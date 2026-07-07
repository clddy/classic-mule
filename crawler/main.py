# 메인: 전 기관 수집 → 필터 → 상세/첨부에서 마감일 보강 → data/official.json
import json, os, re, sys, time, traceback
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import new_session, get, relevant, extract_deadline
from sources import PARSERS
import attach

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # classic-mule/
OUT = os.path.join(BASE, "data", "official.json")
LOG = os.path.join(BASE, "data", "crawl.log")

MAX_DETAIL_PER_SOURCE = 10    # 마감일 보강용 상세 페이지 조회 상한
RECENT_DAYS = 270             # 이보다 오래된 게시물은 버림 (마감 미래면 유지)

def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def find_attachments(soup, base_url):
    """첨부파일 후보 URL — 확장자 링크뿐 아니라 download.do 류 CMS 다운로드 링크까지"""
    from urllib.parse import urljoin
    cands, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("javascript", "#", "mailto")):
            continue
        text = a.get_text(" ", strip=True)
        if (re.search(r"\.(pdf|hwpx?|zip)(\?|$)", href, re.I)
                or re.search(r"\.(pdf|hwpx?|zip)\b", text, re.I)
                or re.search(r"download|fileDown|file\.do|atchFile|attach|dwld|fileId|process\.file", href, re.I)):
            full = urljoin(base_url, href)
            if full not in seen:
                seen.add(full)
                cands.append((full, text))
    return cands[:3]

def enrich_deadline(s, item):
    """상세 페이지 본문 → 없으면 첨부파일(PDF/HWP/HWPX/ZIP)에서 접수 마감일 추출"""
    try:
        r = get(s, item["url"])
        if r.status_code != 200:
            return
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "header", "footer", "nav"]):
            tag.decompose()
        dl = extract_deadline(soup.get_text(" ", strip=True))
        if dl:
            item["deadline"] = dl
            item["deadlineFrom"] = "page"
            return
        for furl, fname in find_attachments(soup, r.url):
            try:
                fr = s.get(furl, timeout=30, verify=False)
                if fr.status_code != 200 or len(fr.content) > 20_000_000 or len(fr.content) < 200:
                    continue
                # Content-Disposition에서 실제 파일명 확보
                cd = fr.headers.get("Content-Disposition", "")
                m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
                name = m.group(1) if m else (fname or furl)
                ftext = attach.extract_any(name, fr.content)
                dl = extract_deadline(ftext)
                if dl:
                    item["deadline"] = dl
                    item["deadlineFrom"] = "attachment"
                    return
            except Exception:
                continue
    except Exception as e:
        log(f"  enrich 실패 {item['url'][:60]}: {type(e).__name__}")

def run():
    today = date.today()
    cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    # 이전 데이터 로드 (firstSeen 유지용)
    prev = {}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                for it in json.load(f).get("items", []):
                    prev[it["id"]] = it
        except Exception:
            pass

    all_items, source_stats = [], []
    for sid, name, fn in PARSERS:
        s = new_session()
        try:
            raw = fn(s)
            kept = []
            for it in raw:
                if not relevant(it["title"]):
                    continue
                future_dl = it["deadline"] and it["deadline"] >= today.isoformat()
                # 오래된 글 컷 (마감이 미래면 유지)
                if it["date"] and it["date"] < cutoff and not future_dl:
                    continue
                # 제목 연도가 작년 이전이고 마감도 지났으면 컷
                ym = re.search(r"20\d{2}", it["title"])
                if ym and int(ym.group(0)) < today.year and not future_dl:
                    continue
                # 마감 지난 지 60일 넘은 공고 컷
                stale = (today - timedelta(days=60)).isoformat()
                if it["deadline"] and it["deadline"] < stale:
                    continue
                kept.append(it)
            # 지난 수집에서 알아낸 마감일은 승계 (매일 재추출 방지)
            for it in kept:
                old = prev.get(it["id"])
                if old and not it["deadline"] and old.get("deadline"):
                    it["deadline"] = old["deadline"]
                    if old.get("deadlineFrom"):
                        it["deadlineFrom"] = old["deadlineFrom"]
            # 마감일 없는 최신 글만 상세 보강
            need = [i for i in kept if not i["deadline"]][:MAX_DETAIL_PER_SOURCE]
            for it in need:
                enrich_deadline(s, it)
            all_items.extend(kept)
            source_stats.append({"id": sid, "name": name, "ok": True,
                                 "raw": len(raw), "kept": len(kept)})
            log(f"OK  {name}: 원본 {len(raw)}건 → 수집 {len(kept)}건")
        except Exception as e:
            source_stats.append({"id": sid, "name": name, "ok": False,
                                 "error": f"{type(e).__name__}: {str(e)[:120]}"})
            log(f"FAIL {name}: {type(e).__name__}: {str(e)[:120]}")
            traceback.print_exc()

    # 중복 제거 + firstSeen/isNew
    seen, final = set(), []
    for it in all_items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        old = prev.get(it["id"])
        it["firstSeen"] = old.get("firstSeen", today.isoformat()) if old else today.isoformat()
        it["isNew"] = it["firstSeen"] == today.isoformat()
        final.append(it)

    final.sort(key=lambda x: (x.get("date") or x["firstSeen"]), reverse=True)

    payload = {
        "collectedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sourceCount": len(PARSERS),
        "okCount": sum(1 for x in source_stats if x["ok"]),
        "sources": source_stats,
        "items": final,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    # 사이트에서 file:// 로도 열리도록 JS 파일로도 출력
    with open(os.path.join(BASE, "data", "official-data.js"), "w", encoding="utf-8") as f:
        f.write("window.CRAWLED = ")
        json.dump(payload, f, ensure_ascii=False)
        f.write(";\n")

    log(f"완료: {len(final)}건 저장 → {OUT}")

if __name__ == "__main__":
    run()
