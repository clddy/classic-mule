# -*- coding: utf-8 -*-
"""하이브레인넷(대학 채용 포털) — 로그인 세션으로 음악학(AP02) 채용을 수집.

원칙: 링크는 hibrain이 아니라 각 대학 '원본사이트(원문)'로 건다.
로그인 세션은 hibrain_auth가 관리(사람이 1회 로그인). 세션이 없으면 조용히 []
반환(주간 폴링이라 크롤 전체를 막지 않는다).
"""
import re
from bs4 import BeautifulSoup
from common import make_item

# 음악학 = AP02 (예술체육 AP 하위). 국악학과는 상위 musician_relevant가 풍류로 분리 제외.
AP02_LIST = ("https://www.hibrain.net/recruitment/categories/MJR/"
             "categories/AP/categories/AP02/recruits")
DETAIL = "https://www.hibrain.net/recruitment/recruits/"
_UI_REGIONS = ("서울", "경기", "인천", "대전", "대구", "부산")


def _region(text):
    m = re.search(r"근무예정지\s*([가-힣]+)", text)
    if not m:
        return "기타"
    v = m.group(1)
    for r in _UI_REGIONS:
        if v.startswith(r):
            return r
    return "기타"   # 그 외 지역은 UI 필터에 없어 '기타'로


def _dates(text):
    """접수기간 '26.07.07 ~ 26.07.12' → (시작 date, 마감 deadline). 없으면 (None,None)."""
    m = re.search(r"접수기간[^\d]*(\d{2,4})[.\-](\d{1,2})[.\-](\d{1,2})"
                  r"\s*~\s*(\d{2,4})[.\-](\d{1,2})[.\-](\d{1,2})", text)
    if m:
        sy, sm, sd, ey, em, ed = m.groups()
        sy = ("20" + sy) if len(sy) == 2 else sy
        ey = ("20" + ey) if len(ey) == 2 else ey
        return (f"{sy}-{int(sm):02d}-{int(sd):02d}",
                f"{ey}-{int(em):02d}-{int(ed):02d}")
    # 마감만 있는 형태 '~ 26.07.12'
    m = re.search(r"접수기간[^~]*~\s*(\d{2,4})[.\-](\d{1,2})[.\-](\d{1,2})", text)
    if m:
        ey, em, ed = m.groups()
        ey = ("20" + ey) if len(ey) == 2 else ey
        return (None, f"{ey}-{int(em):02d}-{int(ed):02d}")
    return (None, None)


def _org(title, text):
    m = re.search(r"([가-힣A-Za-z]{2,15}?(?:대학교|대학원대학교|교육대학교|대학))", title)
    if m:
        return m.group(1)
    m = re.search(r"기관\s+(\S{2,20}?)\s+기관", text)
    return m.group(1) if m else title[:14]


def _origin(soup):
    """상세의 '원본사이트 바로가기'(대학 공식 공고) 링크. 없으면 홈페이지 바로가기."""
    home = None
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if "hibrain" in h or not h.startswith("http"):
            continue
        if re.search(r"facebook|instagram|twitter|higrad|apps\.apple|play\.google|kakao|youtube", h):
            continue
        t = a.get_text(" ", strip=True)
        if "원본사이트" in t:
            return h
        if "홈페이지" in t and not home:
            home = h
    return home


def parse_hibrain(s):
    try:
        import hibrain_auth
    except Exception:
        return []
    lst = hibrain_auth.fetch_many([AP02_LIST])
    if not lst:
        return []   # 세션 만료 — fetch_many가 경고 출력
    soup = BeautifulSoup(next(iter(lst.values())), "lxml")
    ids, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"/categories/AP02/recruits/(\d+)", a["href"])
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            ids.append((m.group(1), a.get_text(" ", strip=True)))
    if not ids:
        return []
    dets = hibrain_auth.fetch_many([DETAIL + i for i, _ in ids])
    items = []
    for i, list_title in ids:
        html = dets.get(DETAIL + i)
        if not html:
            continue
        ds = BeautifulSoup(html, "lxml")
        for tag in ds(["script", "style"]):
            tag.decompose()
        txt = ds.get_text(" ", strip=True)
        if "로그인후에 이용" in txt:      # 세션이 중간에 끊김 — 껍데기 저장 방지
            continue
        title = list_title if len(list_title) >= 8 else txt[:60]
        start, deadline = _dates(txt)
        it = make_item(_org(title, txt), _region(txt), "hibrain.net",
                       title, DETAIL + i, date=start, deadline=deadline)
        origin = _origin(ds)
        if origin:
            it["officialUrl"] = origin
        items.append(it)
    return items
