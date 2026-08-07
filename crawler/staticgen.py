# 정적 렌더링 — 네이버·구글 검색 유입과 JS 실패 대비 (2026-07-24 리뷰 반영)
#
# 왜: 공고 목록·상세가 전부 클라이언트 JS 렌더링이라 검색 크롤러(특히 네이버)에는
# 빈 페이지로 보인다. 매일 크롤이 커밋+푸시하는 파이프라인이 이미 있으므로,
# 그 시점에 정적 HTML을 같이 만들어 태운다.
#
#  · jobs.html / index.html — STATIC 마커 사이에 공고 목록을 박는다.
#    JS가 살아 있으면 렌더러가 innerHTML로 덮어쓰므로 사용자 경험은 그대로,
#    JS가 죽었거나 검색 봇이면 정적 목록이 그대로 보인다.
#  · p/<id>.html — 공고당 정적 상세 페이지 (검색 착지용, JSON-LD JobPosting 포함)
#  · sitemap.xml / robots.txt
#
# 링크 원칙 준수: 집계 포털로는 링크도, 게시처명 텍스트도 내보내지 않는다 (CLAUDE.md).
import html
import json
import os
import re
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # podium/
SITE = "https://podiumclassical.kr"
# js/jobs.js PORTAL_RE와 같은 목록 — 두 곳이 어긋나면 한쪽에서만 포털 링크가 샌다
PORTAL_RE = re.compile(r"artinfokorea|artmore|hibrain|jobkorea|saramin|albamon|cleaneye|gojobs|work\.go\.kr/portal", re.I)

esc = lambda v: html.escape(str(v or ""), quote=True)


def _status(j, today):
    """카드에 얹는 상태 라벨 (js/jobs.js statusOf의 정적 축약판)"""
    dl = j.get("deadline")
    if not dl:
        return ("상시", "dd-open") if j.get("deadlineNote") == "상시" or j.get("obri") else ("기한 미정", "dd-always")
    diff = (date.fromisoformat(dl) - today).days
    if diff < 0:
        return ("마감", "dd-closed")
    if diff == 0:
        return ("오늘 마감", "dd-soon")
    if diff <= 7:
        return (f"지원 마감 D-{diff}", "dd-soon")
    if diff > 30:
        return ("상시·장기", "dd-open")
    return (f"접수중 (~{int(dl[5:7])}.{int(dl[8:10])})", "dd-open")


def _apply(j):
    """상세 페이지의 지원 경로 — (라벨, href|None). 포털로는 절대 내보내지 않는다."""
    ou = j.get("officialUrl")
    if ou and not PORTAL_RE.search(ou):
        return "공식 공고 페이지 바로가기 ↗", ou
    if PORTAL_RE.search(j.get("source") or ""):
        if j.get("applyEmail"):
            return "이메일로 지원 ✉", f"mailto:{j['applyEmail']}"
        if j.get("applyPhone"):
            return f"전화 지원 ☎ {j['applyPhone']}", "tel:" + re.sub(r"-", "", j["applyPhone"])
        return None, None   # 지원 경로 없음 — 버튼을 만들지 않는다 (main.py가 이런 공고를 걸러낸다)
    return "공고 보러가기 ↗", j.get("url")


def _is_fresh(j, today):
    """NEW: 게시 시작 기준 만 48시간(게시일 당일+다음 날). 기준은 게시일(date),
    모르면 firstSeen 폴백 (jobs.js isFresh·main.py isNew와 같은 규칙)."""
    basis = j.get("date") or j.get("firstSeen")
    if not basis:
        return bool(j.get("isNew"))
    try:
        return 0 <= (today - date.fromisoformat(basis)).days <= 1
    except ValueError:
        return bool(j.get("isNew"))


def _card(j, today, href):
    st, cls = _status(j, today)
    tags = [f'<span class="tag org">{esc(j.get("org"))}</span>']   # 분류 태그와 색이 겹치지 않게 전용 클래스
    if j.get("tier") and j["tier"] != "미분류":
        tags.append(f'<span class="tag src-official">{esc(j["tier"])}</span>')   # 구분은 검정 통일
    for i in (j.get("instDetails") or [])[:3]:
        tags.append(f'<span class="tag inst">{esc(i)}</span>')
    tags.append(f'<span class="tag {cls}">{esc(st)}</span>')
    if _is_fresh(j, today):
        tags.append('<span class="tag urgent">NEW</span>')
    meta = [esc(j.get("region") or "")]
    if j.get("subject"):
        meta.append(esc(j["subject"]))
    if j.get("deadline"):
        meta.append("마감 " + esc(j["deadline"]))
    return (f'<a href="{href}" class="job-card" style="display:block">'
            f'<div class="top-row">{"".join(tags)}</div>'
            f'<h3>{esc(j["title"])}</h3>'
            f'<div class="meta">{"".join(f"<span>{m}</span>" for m in meta if m)}</div></a>')


def _inject(path, marker, content):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    pat = re.compile(rf"(<!-- STATIC:{marker} -->).*?(<!-- /STATIC:{marker} -->)", re.S)
    if not pat.search(src):
        raise RuntimeError(f"{os.path.basename(path)}: STATIC:{marker} 마커가 없다")
    out = pat.sub(lambda m: m.group(1) + content + m.group(2), src)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)


def _detail_rows(j):
    rows = [("기관", j.get("org")), ("지역", j.get("region")),
            ("마감", j.get("deadline") or ("상시 모집" if j.get("deadlineNote") == "상시" or j.get("obri") else "기한 미정"))]
    if j.get("subject"):
        rows.append(("전공", j["subject"]))
    if j.get("courses"):
        rows.append(("교과목", ", ".join(j["courses"])))
    insts = "·".join(j.get("instDetails") or [])
    if j.get("recruitSummary"):
        rows.append(("모집", j["recruitSummary"]))
    elif j.get("personnel"):
        rows.append(("모집", (insts + " " if insts else "") + str(j["personnel"])))
    elif insts:
        rows.append(("모집", insts))
    if j.get("qualification"):
        q = str(j["qualification"])
        if re.search(r"(있는|없는|준하는|가능한|갖춘|마친|수료한|졸업한|이수한|전공한|취득한|소지한)$", q):
            q += " 자"
        rows.append(("자격", q))
    if j.get("pay"):
        rows.append(("페이", j["pay"]))
    if j.get("contract"):
        rows.append(("계약", j["contract"]))
    if j.get("auditionDate"):
        rows.append(("오디션", j["auditionDate"]))
    if j.get("applyEmail"):
        rows.append(("지원 이메일", j["applyEmail"]))
    if j.get("applyPhone"):
        rows.append(("지원 전화", j["applyPhone"]))
    return [(k, v) for k, v in rows if v]


def _jsonld(j):
    d = {"@context": "https://schema.org", "@type": "JobPosting",
         "title": j["title"],
         "datePosted": j.get("date") or j.get("firstSeen") or "",
         "hiringOrganization": {"@type": "Organization", "name": j.get("org") or ""},
         "jobLocation": {"@type": "Place",
                         "address": {"@type": "PostalAddress", "addressRegion": j.get("region") or "", "addressCountry": "KR"}},
         "description": (j.get("bodyExcerpt") or j.get("recruitSummary") or j.get("qualification") or j["title"])[:300]}
    if j.get("deadline"):
        d["validThrough"] = j["deadline"]
    return json.dumps(d, ensure_ascii=False)


def _detail_page(j, today):
    st, cls = _status(j, today)
    label, href = _apply(j)
    # 계측: 검색 유입이 처음 닿는 페이지가 여기다 — 원문 이동 클릭(data-ev)이
    # '포디엄을 보고 지원했다'의 유일한 증거가 된다 (js/analytics.js 위임 클릭)
    _dest = "mail" if (href or "").startswith("mailto:") else "tel" if (href or "").startswith("tel:") else "official"
    _ev = "contact_click" if _dest in ("mail", "tel") else "job_outbound"
    act = (f'<a class="btn-primary" style="text-decoration:none" href="{esc(href)}" target="_blank" rel="noopener" '
           f'data-ev="{_ev}" data-evl="{esc(j.get("org") or "")}|{j["id"]}|{_dest}">{esc(label)}</a>'
           if href and label else "")   # 지원 경로가 없으면 버튼 자체를 만들지 않는다
    rows = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in _detail_rows(j))
    desc = esc((j.get("bodyExcerpt") or j.get("recruitSummary") or f"{j.get('org','')} {j['title']}")[:150])
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(j['title'])} — 포디엄</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="{SITE}/p/{j['id']}.html">
  <link rel="icon" type="image/png" sizes="32x32" href="../favicon-32.png">
  <link rel="apple-touch-icon" href="../apple-touch-icon.png">
  <meta name="theme-color" content="#7a2a38">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="포디엄">
  <meta property="og:title" content="{esc(j['title'])} — {esc(j.get('org'))}">
  <meta property="og:description" content="{desc}">
  <meta property="og:url" content="{SITE}/p/{j['id']}.html">
  <meta property="og:image" content="{SITE}/og-image.png">
  <meta property="og:locale" content="ko_KR">
  <meta name="twitter:card" content="summary_large_image">
  <link href="https://fonts.googleapis.com/css2?family=Gowun+Batang:wght@400;700&family=Cormorant:wght@500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../css/style.css?v=14">
  <script src="../js/analytics.js?v=2" defer></script>
  <script type="application/ld+json">{_jsonld(j)}</script>
</head>
<body>
<header class="site-header"><div class="container">
  <a href="../index.html" class="logo">포디엄<span class="accent">.</span><span class="beta">BETA</span></a>
  <nav class="main-nav"><a href="../jobs.html" class="active">구인구직</a><a href="../practice.html">연습실</a><a href="../about.html">소개</a></nav>
</div></header>
<div class="page-head"><div class="container">
  <div class="top-row">
    <span class="tag src-official">{esc(j.get('org'))}</span>
    {f'<span class="tag src-official">{esc(j["tier"])}</span>' if j.get('tier') and j['tier'] != '미분류' else ''}
    <span class="tag {cls}">{esc(st)}</span>
  </div>
  <h1 style="font-size:1.35rem;margin-top:8px">{esc(j['title'])}</h1>
</div></div>
<main class="container" style="padding-block:20px 40px;max-width:720px">
  <dl class="detail-meta">{rows}</dl>
  <div class="modal-actions" style="margin-top:20px">{act}
    <a class="btn-outline" style="text-decoration:none" href="../jobs.html">전체 공고 보기</a></div>
  <p style="font-size:0.78rem;color:var(--ink-soft);margin-top:24px">
    이 페이지는 기관이 공개한 공고를 매일 자동 수집해 요약한 것입니다. 지원 전 반드시 원문에서 최종 확인하세요.
    · <a href="../sources.html" style="color:inherit">수집 원천</a></p>
</main>
<footer class="site-footer"><div class="container">
  <span class="logo serif">포디엄<span class="accent">.</span></span><br>
  클래식 음악인을 위한 공고 집약 플랫폼 · v2.0 · <a href="../sources.html" style="color:inherit">수집 원천</a> · <a href="../privacy.html" style="color:inherit">개인정보 처리방침</a>
</div></footer>
</body>
</html>
"""


def generate(base=BASE):
    with open(os.path.join(base, "data", "official.json"), encoding="utf-8") as f:
        doc = json.load(f)
    today = date.today()
    items = [j for j in doc.get("items", [])
             if not (j.get("deadline") and j["deadline"] < today.isoformat())]
    # 마감 임박순 (jobs.js 기본 정렬과 동일 취지: 마감 가까운 순 → 무마감·상시는 뒤)
    def key(j):
        dl = j.get("deadline")
        if dl:
            return (0, dl)
        return (1, "") if not (j.get("deadlineNote") == "상시" or j.get("obri")) else (2, "")
    items.sort(key=key)

    # 1) 상세 페이지 — p/ 를 현재 공고로 전면 재생성 (내려간 공고 페이지는 제거)
    pdir = os.path.join(base, "p")
    os.makedirs(pdir, exist_ok=True)
    for f_ in os.listdir(pdir):
        if f_.endswith(".html"):
            os.remove(os.path.join(pdir, f_))
    for j in items:
        with open(os.path.join(pdir, f"{j['id']}.html"), "w", encoding="utf-8") as f:
            f.write(_detail_page(j, today))

    # 2) 목록 정적 삽입 — 카드는 정적 상세 페이지로 링크 (검색 봇의 착지 경로)
    _inject(os.path.join(base, "jobs.html"), "LIST",
            "".join(_card(j, today, f"p/{j['id']}.html") for j in items))
    recent = sorted(items, key=lambda j: str(j.get("date") or j.get("firstSeen") or ""), reverse=True)[:8]
    _inject(os.path.join(base, "index.html"), "RECENT",
            "".join(_card(j, today, f"p/{j['id']}.html") for j in recent))

    # 3) sitemap + robots
    lastmod = (doc.get("collectedAt") or today.isoformat())[:10]
    urls = [f"{SITE}/{p}" for p in ("", "jobs.html", "practice.html", "about.html", "sources.html", "privacy.html")]
    urls += [f"{SITE}/p/{j['id']}.html" for j in items]
    with open(os.path.join(base, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        f.write("".join(f"<url><loc>{u}</loc><lastmod>{lastmod}</lastmod></url>\n" for u in urls))
        f.write("</urlset>\n")
    with open(os.path.join(base, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    return len(items)


if __name__ == "__main__":
    n = generate()
    print(f"정적 생성 완료: 공고 {n}건 (p/*.html, jobs/index 목록, sitemap.xml)")
