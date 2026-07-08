# 메인: 소스 레지스트리 기반 수집 → dedup(canonical) → 마감일 보강 → 커버리지 리포트
import json, os, re, sys, time, traceback
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (new_session, get, relevant, extract_deadline, deadline_from_title,
                    musician_relevant, parse_recruit_table, summarize_recruit, find_position)
from sources import SOURCES
from institutions import INSTITUTIONS
import attach

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # classic-mule/
OUT = os.path.join(BASE, "data", "official.json")
LOG = os.path.join(BASE, "data", "crawl.log")
COVERAGE = os.path.join(BASE, "data", "coverage_report.json")

MAX_DETAIL_PER_SOURCE = 14
RECENT_DAYS = 270
LAYER_RANK = {"D": 0, "C": 1, "B": 2, "A": 3}  # canonical 우선순위: 원천 > 도메인 > 지역 > 전국

def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def should_run(src, today, force_all=False):
    """폴링 게이팅: daily는 항상, weekly는 지정 요일, seasonal은 시즌 내 daily"""
    if force_all:
        return True
    if src["poll"] == "daily":
        return True
    if src["poll"] == "seasonal":
        return src["months"] and today.month in src["months"]
    return today.weekday() in src["days"]

# ---------- dedup (canonical) ----------
def norm_org(s):
    s = re.sub(r"\(재\)|재단법인|사단법인|\s+", "", s or "")
    return re.sub(r"[()\[\]·.]", "", s)

def norm_title(s):
    # 변경공고/재공고는 원공고와 같은 건으로 취급 (dedup 시 최신 것이 canonical)
    s = re.sub(r"변경 ?공고|재공고|수정 ?공고", "", s or "")
    return re.sub(r"[\s\[\]()〈〉<>『』「」·.,\-~!?]", "", s)[:40]

# 집계 채널의 일반(placeholder) org — 기관 특정이 안 되므로 병합 금지
GENERIC_ORG = re.compile(r"기독정보넷|아트인포|아트모아|교육청 ?포털")

def dedup_key(it):
    if GENERIC_ORG.search(it.get("org", "")):
        return it["id"]  # 병합하지 않음
    if it.get("deadline"):
        return f"{norm_org(it['org'])}|{'/'.join(sorted(it.get('instDetails') or []))}|{it['deadline']}"
    return f"{norm_org(it['org'])}|{norm_title(it['title'])}"

def dedup(items):
    groups = {}
    for it in items:
        groups.setdefault(dedup_key(it), []).append(it)
    out = []
    for group in groups.values():
        # 같은 층위면 최신 게시(변경공고)를 canonical로
        group.sort(key=lambda x: x.get("date") or "", reverse=True)
        group.sort(key=lambda x: LAYER_RANK.get(x.get("layer", "A"), 9))
        canon = group[0]
        others = sorted({g["source"] for g in group[1:] if g["source"] != canon["source"]})
        if others:
            canon["alsoSeenOn"] = others
        out.append(canon)
    return out

# ---------- 커버리지 대조 ----------
def coverage_report(items, today):
    haystack = " ".join(f"{i['org']} {i['title']}" for i in items)
    covered, gaps = [], []
    for inst in INSTITUTIONS:
        if re.search(inst["match"], haystack):
            covered.append(inst["name"])
        else:
            gaps.append({"name": inst["name"], "type": inst["type"], "region": inst["region"]})
    report = {"date": today.isoformat(), "total": len(INSTITUTIONS),
              "covered": len(covered), "gapCount": len(gaps), "gaps": gaps}
    with open(COVERAGE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    log(f"커버리지: 명부 {len(INSTITUTIONS)}곳 중 {len(covered)}곳 공고 확인, 공백 {len(gaps)}곳 → coverage_report.json")
    return report

# ---------- 마감일 보강 ----------
ATTACH_LINK = re.compile(r"download|fileDown|file\.do|atchFile|attach|dwld|fileId|process\.file", re.I)

def find_attachments(soup, base_url):
    from urllib.parse import urljoin
    cands, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("javascript", "#", "mailto")):
            continue
        text = a.get_text(" ", strip=True)
        if (re.search(r"\.(pdf|hwpx?|zip)(\?|$)", href, re.I)
                or re.search(r"\.(pdf|hwpx?|zip)\b", text, re.I)
                or ATTACH_LINK.search(href)):
            full = urljoin(base_url, href)
            if full not in seen:
                seen.add(full)
                cands.append((full, text))
    return cands[:3]

EXT_VER = 4         # 마감일 추출기 버전 — 올리면 이전 수집의 마감일 승계가 무효화됨
RENDER_PER_SOURCE = 3   # 소스당 Playwright 렌더링 상한
OCR_PER_SOURCE = 6      # 소스당 이미지 공고문 OCR 상한 (항목당 최대 2장)
_renders_used = 0
_ocr_used = 0

IMG_SRC = re.compile(r'<img[^>]+src="((?:data:image/[^"]+|[^"]*(?:editor|upload|atch|cmmn|bbs)[^"]*\.(?:png|jpe?g)[^"]*))"', re.I)

def _content_images(html, base_url):
    """본문 영역의 공고문 이미지 후보 (base64 임베드 또는 업로드 경로)"""
    import base64
    from urllib.parse import urljoin
    out = []
    for m in IMG_SRC.finditer(html):
        src = m.group(1)
        if src.startswith("data:image"):
            try:
                b64 = src.split(",", 1)[1]
                if len(b64) > 50_000:  # 아이콘 제외
                    out.append(("__inline__", base64.b64decode(b64)))
            except Exception:
                pass
        else:
            out.append((urljoin(base_url, src), None))
        if len(out) >= 2:
            break
    return out

def _ref_year(item):
    d = item.get("date") or ""
    return int(d[:4]) if re.match(r"^20\d{2}", d) else None

def _find_audition(text):
    """실기전형/오디션 키워드 근처 날짜 → 'M/D' (첫 1~2개)"""
    for kw in re.finditer(r"실기 ?전형|오디션|실기 ?심사|실기 ?시험|실기 ?일정", text):
        w = text[kw.start(): kw.start() + 160]
        ds = re.findall(r"20\d{2}\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})", w)
        if ds:
            segs = [f"{int(mo)}/{int(d)}" for mo, d in ds[:2]]
            return " · ".join(segs)
    return None

def _find_contract(text):
    m = re.search(r"(계약 ?기간|위촉 ?기간)\s*:?\s*([^\n·|]{4,40})", text)
    if m:
        return re.sub(r"\s+", " ", m.group(2)).strip(" .:")
    m = re.search(r"(1년 ?계약직?|기간제|시즌 ?단원|비상임|상임)", text)
    return m.group(1) if m else None

def _extract_body_details(soup, page_text, item, ry):
    """본문에서 채용부문/직책/인원 표 + 직책 + 오디션 + 계약기간 추출"""
    if not item.get("recruitParts"):
        parts = parse_recruit_table(soup)
        if parts:
            item["recruitParts"] = parts
            summ, positions, total = summarize_recruit(parts)
            item["recruitSummary"] = summ
            if positions:
                item["positions"] = positions
            if summ:
                item["personnel"] = summ  # 표 요약을 모집인원 표기로 승격
    if not item.get("positions"):
        pos = find_position(item.get("title", "")) or find_position(page_text[:500])
        if pos:
            item["positions"] = [pos]
    if not item.get("auditionDate"):
        a = _find_audition(page_text)
        if a:
            item["auditionDate"] = a
    if not item.get("contract") and item.get("kind") == "단원":
        c = _find_contract(page_text)
        if c:
            item["contract"] = c

def enrich_deadline(s, item, allow_render=True):
    global _renders_used
    ry = _ref_year(item)
    try:
        r = get(s, item["url"])
        if r.status_code != 200:
            return
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "header", "footer", "nav"]):
            tag.decompose()
        page_text = soup.get_text(" ", strip=True)
        # 채용부문/직책/인원 표 등 본문 상세 (마감 유무와 무관하게 항상)
        _extract_body_details(soup, page_text, item, ry)
        # 게시일이 없으면 상세의 등록일로 보충 (연령 정리·연도 보정에 사용)
        if not item.get("date"):
            m = re.search(r"등록일\s*:?\s*(20\d{2}-\d{2}-\d{2})", page_text)
            if m:
                item["date"] = m.group(1)
        # 상시모집 감지: 기독정보넷의 '남은기간 0000-00-00', 통상 표현들
        if re.search(r"남은기간\s*0000-00-00|상시 ?모집|상시 ?채용|채용 ?시 ?(?:까지|마감)|충원 ?시 ?마감", page_text):
            item["deadlineNote"] = "상시"
            return
        dl = extract_deadline(page_text, ref_year=ry)
        if dl:
            item["deadline"] = dl
            item["deadlineFrom"] = "page"
            return
        for furl, fname in find_attachments(soup, r.url):
            try:
                # 일부 CMS(부천 등)는 Referer 없으면 다운로드 거부
                fr = s.get(furl, timeout=30, verify=False, headers={"Referer": item["url"]})
                if fr.status_code != 200 or not (200 < len(fr.content) < 20_000_000):
                    continue
                cd = fr.headers.get("Content-Disposition", "")
                m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
                name = m.group(1) if m else (fname or furl)
                dl = extract_deadline(attach.extract_any(name, fr.content), ref_year=ry)
                if dl:
                    item["deadline"] = dl
                    item["deadlineFrom"] = "attachment"
                    return
            except Exception:
                continue
        # 공고문이 이미지로만 게시된 경우 — OCR 폴백
        global _ocr_used
        if allow_render and _ocr_used < OCR_PER_SOURCE:
            for src_url, blob in _content_images(r.text, r.url):
                try:
                    _ocr_used += 1
                    data = blob if blob else s.get(src_url, timeout=30, verify=False).content
                    dl = extract_deadline(attach.ocr_image(data), ref_year=ry)
                    if dl:
                        item["deadline"] = dl
                        item["deadlineFrom"] = "ocr"
                        return
                except Exception:
                    continue
                if _ocr_used >= OCR_PER_SOURCE:
                    break
        # 본문이 JS 렌더링인 페이지 — 헤드리스 크롬 폴백
        global _renders_used
        if allow_render and _renders_used < RENDER_PER_SOURCE:
            try:
                from jsfetch import render
                _renders_used += 1
                html = render(item["url"], wait_ms=2500)
                jsoup = BeautifulSoup(html, "lxml")
                for tag in jsoup(["script", "style", "header", "footer", "nav"]):
                    tag.decompose()
                dl = extract_deadline(jsoup.get_text(" ", strip=True), ref_year=ry)
                if dl:
                    item["deadline"] = dl
                    item["deadlineFrom"] = "page-js"
            except Exception:
                pass
    except Exception:
        log(f"  enrich 실패 {item['url'][:60]}")

# ---------- 메인 ----------
def run(force_all=False):
    today = date.today()
    cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()
    stale = (today - timedelta(days=60)).isoformat()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    prev_items, prev_by_id = [], {}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                prev_items = json.load(f).get("items", [])
                prev_by_id = {it["id"]: it for it in prev_items}
        except Exception:
            pass

    all_items, source_stats = [], []
    for src in SOURCES:
        meta = {"id": src["id"], "name": src["name"], "layer": src["layer"], "poll": src["poll"]}
        if not should_run(src, today, force_all):
            # 오늘 폴링 차례가 아님 → 이전 수집분 승계
            carried = [it for it in prev_items if it.get("channel") == src["id"]
                       or (not it.get("channel") and src["domain"] in it.get("source", ""))]
            for it in carried:
                it["channel"] = src["id"]
                it["layer"] = src["layer"]
            all_items.extend(carried)
            source_stats.append({**meta, "ok": True, "skipped": True, "kept": len(carried)})
            log(f"SKIP {src['name']} (폴링 주기 아님) — 이전 {len(carried)}건 승계")
            continue
        s = new_session()
        try:
            raw = src["fn"](s)
            kept = []
            for it in raw:
                if not relevant(it["title"]):
                    continue
                if not musician_relevant(it["title"], it["kind"], it.get("org", "")):
                    continue
                future_dl = it["deadline"] and it["deadline"] >= today.isoformat()
                if it["date"] and it["date"] < cutoff and not future_dl:
                    continue
                ym = re.search(r"20\d{2}", it["title"])
                if ym and int(ym.group(0)) < today.year and not future_dl:
                    continue
                if it["deadline"] and it["deadline"] < stale:
                    continue
                it["channel"] = src["id"]
                it["layer"] = src["layer"]
                kept.append(it)
            global _renders_used, _ocr_used
            _renders_used = 0
            _ocr_used = 0
            # 지난 수집의 마감일 승계(추출기 버전 일치 시) → 제목 → 상세/첨부/OCR/JS렌더
            for it in kept:
                old = prev_by_id.get(it["id"])
                if (old and not it["deadline"] and old.get("deadline")
                        and old.get("extVer") == EXT_VER):
                    it["deadline"] = old["deadline"]
                    if old.get("deadlineFrom"):
                        it["deadlineFrom"] = old["deadlineFrom"]
                if old and old.get("extVer") == EXT_VER:
                    if old.get("deadlineNote") and not it.get("deadlineNote"):
                        it["deadlineNote"] = old["deadlineNote"]
                    if old.get("date") and not it.get("date"):
                        it["date"] = old["date"]
                    # 본문 파싱 결과(직책·인원·오디션·계약) 승계 — 재파싱 방지
                    for f_ in ("recruitParts", "recruitSummary", "positions",
                               "personnel", "auditionDate", "contract"):
                        if old.get(f_) and not it.get(f_):
                            it[f_] = old[f_]
                if not it["deadline"]:
                    tdl = deadline_from_title(it["title"], ref_year=_ref_year(it))
                    if tdl:
                        it["deadline"] = tdl
                        it["deadlineFrom"] = "title"
            # 상세 파싱 대상: 마감 미확인 + (단원·객원인데 직책/인원 아직 없음)
            need = [i for i in kept if not i["deadline"]]
            recruit_need = [i for i in kept
                            if i.get("kind") in ("단원", "객원·대체")
                            and not i.get("recruitParts") and i not in need]
            for it in (need + recruit_need)[:MAX_DETAIL_PER_SOURCE]:
                enrich_deadline(s, it, allow_render=src["layer"] in ("B", "D"))
            # 마감이 게시일보다 앞서면 공고문 연도 오타로 보고 +1년 보정
            for it in kept:
                if it["deadline"] and it["date"] and it["deadline"] < it["date"]:
                    fixed = f"{int(it['deadline'][:4]) + 1}{it['deadline'][4:]}"
                    if fixed <= f"{int(it['date'][:4]) + 1}-12-31":
                        it["deadline"] = fixed
                        it["deadlineFrom"] = (it.get("deadlineFrom") or "") + "+yearfix"
            # 보강으로 알게 된 마감이 이미 한참 지난 공고는 제거 (작년 공고 등)
            kept = [i for i in kept if not (i["deadline"] and i["deadline"] < stale)]
            # 마감을 못 찾았고 게시된 지 120일 넘은 공고도 정리 (상시모집은 예외)
            old_cut = (today - timedelta(days=120)).isoformat()
            kept = [i for i in kept if i["deadline"] or i.get("deadlineNote") == "상시"
                    or not i["date"] or i["date"] >= old_cut]
            # 소스가 비정상적으로 0건 반환(서버 다운 등) 시 이전 수집분 승계
            if not raw:
                carried = [it for it in prev_items if it.get("channel") == src["id"]]
                if carried:
                    kept = carried
                    log(f"WARN {src['name']}: 0건 반환 — 이전 {len(carried)}건 승계 (서버 장애 추정)")
            all_items.extend(kept)
            source_stats.append({**meta, "ok": True, "raw": len(raw), "kept": len(kept)})
            log(f"OK  {src['name']}: 원본 {len(raw)}건 → 수집 {len(kept)}건")
        except Exception as e:
            source_stats.append({**meta, "ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"})
            log(f"FAIL {src['name']}: {type(e).__name__}: {str(e)[:120]}")
            traceback.print_exc()

    # id 중복 제거 → canonical dedup → firstSeen
    seen, uniq = set(), []
    for it in all_items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)
    final = dedup(uniq)
    # 승계 경로로 들어온 항목까지 포함해 음악인 대상 필터를 최종 일괄 적용
    final = [i for i in final if musician_relevant(i["title"], i.get("kind", ""), i.get("org", ""))]
    for it in final:
        old = prev_by_id.get(it["id"])
        it["firstSeen"] = old.get("firstSeen", today.isoformat()) if old else today.isoformat()
        it["isNew"] = it["firstSeen"] == today.isoformat()
        it["extVer"] = EXT_VER
    final.sort(key=lambda x: (x.get("date") or x["firstSeen"]), reverse=True)

    payload = {
        "collectedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sourceCount": len(SOURCES),
        "okCount": sum(1 for x in source_stats if x["ok"]),
        "sources": source_stats,
        "items": final,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    with open(os.path.join(BASE, "data", "official-data.js"), "w", encoding="utf-8") as f:
        f.write("window.CRAWLED = ")
        json.dump(payload, f, ensure_ascii=False)
        f.write(";\n")

    coverage_report(final, today)
    log(f"완료: {len(final)}건 저장 (dedup 전 {len(uniq)}건) → {OUT}")

if __name__ == "__main__":
    run(force_all="--all" in sys.argv)
