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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from slug import build as build_slug  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # podium/
SITE = "https://podiumclassical.kr"
# js/jobs.js PORTAL_RE와 같은 목록 — 두 곳이 어긋나면 한쪽에서만 포털 링크가 샌다
PORTAL_RE = re.compile(r"artinfokorea|artmore|hibrain|jobkorea|saramin|albamon|cleaneye|gojobs|work\.go\.kr/portal", re.I)

XML_HEAD = '<?xml version="1.0" encoding="UTF-8"?>' + chr(10)
URLSET_OPEN = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + chr(10)
URLSET_CLOSE = "</urlset>" + chr(10)
URL_ROW = "<url><loc>{u}</loc><lastmod>{m}</lastmod></url>" + chr(10)
INDEX_OPEN = '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + chr(10)
INDEX_ROW = "<sitemap><loc>{s}/sitemap-{n}.xml</loc><lastmod>{m}</lastmod></sitemap>" + chr(10)
INDEX_CLOSE = "</sitemapindex>" + chr(10)

esc = lambda v: html.escape(str(v or ""), quote=True)


def _status(j, today):
    """카드에 얹는 상태 라벨 (js/jobs.js statusOf의 정적 축약판)"""
    dl = j.get("deadline")
    # 상시모집은 날짜보다 앞선다 (js/jobs.js statusOf와 같은 규칙 — 어긋나면 정적 목록과
    # JS 렌더가 다른 배지를 보여준다)
    if j.get("deadlineNote") == "상시" or (j.get("obri") and not dl):
        return ("상시모집", "dd-open")
    if not dl:
        return ("기한 미정", "dd-always")
    diff = (date.fromisoformat(dl) - today).days
    if diff < 0:
        return ("마감", "dd-closed")
    if diff == 0:
        return ("오늘 마감", "dd-soon")
    # D-day는 사흘 안쪽에서만, 표기는 'D-3'만 (js/jobs.js statusOf와 같은 규칙 — 어긋나면
    # 정적 목록과 JS 렌더가 다른 배지를 보여준다)
    if diff <= 3:
        return (f"D-{diff}", "dd-soon")
    # 마감이 멀어도 '상시'가 아니다 — 날짜가 있으면 날짜를 보여준다 (js/jobs.js와 같은 규칙)
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
            ("마감", "상시모집" if j.get("deadlineNote") == "상시"
             else (j.get("deadline") or ("상시모집" if j.get("obri") else "기한 미정")))]
    if j.get("subject"):
        rows.append(("전공", j["subject"]))
    if j.get("courses"):
        rows.append(("교과목", ", ".join(j["courses"])))
    insts = "·".join(j.get("instDetails") or [])
    if j.get("recruitSummary"):
        rows.append(("모집", j["recruitSummary"]))
    elif j.get("personnel"):
        # 악기를 여기 또 붙이지 않는다 — 카드 위쪽 태그와 겹친다 (2026-08-21)
        rows.append(("모집", str(j["personnel"])))
    elif insts:
        rows.append(("모집", insts))
    # 담당업무는 '무엇을 하는 자리인가'라 지원 판단의 핵심인데 정적 상세에만 빠져 있었다
    # (화면 모달에는 있었다). 검색 착지 페이지가 화면보다 적게 말할 이유가 없다 (2026-08-21).
    if j.get("duty"):
        rows.append(("담당업무", j["duty"]))
    if j.get("workPeriod"):
        rows.append(("근무기간", j["workPeriod"]))
    if j.get("workHours"):
        rows.append(("근무시간", j["workHours"]))
    # 자격 행은 보여주지 않는다 (2026-08-23 사용자 지시) — 화면 모달과 같은 규칙.
    # 값 대부분이 어느 공고에나 붙는 상투구라 정보가 0이다.
    if j.get("pay"):
        rows.append(("페이", j["pay"]))
    if j.get("contract"):
        rows.append(("계약", j["contract"]))
    if j.get("auditionDate"):
        rows.append(("오디션", j["auditionDate"]))
    # 전화·이메일 병기 — 화면 모달(js/jobs.js 연락처 행)과 같은 꼴 (워크오더 08-16 §5)
    if j.get("contact") or j.get("email"):
        rows.append(("연락처", " · ".join(str(j[k]) for k in ("contact", "email") if j.get(k))))
    if j.get("applyEmail"):
        rows.append(("지원 이메일", j["applyEmail"]))
    if j.get("applyPhone"):
        rows.append(("지원 전화", j["applyPhone"]))
    return [(k, v) for k, v in rows if v]



# ---------- description = 필드 조립 (본문 발췌 폐기, 작업 A-2 / 2026-08-19) ----------
# 본문 발췌는 게시 28건 중 14건이 약관·공백으로 오염돼 있었다. 발췌를 다듬는 대신
# 우리가 이미 검증해 둔 필드만으로 문장을 짓는다 — 오염원이 구조적으로 사라진다.

def _pay_short(pay):
    """'시급 40000원' → '시급 4만원'. 금액을 못 읽으면 None(절 자체를 생략)."""
    if not pay:
        return None
    t = re.sub(r"\s+", " ", str(pay))
    m = re.search(r"([\d,]+)\s*(?:만\s*)?원", t)
    if not m:
        return None
    try:
        won = int(m.group(1).replace(",", ""))
    except ValueError:
        return None
    if "만" in t[m.end() - 2:m.end() + 1]:
        won *= 10000
    # 단위는 금액 앞을 본다 — '세전 월 550,000원'처럼 낱말이 떨어져 있어도 월급이다
    before = t[:m.start()]
    unit = ("시급" if re.search(r"시급|시간\s*당", t) else
            "일당" if re.search(r"일당|일\s*급", t) else
            "월급" if re.search(r"월급|월\s*액|월\s*보수|월\s*$", before) else
            "회당" if re.search(r"회당|건당", t) else "")
    if won >= 10000:
        amt = f"{won // 10000}만원" if won % 10000 == 0 else f"{won / 10000:.1f}만원"
    else:
        amt = f"{won:,}원"
    return f"{unit} {amt}".strip()


def build_description(j):
    """검증된 필드로 짓는 70~110자 설명. 결측은 절 단위로 자연 생략한다."""
    inst = "·".join(j.get("instDetails") or []) or j.get("subject")
    kind = j.get("kind")
    # '지휘 지휘 채용'처럼 악기와 직무가 같은 말이면 한 번만 쓴다
    what = " ".join(dict.fromkeys(x for x in (inst, kind) if x))
    head = " ".join(x for x in (j.get("org"), what) if x).strip()
    head = f"{head} 채용." if head else (j.get("title") or "").strip()
    tail = [j.get("region"),
            _pay_short(j.get("pay")),
            (f"{int(j['deadline'][5:7])}/{int(j['deadline'][8:10])} 마감"
             if (j.get("deadline") or "").count("-") == 2 else
             ("상시모집" if j.get("deadlineNote") == "상시" else None)),
            j.get("workHours"),
            (f"근무 {j['workPeriod']}" if j.get("workPeriod") and len(str(j["workPeriod"])) <= 34 else None)]
    parts = [p for p in tail if p]
    # 110자를 넘으면 뒤에서부터 덜어낸다 — 지역·마감이 페이·근무시간보다 중요하다
    order = [0, 2, 1, 3, 4]
    keep = [p for i, p in enumerate(parts)]
    while keep and len(head + ", ".join(keep)) > 108:
        drop = max((i for i in range(len(keep))), key=lambda i: order.index(min(i, 3)))
        keep.pop(drop)
    return (head + (" " + ", ".join(keep) + "." if keep else "")).strip()[:110]



# JSON-LD 보강 (작업 C) — 결측 키는 넣지 않는다(빈 문자열 금지), 화면에 없는 정보는 만들지 않는다.
_PAY_UNIT = [(r"시급|시간\s*당", "HOUR"), (r"일당|일\s*급", "DAY"),
             (r"주급|주\s*당", "WEEK"), (r"월급|월\s*액|월\s*보수|세전\s*월|월\s*\d", "MONTH"),
             (r"연봉|연\s*급", "YEAR")]
# 직무 → 고용형태. 확실한 것만 매긴다 — 모르면 키 자체를 생략한다.
_EMP = {"교수": "PART_TIME", "강사": "PART_TIME", "단원": "PART_TIME",
        "객원·대체": "TEMPORARY", "직원": "FULL_TIME", "교원": "CONTRACTOR"}


def _base_salary(j):
    """baseSalary — 금액과 단위를 둘 다 읽었을 때만 만든다."""
    pay = j.get("pay")
    if not pay:
        return None
    t = re.sub(r"\s+", " ", str(pay))
    m = re.search(r"([\d,]+)\s*(만\s*)?원", t)
    if not m:
        return None
    try:
        won = int(m.group(1).replace(",", "")) * (10000 if m.group(2) else 1)
    except ValueError:
        return None
    unit = next((u for pat, u in _PAY_UNIT if re.search(pat, t)), None)
    if not unit or won < 1000:
        return None                      # 단위 불명이면 생략 (작업 C 규칙)
    return {"@type": "MonetaryAmount", "currency": "KRW",
            "value": {"@type": "QuantitativeValue", "value": won, "unitText": unit}}



def build_title(j):
    """검색결과에 뜨는 제목 (작업 E, 2026-08-20).

    "{지역} {기관축약} {악기·전공} {직무} 채용 ({페이}, ~{M/D}) — 포디엄"
    한글 30자 안팎을 노리고, 넘치면 페이 → 마감 → '— 포디엄' 순으로 덜어낸다.
    h1(공고 제목 원문)은 건드리지 않는다 — 화면에 보이는 글자는 그대로 두고
    검색결과용 표기만 다르게 짓는 것이다.
    """
    from slug import org_name_ko
    name = org_name_ko(j.get("org"))
    what = "·".join(j.get("instDetails") or []) or (j.get("subject") or "")
    what = re.sub(r"(?:학과|학부|전공|과)$", "", str(what).split("·")[0]) if what else ""
    kind = j.get("kind") or ""
    if what and kind and what == kind:
        kind = ""                       # '지휘 지휘' 방지
    # '전체'·'기타'처럼 값이 없다는 뜻의 표기는 제목에 싣지 않는다
    if what in ("전체", "기타", "미상", "무관"):
        what = ""
    region = j.get("region") or ""
    if region in ("기타", "전국"):
        region = ""
    # 기관명이 이미 지역으로 시작하면 앞의 지역을 빼 '부산 부산문화회관'을 막는다
    if region and name.startswith(region):
        region = ""
    bits = []
    for x in (region, name, what, kind):
        if x and x not in bits:          # 같은 말이 두 번 들어가지 않게
            bits.append(x)
    head = " ".join(bits).strip()
    head = (head + " 채용") if head else (j.get("title") or "")
    pay = _pay_short(j.get("pay"))
    dl = j.get("deadline")
    when = (f"~{int(dl[5:7])}/{int(dl[8:10])}" if (dl or "").count("-") == 2
            else ("상시모집" if j.get("deadlineNote") == "상시" else ""))
    # 30자 = '{본문} — 포디엄' 까지 합친 길이 기준. 넘치면 페이 → 마감 → 꼬리표 순으로 덜어낸다
    for bits in ([pay, when], [when], [pay], []):
        bits = [b for b in bits if b]
        t = head + (f" ({', '.join(bits)})" if bits else "")
        if len(t) + 5 <= 30:
            return t + " — 포디엄"
    t = head + (f" ({when})" if when else "")
    return t[:30]


def _jsonld(j):
    d = {"@context": "https://schema.org", "@type": "JobPosting",
         "title": j["title"],
         "datePosted": j.get("date") or j.get("firstSeen") or "",
         "hiringOrganization": {"@type": "Organization", "name": j.get("org") or ""},
         "jobLocation": {"@type": "Place",
                         "address": {"@type": "PostalAddress", "addressRegion": j.get("region") or "", "addressCountry": "KR"}},
         "description": build_description(j)}
    if j.get("deadline"):
        d["validThrough"] = j["deadline"]
    sal = _base_salary(j)
    if sal:
        d["baseSalary"] = sal
    emp = _EMP.get(j.get("kind") or "")
    if emp:
        d["employmentType"] = emp
    if j.get("addr"):                     # 주소를 아는 공고는 지역보다 정확하게 적는다
        d["jobLocation"]["address"]["streetAddress"] = j["addr"]
    return json.dumps(d, ensure_ascii=False)


def _dday_bucket(j, today):
    """마감까지 남은 기간을 구간으로. js/jobs.js ddayBucket과 같은 규칙 — 같이 고칠 것."""
    dl = j.get("deadline")
    if not dl:
        return "상시" if j.get("deadlineNote") == "상시" or j.get("obri") else "미정"
    try:
        d = (date.fromisoformat(dl) - today).days
    except ValueError:
        return "미정"
    if d < 0: return "마감"
    if d <= 3: return "D0-3"
    if d <= 7: return "D4-7"
    if d <= 30: return "D8-30"
    return "D30+"



STUB_MARK = "<!-- podium:redirect-stub -->"

_STUB_TMPL = """<!DOCTYPE html>
<html lang="ko">
<head>{mark}
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url={url}">
<meta name="robots" content="noindex, follow">
<link rel="canonical" href="{url}">
<title>{title} — 포디엄</title>
</head>
<body>
<p>이 공고는 <a href="{url}">{title}</a> 로 옮겨졌습니다.</p>
</body>
</html>
"""


def _stub_page(j, new_slug):
    """옛 주소에 남기는 리다이렉트 스텁 (GitHub Pages 는 서버 리다이렉트가 안 된다).

    meta refresh 0초로 즉시 옮기고, canonical 로 새 주소가 정본임을 알리고, noindex 로
    이 껍데기가 검색결과에 남지 않게 한다. 본문 링크 한 줄은 리프레시가 막힌 환경에서도
    길이 끊기지 않게 하려는 것이다 (작업 B, 2026-08-20).
    """
    return _STUB_TMPL.format(mark=STUB_MARK, url=f"{SITE}/p/{new_slug}.html",
                             title=esc(j["title"]))


def _detail_page(j, today):
    st, cls = _status(j, today)
    label, href = _apply(j)
    # 계측: 검색 유입이 처음 닿는 페이지가 여기다 — 원문 이동 클릭(data-ev)이
    # '포디엄을 보고 지원했다'의 유일한 증거가 된다 (js/analytics.js 위임 클릭)
    _dest = "mail" if (href or "").startswith("mailto:") else "tel" if (href or "").startswith("tel:") else "official"
    _ev = "contact_click" if _dest in ("mail", "tel") else "job_outbound"
    # 파라미터 전량을 data-evp(JSON)로 — 검색 유입이 처음 닿는 페이지라 여기서의 이동이
    # '포디엄 보고 지원했다'의 유일한 증거다. 목록(jobs.js jobParams)과 키 이름을 맞춘다.
    _ins = j.get("instDetails") or []
    _p = {k: v for k, v in {
        "job_id": "o" + j["id"], "job_tier": j.get("tier"), "job_kind": j.get("kind"),
        "job_inst": (_ins[0] if _ins else j.get("inst")), "job_insts": "|".join(_ins)[:90],
        "job_region": j.get("region"), "job_org": (j.get("org") or "")[:90],
        "job_source": j.get("source"), "job_dday": _dday_bucket(j, today),
        "job_cert": j.get("certReq"), "job_career": j.get("careerReq"),
        "job_degree": j.get("degreeReq"), "job_age": j.get("ageGroup"),
        "job_subject": (j.get("subject") or "")[:90],
        "job_obri": "예" if j.get("obri") else None,
        "job_new": "예" if _is_fresh(j, today) else None,
        "dest": _dest, "page_area": "detail",
    }.items() if v}
    act = (f'<a class="btn-primary" style="text-decoration:none" href="{esc(href)}" target="_blank" rel="noopener" '
           f'data-ev="{_ev}" data-evp="{esc(json.dumps(_p, ensure_ascii=False))}">{esc(label)}</a>'
           if href and label else "")   # 지원 경로가 없으면 버튼 자체를 만들지 않는다
    rows = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in _detail_rows(j))
    desc = esc(build_description(j))
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(build_title(j))}</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="{SITE}/p/{build_slug(j)}.html">
  <link rel="icon" type="image/png" sizes="32x32" href="../favicon-32.png">
  <link rel="apple-touch-icon" href="../apple-touch-icon.png">
  <meta name="theme-color" content="#7a2a38">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="포디엄">
  <meta property="og:title" content="{esc(build_title(j))}">
  <meta property="og:description" content="{desc}">
  <meta property="og:url" content="{SITE}/p/{build_slug(j)}.html">
  <meta property="og:image" content="{SITE}/og-image.png">
  <meta property="og:locale" content="ko_KR">
  <meta name="twitter:card" content="summary_large_image">
  <link href="https://fonts.googleapis.com/css2?family=Gowun+Batang:wght@400;700&family=Cormorant:wght@500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../css/style.css?v=16">
  <script src="../js/analytics.js?v=8" defer></script>
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



SITEMAP_SHARD = 1000     # 규격 상한은 50,000이지만 작게 끊어야 어디가 막혔는지 보인다


def _write_sitemaps(base, urls, lastmod):
    """URL이 많아지면 sitemap index + 조각으로 나눈다 (작업 F, 2026-08-20).

    한 파일에 다 넣어도 규격상 문제는 없지만, 조각으로 나눠야 서치콘솔이 조각별
    색인 현황을 따로 보여준다 — '어느 묶음이 안 먹히는가'를 볼 수 있다.
    조각이 하나뿐이면 예전처럼 sitemap.xml 한 장으로 둔다(불필요한 층 금지).
    """
    def _urlset(path, chunk):
        with open(path, "w", encoding="utf-8") as f:
            f.write(XML_HEAD + URLSET_OPEN)
            f.write("".join(URL_ROW.format(u=u, m=lastmod) for u in chunk))
            f.write(URLSET_CLOSE)

    shards = [urls[i:i + SITEMAP_SHARD] for i in range(0, len(urls), SITEMAP_SHARD)] or [[]]
    # 지난 회차의 조각이 남아 있으면 지운다 (공고가 줄면 조각 수도 줄어야 한다)
    for f_ in os.listdir(base):
        if re.fullmatch(r"sitemap-[0-9]+[.]xml", f_):
            os.remove(os.path.join(base, f_))
    if len(shards) == 1:
        _urlset(os.path.join(base, "sitemap.xml"), shards[0])
        return 1
    for n, chunk in enumerate(shards, 1):
        _urlset(os.path.join(base, "sitemap-{}.xml".format(n)), chunk)
    with open(os.path.join(base, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(XML_HEAD + INDEX_OPEN)
        f.write("".join(INDEX_ROW.format(s=SITE, n=n, m=lastmod)
                        for n in range(1, len(shards) + 1)))
        f.write(INDEX_CLOSE)
    return len(shards)


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

    # 1) 상세 페이지 — 사람이 읽을 수 있는 슬러그로 (작업 B, 2026-08-20)
    pdir = os.path.join(base, "p")
    os.makedirs(pdir, exist_ok=True)
    slugs = {j["id"]: build_slug(j) for j in items}
    keep = {sl + ".html" for sl in slugs.values()}
    # 아카이브 페이지(마감분)도 보존 대상이다 — 여기 없으면 매 실행 지워졌다 다시 생기며
    # 검색엔진에는 URL 이 사라졌다 살아나는 것으로 보인다 (작업 D, 2026-08-20).
    try:
        import archive_pages
        keep |= archive_pages.expected_files(base, {j["id"] for j in items})
    except Exception:
        pass
    # 옛 주소(/p/{id}.html)는 지우지 않는다 — 색인·북마크가 물려 있어 스텁으로 남긴다.
    # 스텁은 내용의 마커로 식별하고, 그 밖의 낡은 파일만 정리한다.
    for f_ in os.listdir(pdir):
        if not f_.endswith(".html") or f_ in keep:
            continue
        fp = os.path.join(pdir, f_)
        try:
            with open(fp, encoding="utf-8") as fh:
                if STUB_MARK in fh.read(400):
                    continue
        except OSError:
            pass
        os.remove(fp)
    for j in items:
        with open(os.path.join(pdir, slugs[j["id"]] + ".html"), "w", encoding="utf-8") as f:
            f.write(_detail_page(j, today))
        if j["id"] + ".html" not in keep:
            with open(os.path.join(pdir, j["id"] + ".html"), "w", encoding="utf-8") as f:
                f.write(_stub_page(j, slugs[j["id"]]))

    # 2) 목록 정적 삽입 — 카드는 정적 상세 페이지로 링크 (검색 봇의 착지 경로)
    _inject(os.path.join(base, "jobs.html"), "LIST",
            "".join(_card(j, today, f"p/{slugs[j['id']]}.html") for j in items))
    recent = sorted(items, key=lambda j: str(j.get("date") or j.get("firstSeen") or ""), reverse=True)[:8]
    _inject(os.path.join(base, "index.html"), "RECENT",
            "".join(_card(j, today, f"p/{slugs[j['id']]}.html") for j in recent))

    # 3) sitemap + robots
    lastmod = (doc.get("collectedAt") or today.isoformat())[:10]
    urls = [f"{SITE}/{p}" for p in ("", "jobs.html", "practice.html", "about.html", "sources.html", "privacy.html")]
    urls += [f"{SITE}/p/{slugs[j['id']]}.html" for j in items]
    # 마감 공고의 아카이브 페이지 (작업 D) — 품질 게이트를 통과한 것만 만들어 sitemap 에 싣는다.
    # 목록(jobs.html)·index 에는 넣지 않는다 — 화면에서는 진행 중인 공고만 보여준다.
    try:
        import archive_pages
        urls += archive_pages.generate(base, verbose=False)
    except Exception as e:
        print(f"[warn] 아카이브 페이지 생성 건너뜀: {type(e).__name__}: {e}")
    _write_sitemaps(base, urls, lastmod)
    with open(os.path.join(base, "robots.txt"), "w", encoding="utf-8") as f:
        # admin.html 은 열쇠로 막혀 있지만 검색결과에 뜰 이유가 없다 (sitemap 목록에도 없다).
        # 관리·계측·프로필 계열은 검색결과에 뜰 이유가 없다. 프로필은 v0 라 색인을 열지
        # 않는다 — 승인·삭제 프로세스가 안정된 뒤 v1 에서 연다 (지시서 v3 작업 H).
        f.write("User-agent: *" + chr(10) + "Allow: /" + chr(10)
                + chr(10).join("Disallow: /" + p_ for p_ in (
                    "admin.html", "analytics.html",
                    "profiles.html", "profile-submit.html", "profile-manage.html"))
                + chr(10) + f"Sitemap: {SITE}/sitemap.xml" + chr(10))
    return len(items)


if __name__ == "__main__":
    n = generate()
    print(f"정적 생성 완료: 공고 {n}건 (p/*.html, jobs/index 목록, sitemap.xml)")
