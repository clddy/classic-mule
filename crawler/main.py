# 메인: 소스 레지스트리 기반 수집 → dedup(canonical) → 마감일 보강 → 커버리지 리포트
import json, os, re, sys, time, traceback
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (new_session, get, relevant, extract_deadline, deadline_from_title,
                    musician_relevant, parse_recruit_table, summarize_recruit, find_position,
                    classify_insts, find_subject, find_music_subjects, find_music_courses,
                    classify_kind, classify_tier, is_obri, cert_required, degree_req, career_req, age_group)
from sources import SOURCES
from institutions import INSTITUTIONS
import attach

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # podium/
OUT = os.path.join(BASE, "data", "official.json")
LOG = os.path.join(BASE, "data", "crawl.log")
COVERAGE = os.path.join(BASE, "data", "coverage_report.json")

MAX_DETAIL_PER_SOURCE = 20
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
    insts = it.get("instDetails") or []
    # 악기가 특정되면 마감일 유무와 무관하게 org|악기로 병합
    # (집계 포털판이 마감을 못 얻어도 원천 공고와 합쳐지도록 — KBS artmore vs kbssymphony)
    if insts:
        return f"{norm_org(it['org'])}|{'/'.join(sorted(insts))}"
    if it.get("deadline"):
        return f"{norm_org(it['org'])}|{it['deadline']}"
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
INST_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "institutions.csv")
# 대조용 이름 정규화: 괄호·법인격·말미 기관유형어 제거 → 지역+식별 핵심만 남겨 오탐 줄임
_COV_TAIL = re.compile(r"(교향악단|필하모닉|합창단|오케스트라|예술단|관현악단|국악관현악단|무용단|극단"
                       r"|문화재단|문화관광재단|문화예술재단|문화의전당|예술의전당|문화예술회관|문화회관|아트센터|아트홀"
                       r"|콘서트홀|문화원|음악당|대학교|교육대학교|대학|교회|교구)$")
def _cov_core(name):
    core = re.sub(r"\([^)]*\)|재단법인|\(재\)|사단법인|\s+", "", name)
    prev = None
    while core != prev:            # 말미 유형어 반복 제거 (예: '○○시립교향악단' → '○○시립')
        prev = core
        core = _COV_TAIL.sub("", core)
    return core

def _master_coverage(haystack):
    """institutions.csv(실재 확정) 전체 대비 커버리지 — 카테고리별 집계 + 공백 목록."""
    import csv as _csv
    if not os.path.exists(INST_CSV):
        return None
    by_cat, gaps, total, covered = {}, [], 0, 0
    with open(INST_CSV, encoding="utf-8") as f:
        for row in _csv.reader(f):
            if not row or row[0].lstrip().startswith("#") or row[0] == "기관명" or len(row) < 8:
                continue
            name, cat, region, real = row[0], row[1], row[3], row[7].strip()
            if real != "확정":
                continue
            total += 1
            by_cat.setdefault(cat, {"total": 0, "covered": 0})
            by_cat[cat]["total"] += 1
            core = _cov_core(name)
            if len(core) >= 3 and core in haystack:
                covered += 1
                by_cat[cat]["covered"] += 1
            else:
                gaps.append({"name": name, "cat": cat, "region": region})
    return {"total": total, "covered": covered, "gapCount": len(gaps),
            "byCategory": by_cat, "gaps": gaps}

def coverage_report(items, today):
    haystack = " ".join(f"{i['org']} {i['title']}" for i in items)
    covered, gaps = [], []
    for inst in INSTITUTIONS:
        if re.search(inst["match"], haystack):
            covered.append(inst["name"])
        else:
            gaps.append({"name": inst["name"], "type": inst["type"], "region": inst["region"]})
    master = _master_coverage(haystack)
    report = {"date": today.isoformat(), "total": len(INSTITUTIONS),
              "covered": len(covered), "gapCount": len(gaps), "gaps": gaps,
              "master": master}
    with open(COVERAGE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    log(f"커버리지(시드 {len(INSTITUTIONS)}): {len(covered)}곳 확인, 공백 {len(gaps)}곳")
    if master:
        log(f"커버리지(마스터 institutions.csv {master['total']}): "
            f"{master['covered']}곳 확인, 공백 {master['gapCount']}곳 → coverage_report.json")
    return report

# ---------- 마감일 보강 ----------
ATTACH_LINK = re.compile(r"download|fileDown|file\.do|atchFile|attach|dwld|fileId|process\.file", re.I)

# 새올·JSP 게시판: javascript:fnDownload('/board/file/…','…') 형태의 다운로드 함수에서
# 파일 경로 인자를 뽑아낸다 (첫 인자가 실제 다운로드 경로).
_JS_FILEARG = re.compile(r"""['"](/[^'"]*?(?:/file/|download|filedown|atchfile|/atch|/dext5)[^'"]*)['"]""", re.I)

# 경로에 download 흔적이 없는 JSP(원광대 downFile 등): 페이지 스크립트의 함수 정의에서
# location.href="…jsp?path="+path+"&ofilename="+encodeURIComponent(f) 템플릿을 복원해 URL 조립
_JS_CALL = re.compile(r"^javascript:\s*(\w+)\s*\((.*)\)\s*;?\s*$", re.I | re.S)
_JS_STRARG = re.compile(r"""['"]([^'"]*)['"]""")

def _js_template_url(soup, base_url, href, text=""):
    from urllib.parse import urljoin, quote
    m = _JS_CALL.match(href.strip())
    if not m:
        return None
    fname, args = m.group(1), _JS_STRARG.findall(m.group(2))
    if not args:
        return None
    # 다운로드 함수로 볼 근거: 인자/앵커텍스트에 파일 확장자, 또는 함수명이 down/file/atch/fms
    arg_ext = any(re.search(r"\.(pdf|hwpx?|xlsx?|docx?|zip)$", a, re.I) for a in args)
    text_ext = bool(re.search(r"\.(pdf|hwpx?|xlsx?|docx?|zip)\b", text or "", re.I))
    fname_dl = bool(re.search(r"down|file|atch|attach|fms|fdown", fname, re.I))
    if not (arg_ext or text_ext or fname_dl):
        return None
    script = " ".join(sc.get_text() for sc in soup.find_all("script"))
    fm = re.search(r"function\s+" + re.escape(fname) + r"\s*\(([^)]*)\)\s*\{(.*?)\}", script, re.S)
    if not fm:
        return None
    params = [p.strip() for p in fm.group(1).split(",") if p.strip()]
    body = fm.group(2)
    # location.href="…"  또는  window.open("…")  또는  form.action="…"
    lm = (re.search(r"location(?:\.href)?\s*=\s*([^;\n]+)", body)
          or re.search(r"window\.open\s*\(\s*([^;,\n]+)", body)
          or re.search(r"\.action\s*=\s*([^;\n]+)", body))
    if not lm:
        return None
    argmap = dict(zip(params, args))
    url = ""
    for s1, s2, enc, ident in re.findall(
            r"\"([^\"]*)\"|'([^']*)'|encodeURIComponent\s*\(\s*(\w+)\s*\)|\b(\w+)\b", lm.group(1)):
        if s1 or s2:
            url += (s1 or s2)
        elif enc:
            url += quote(argmap.get(enc, ""))
        elif ident in argmap:
            url += quote(argmap[ident], safe="/")
    ok = "?" in url or re.search(r"\.(pdf|hwpx?|xlsx?|docx?|zip)", url, re.I)
    return urljoin(base_url, url) if ok else None

def find_attachments(soup, base_url):
    from urllib.parse import urljoin
    cands, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        if href.startswith(("#", "mailto")):
            continue
        full = None
        if href.startswith("javascript"):
            m = _JS_FILEARG.search(href)
            if m:
                full = urljoin(base_url, re.sub(r";jsessionid=[^?&'\"]*", "", m.group(1), flags=re.I))
            else:
                full = _js_template_url(soup, base_url, href, text)  # downFile/eGov 템플릿형
                if not full:
                    continue
        elif (re.search(r"\.(pdf|hwpx?|zip)(\?|$)", href, re.I)
                or re.search(r"\.(pdf|hwpx?|zip)\b", text, re.I)
                or ATTACH_LINK.search(href)):
            full = urljoin(base_url, href)
        if full and full not in seen:
            seen.add(full)
            cands.append((full, text))
    # WordPress 게시판(서경대 등): href="#" 이고 실제 파일경로가 data-file-key 속성에 있음
    if not cands and soup.find(src=re.compile(r"wp-content")):
        for el in soup.find_all(attrs={"data-file-key": True}):
            key = (el.get("data-file-key") or "").lstrip("/")
            if re.search(r"\.(pdf|hwpx?|xlsx?|docx?|zip)$", key, re.I):
                full = urljoin(base_url, "/wp-content/uploads/" + key)
                if full not in seen:
                    seen.add(full)
                    cands.append((full, el.get_text(" ", strip=True)))
    return cands[:4]

EXT_VER = 22         # 마감일 추출기 버전 — 올리면 이전 수집의 마감일·전공 승계가 무효화됨
                     #  v18: 대학 강사 초빙 원문 첨부(HWP/XLSX)에서 음악 전공 추출 + 비음악 제외
                     #  v19: 음악 학과/전공 정밀 추출(행사명·전화번호 오염 제거) — 재추출 강제
                     #  v20: 담당 교과목(courses) 추출·패널 노출 — 재추출 강제
                     #  v21: 담당 교과목 정제 강화(자격문구·코드·조각 제거) — 재추출 강제
                     #  v22: 실용음악 전공 제외(→비음악), 등급 4분류 개편 — 재추출 강제
                     # v17: 집계포털 상시 기본값 제거 + 원문(officialUrl) 죽은링크 감지·실마감 추출
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

def _clip(s, n=60):
    return re.sub(r"\s+", " ", s or "").strip(" .:·|,-") [:n] or None

# 본문 라벨 목록 — 필드 값을 다음 라벨/문장부호 직전에서 잘라내기 위한 경계
_LABELS = (r"지원자격|응시자격|자격요건|참가자격|모집대상|지원대상|모집인원|채용인원|선발인원|모집정원"
           r"|접수기간|접수일정|접수방법|접수처|리허설|연습일정|연습|공연일시|공연일|연주일시|연주일|공연날짜"
           r"|장소|일시|기간|페이|출연료|사례비|보수|급여|수당|강사료|연주비|프로그램|연주곡목|곡목|레퍼토리"
           r"|문의|담당|기타|비고|제출|전형|합격|발표|우대|근무|공연|자격|대상|인원|정원")
_LBL_RE = re.compile(_LABELS)

def _seg_after(text, label_pat, n=60):
    """라벨 뒤 값을 다음 라벨/문장부호 전까지 잘라 반환 (공백평탄 본문 대응)"""
    m = re.search(r"(?:" + label_pat + r")\s*[:：]?\s*", text)
    if not m:
        return None
    rest = text[m.end(): m.end() + 130]
    nxt = _LBL_RE.search(rest)
    seg = rest[:nxt.start()] if nxt else rest
    seg = re.split(r"[.\n]|\s{2,}", seg)[0]
    return _clip(seg, n)

_QUAL_OK = re.compile(r"졸업|학위|학력|경력|이상|전공|재학|대학|연령|만 ?\d|세 |세$|자 |전공자|무관")

def _find_qualification(text):
    q = _seg_after(text, r"지원 ?자격|응시 ?자격|자격 ?요건|참가 ?자격|모집 ?대상|지원 ?대상") \
        or _seg_after(text, r"자격(?!증)")
    # 실제 자격 표현이 담긴 경우만 채택 (○실기·전형 조기절단 파편 배제)
    return q if q and len(q) >= 5 and _QUAL_OK.search(q) else None

def _find_personnel_body(text):
    """모집인원(표 없이 본문에만 있을 때) — 라벨 우선, 없으면 '○○ N명 모집'"""
    seg = _seg_after(text, r"모집 ?인원|채용 ?인원|선발 ?인원|모집 ?정원|T\.?O\.?", 24)
    if seg and re.search(r"\d", seg):
        return seg
    m = re.search(r"([가-힣A-Za-z·/]{2,16})\s*(?:각\s*)?(\d+)\s*명\s*(?:모집|선발|채용|충원)", text)
    return f"{m.group(1).strip()} {m.group(2)}명" if m else None

_PAY_NOISE = re.compile(r"보내기|복사|인쇄|관심기관|스크랩|스북|공유|목록|URL|바로가기|로그인|회원")
def _find_pay(text):
    m = re.search(r"(회당|1회당|건당|시간당|일당|공연당|월)\s*([\d,]+\s*만?\s*원)", text)
    if m:
        return (m.group(1) + " " + m.group(2)).replace(" ", "")
    v = _seg_after(text, r"연주비|출연료|사례비|페이|보수|급여|수당|강사료", 24)
    # 키워드 뒤 텍스트가 공유버튼 등 UI 잡음이거나 금액 표현이 없으면 버림
    if v and not _PAY_NOISE.search(v) and re.search(r"원|만|협의|규정|시급|일당|사례|\d", v):
        return v
    return None

def _find_program(text):
    return _seg_after(text, r"프로그램|연주 ?곡목?|곡\s*목|레퍼토리|연주곡", 80)

def _find_rehearsal(text):
    v = _seg_after(text, r"리허설|연습 ?일정|연습", 50)
    return v if v and re.search(r"\d", v) else None      # 날짜 숫자 없으면 버림

def _find_concert(text):
    v = _seg_after(text, r"공연 ?일시|연주 ?일시|공연일|연주일|공연 ?날짜|공연", 50)
    return v if v and re.search(r"\d", v) else None      # '장 [' 등 파편 배제

# 본문 요약: 모집·자격·일정 관련 핵심 줄만 골라 세부창에 노출
_EXCERPT_KW = re.compile(
    r"모집|채용|선발|자격|대상|리허설|연습|공연|연주|일시|장소|기간|인원|오디션"
    r"|전형|접수|급여|보수|페이|출연|곡목|프로그램|\d명")
# 집계·게시판 페이지의 내비게이션·관련목록·결과공고 잡음 배제
_EXCERPT_SKIP = re.compile(
    r"메인 ?페이지|바로가기|로그인|회원가입|비슷한|관련\s*(모집|공고|정보)|목록|이전\s*글|다음\s*글"
    r"|리스트|검색|더보기|메뉴|카테고리|사이트맵|저작권|Copyright|배너|공유|인쇄|스크랩|조회수"
    r"|첨부 ?파일|>|메일|주소복사|프린트|top|TOP|서포터즈|소식|공지사항|보도자료|서식"
    r"|최종 ?합격|합격자|불합격|합격 ?발표|채용 ?결과|선정 ?결과|낙찰|입찰 ?결과|계약 ?체결|티켓|추가 ?오픈"
    r"|채용 ?비리|비리 ?신고|신고 ?센터|공공기관 채용|청탁|개인정보|저작권|이용약관|고객센터"
    r"|용역|평가위원|단장 ?공개"
    r"|\[채용공고\]|\[공지\]|\[입찰\]|\[결과\]|\[알림\]")

def _body_excerpt_text(text):
    keep = []
    for raw in (text or "").split("\n"):
        ln = re.sub(r"\s+", " ", raw).strip(" ·-•▷▶◦□■●○△*|:")
        if not (8 <= len(ln) <= 90) or ln in keep:
            continue
        if ln.count("|") >= 2:      # 브레드크럼(메뉴 경로) 배제
            continue
        if re.search(r"\.(pdf|hwpx?|zip|docx?|xlsx?)(\b|$)", ln, re.I):  # 첨부 파일명 줄 배제
            continue
        if _EXCERPT_SKIP.search(ln) or not _EXCERPT_KW.search(ln):
            continue
        # 라벨(콜론)·날짜·인원·금액 등 '실제 공고 내용' 신호가 있는 줄만
        if not re.search(r"[:：]|20\d\d|\d\s*명|\d\s*월|원\b|졸업|자격|모집|채용|리허설|오디션", ln):
            continue
        # 이미 담은 줄과 앞부분이 겹치면(제목 반복 등) 건너뛰기
        if any(k[:16] == ln[:16] for k in keep):
            continue
        keep.append(ln)
        if len(keep) >= 4:
            break
    return " · ".join(keep)[:240] if keep else None

def _body_excerpt(soup):
    return _body_excerpt_text(soup.get_text("\n", strip=True))

def _apply_details_from_text(text, item, want_excerpt=True):
    """평문 본문(페이지/첨부/OCR)에서 자격·인원·객원필드·요약을 채운다 (없는 것만)"""
    if not text:
        return
    if not item.get("qualification"):
        q = _find_qualification(text)
        if q:
            item["qualification"] = q
    if not item.get("personnel") and not item.get("recruitSummary"):
        p = _find_personnel_body(text)
        if p:
            item["personnel"] = p
    if item.get("kind") == "객원·대체":
        for fld, fn in (("rehearsal", _find_rehearsal), ("concertDate", _find_concert),
                        ("pay", _find_pay), ("program", _find_program)):
            if not item.get(fld):
                v = fn(text)
                if v:
                    item[fld] = v
    if want_excerpt and not item.get("bodyExcerpt"):
        ex = _body_excerpt_text(text)
        if ex:
            item["bodyExcerpt"] = ex

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
    # 대학 교수 초빙: 제목에 전공이 없으면 본문(공고표·안내)에서 보강
    if item.get("kind") == "교수" and not item.get("subject"):
        subj = find_subject(page_text[:2000])
        if subj:
            item["subject"] = subj
    if not item.get("contract") and item.get("kind") == "단원":
        c = _find_contract(page_text)
        if c:
            item["contract"] = c
    # 자격·모집인원·객원필드 (평문 본문에서, 없는 것만) — 요약은 아래서 별도 처리
    _apply_details_from_text(page_text, item, want_excerpt=False)
    # 본문 요약: 줄 구조가 살아있는 soup 기준(품질 필터가 집계·게시판 잡음 제거).
    # 얇은 페이지에서 못 뽑으면 이후 첨부 단계에서 채워진다.
    if not item.get("bodyExcerpt"):
        ex = _body_excerpt(soup)
        if ex:
            item["bodyExcerpt"] = ex
    # 제목에 악기가 없으면 본문에서 악기 탐지 (오케스트라 강사 등 파트별 모집)
    if not item.get("instDetails"):
        grp, dets = classify_insts(page_text[:3000])
        if dets:
            item["instDetails"] = dets
            if item.get("inst") in (None, "", "전체", "기타"):
                item["inst"] = grp

def _body_from_attachments(s, soup, r, item):
    """첨부 공고문(HWP/PDF)에서 본문 상세(자격·인원·요약) 보강 — 마감일 로직과 무관.
    본문이 첨부에만 있는 집계·게시판(cwcf·bscc 등) 대응."""
    for furl, fname in find_attachments(soup, r.url):
        if item.get("bodyExcerpt"):
            break
        try:
            fr = s.get(furl, timeout=30, verify=False, headers={"Referer": item["url"]})
            if fr.status_code != 200 or not (200 < len(fr.content) < 20_000_000):
                continue
            cd = fr.headers.get("Content-Disposition", "")
            m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
            name = m.group(1) if m else (fname or furl)
            _apply_details_from_text(attach.extract_any(name, fr.content), item)
        except Exception:
            continue

_CJOB_REGIONS = {"서울", "경기", "인천", "대전", "대구", "부산", "광주", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"}

def _cjob_detail(text, item):
    """기독정보넷 상세: 단체명·모시는분·지역·등록일·남은기간·사례비·본문 표 파싱"""
    t = re.sub(r"\s+", " ", text)
    def grab(p):
        m = re.search(p, t)
        if not m:
            return None
        g = next((x for x in m.groups() if x), "")
        return re.sub(r"\s+", " ", g).strip(" :·-")
    org = grab(r"단체\(회사\)이름\s*(.+?)\s*-\s*(?:주소|연락처|담당자|담당|모시는분)")
    if org and 2 <= len(org) <= 30 and org != "미정":
        item["org"] = org
    role = grab(r"모시는분\s*(.+?)\s*-\s*(?:지역|등록일|남은기간)")
    if role and len(role) <= 20:
        item["personnel"] = role
    reg = grab(r"지역\s*(.+?)\s*-\s*(?:등록일|남은기간)")
    if reg in _CJOB_REGIONS:
        item["region"] = reg if reg in ("서울", "경기", "인천", "대전", "대구", "부산") else "기타"
    d = grab(r"등록일\s*(20\d\d-\d\d-\d\d)")
    if d:
        item["date"] = d
    rem = grab(r"남은기간\s*(20\d\d-\d\d-\d\d|0000-00-00)")
    if re.search(r"상시 ?모집|상시 ?채용|충원 ?시 ?마감", t):
        item["deadlineNote"] = "상시"
    elif not rem or rem == "0000-00-00":
        # 남은기간 0000-00-00은 사이트에서 '마감'으로 렌더 → 만료 처리(과거 sentinel로 제거)
        item["deadline"] = "2000-01-01"
        item["deadlineFrom"] = "cjob-마감(0000)"
    else:
        item["deadline"] = rem
        item["deadlineFrom"] = "cjob-남은기간"
    pay = grab(r"사례비\s*:?\s*([^:]{1,24}?)\s*(?:주소|연락처|제출|사진|상세|근무|문의|매주|주일|$)")
    if pay and len(pay) >= 2 and "이곳" not in pay:
        item["pay"] = pay
    denom = grab(r"교회명\(교단\)\s*:?\s*([^:]{1,14}?)\s*(?:제출|주소|사례비|담당|연락처|사진|상세|$)")
    if denom and 1 <= len(denom) <= 14:
        item["denomination"] = denom
    docs = grab(r"제출 ?서류\s*:?\s*([^:]{1,24}?)\s*(?:사례비|주소|연락처|담당|사진|상세|근무|$)")
    if docs and 2 <= len(docs) <= 24:
        item["documents"] = docs
    # 상세 설명: 사례비/제출서류 뒤의 자유서술
    m = re.search(r"(?:사례비\s*:[^:]*|제출 ?서류\s*:[^:]*)\s+([가-힣][^:]{15,180})", t)
    if m:
        body = re.sub(r"\s*(?:주소|연락처|사례비|담당)\s*:.*$", "", m.group(1)).strip()
        if len(body) >= 12:
            item["bodyExcerpt"] = body[:180]

# 집계 포털(아트인포·아트모아)에 개인·교회·학원이 직접 올린 글은 '원문'이 따로 없다.
# 이 경우 사용자를 포털로 보내지 않고, 지원 연락처를 본문에서 뽑아 포디엄에서 바로 노출한다.
AGGREGATORS = ("artinfokorea.com", "artmore.kr", "job.cleaneye.go.kr")

# hibrain 제목에 이미 음악 전공/악기 신호가 있으면 첨부 검증 없이 신뢰 (성악과·합창지휘·교향악단 등)
_MUSIC_TITLE = re.compile(
    r"음악|성악|기악|피아노|바이올린|비올라|첼로|더블베이스|콘트라베이스|플루트|오보에|클라리넷|바순"
    r"|호른|트럼펫|트롬본|튜바|색소폰|타악|팀파니|하프|오르간|관현악|작곡|국악|실용음악|합창|지휘"
    r"|반주|교회음악|뮤지컬|음악치료|성악과|교향악|필하모닉|오케스트라")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"01[016-9][-.\s]?\d{3,4}[-.\s]?\d{4}")

def _extract_contact(page_text, item):
    """집계 포털 직접게시글에서 지원 이메일/전화 추출 (원문 URL이 없을 때만 의미)."""
    em = _EMAIL_RE.search(page_text)
    if em:
        item["applyEmail"] = em.group(0)
    ph = _PHONE_RE.search(page_text)
    if ph:
        # 표기 정규화 (010-0000-0000)
        digits = re.sub(r"\D", "", ph.group(0))
        if len(digits) == 11:
            item["applyPhone"] = f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
        else:
            item["applyPhone"] = ph.group(0)

# 원문 페이지가 삭제·이전된 경우의 오류 문구 (소프트 404 감지) — 링크가 죽은 곳으로 가지 않도록.
# ⚠️ raw HTML 전체에서 찾으면 Next.js 등 SPA가 번들에 심어둔 404 컴포넌트 문자열에 오탐한다.
# 그래서 (1) '삭제글 alert 후 뒤로가기' 패턴과 (2) 스크립트를 걷어낸 '실제 보이는 텍스트'만 본다.
_NOTFOUND_TXT = ("페이지를 찾을 수 없", "요청하신 페이지", "존재하지 않는", "삭제된 게시",
                 "삭제되었습니다", "권한이 없", "게시물이 없", "잘못된 접근")
_DEAD_ALERT_RE = re.compile(
    r"""alert\(\s*["'][^"']*(?:존재하지\s*않|찾을\s*수\s*없|삭제된\s*게시|삭제되었|권한이\s*없|잘못된\s*접근)"""
    r"""[^"']*["']\s*\)\s*;?\s*(?:history\.back|location\.(?:href|replace))""",
    re.S)

def _is_dead_origin(r):
    """원문 페이지가 삭제/없는 글인지 판정 (살아있는 SPA 홈을 오탐하지 않도록 보수적으로)."""
    if r.status_code == 404:
        return True
    # 게시물 삭제 시 gov CMS가 흔히 쓰는 'alert(없는 글) → history.back()' 패턴
    if _DEAD_ALERT_RE.search(r.text):
        return True
    # 스크립트를 제거한 실제 본문이 짧고 not-found 문구뿐이면 서버렌더 404
    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    vis = soup.get_text(" ", strip=True)
    if len(vis) < 600 and any(m in vis for m in _NOTFOUND_TXT):
        return True
    return False

# ---------- 목록 origin 딥링크화 ----------
# 집계(hibrain 등)가 해석한 원문이 '공지사항 목록'인 경우가 있다(예: 대학 채용 게시판 목록).
# 목표는 목록이 아니라 해당 공고 상세까지 도달하는 것 — 목록을 열어 제목 토큰이 겹치는
# 상세 앵커를 찾아 officialUrl을 교체한다.
_LIST_URL = re.compile(r"selectNttList|List\.do|list\.do|/list\b|mode=list|BbsList", re.I)
_DETAIL_HREF = re.compile(r"nttSn=\d|selectNttInfo|mode=view|/view|View\.do|articleNo=\d|wr_id=\d"
                          r"|boardSeq=\d|seq=\d|[?&]idx=\d|dataSid=\d|[?&]no=\d|bbsSn=\d|artclView", re.I)
_TOKEN_SPLIT = re.compile(r"[\s\[\]()〈〉<>.,·/|~\-_!?'\"“”]+")
_STOP_TOKENS = {"모집", "채용", "공고", "공고문", "안내", "초빙", "임용", "재공고", "및", "제", "차",
                "2025", "2026", "2027", "학년도", "년도", "상반기", "하반기", "학기"}

def _title_tokens(t):
    return {w for w in _TOKEN_SPLIT.split(t or "") if len(w) >= 2 and w not in _STOP_TOKENS}

def _deepen_list_origin(s, item):
    """officialUrl이 목록 페이지면, 그 안에서 제목이 가장 잘 맞는 상세 앵커로 교체."""
    from urllib.parse import urljoin
    url = item.get("officialUrl")
    if not url or not _LIST_URL.search(url) or _DETAIL_HREF.search(url):
        return
    try:
        r = get(s, url)
        if r.status_code != 200:
            return
    except Exception:
        return
    want = _title_tokens(item["title"])
    kind_kw = re.compile(r"강사|교원|교수|채용|모집|임용|단원|초빙")
    best, best_score = None, 0
    soup = BeautifulSoup(r.text, "lxml")
    # na/ntt CMS(대학·교육청 공통): 행이 javascript 앵커(.nttInfoBtn[data-id]) →
    # selectNttInfo.do?nttSn= 상세 URL을 직접 조립
    m_na = re.search(r"^(.*)/na/ntt/selectNttList\.do", url)
    if m_na:
        from urllib.parse import parse_qs, urlparse as _up
        q = parse_qs(_up(url).query)
        mi, bbs = (q.get("mi") or [""])[0], (q.get("bbsId") or [""])[0]
        for a in soup.select(".nttInfoBtn[data-id]"):
            t = a.get_text(" ", strip=True)
            if len(t) < 6 or not kind_kw.search(t):
                continue
            score = len(want & _title_tokens(t))
            if score > best_score:
                best = f"{m_na.group(1)}/na/ntt/selectNttInfo.do?nttSn={a['data-id']}&mi={mi}&bbsId={bbs}"
                best_score = score
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("javascript", "#", "mailto")) or not _DETAIL_HREF.search(href):
            continue
        t = a.get_text(" ", strip=True)
        if len(t) < 6 or not kind_kw.search(t):
            continue
        score = len(want & _title_tokens(t))
        if score > best_score:
            best, best_score = urljoin(url, href), score
    # 토큰 2개 이상 겹칠 때만 확신하고 교체 (엉뚱한 공고로 보내지 않도록 보수적)
    if best and best_score >= 2:
        item["officialUrl"] = best
        item["originDeepened"] = True

def _origin_check(s, item, ry):
    """기관 원문(officialUrl)을 실제로 열어본다.
    죽은 페이지면 만료 처리(링크가 404로 가는 것 방지), 살아있으면 진짜 마감일을 추출."""
    url = item.get("officialUrl")
    if not url:
        return
    try:
        r = get(s, url)
    except Exception:
        return
    if _is_dead_origin(r):
        # 원문이 사라짐 → 사실상 만료. 과거 sentinel로 표시해 이후 만료 필터가 제거
        item["deadline"] = "2000-01-01"
        item["deadlineFrom"] = "origin-dead"
        return
    if not item.get("deadline"):
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "header", "footer", "nav"]):
            tag.decompose()
        dl = extract_deadline(soup.get_text(" ", strip=True), ref_year=ry)
        if dl:
            item["deadline"] = dl
            item["deadlineFrom"] = "origin"

def _music_from_origin(s, item):
    """대학 '전체 강사 초빙'(제목만 '○○대 강사 모집'이고 전공 미상): 원문(officialUrl)의
    첨부 '채용 교과목표'(HWP/XLSX)를 열어 음악 관련 전공을 추출한다.
      · 음악 전공 발견 → item['subject'] 채움 (사용자가 '어떤 전공인지' 바로 앎)
      · 첨부를 충분히 읽었는데 음악이 전혀 없음 → item['nonMusic']=True (최종 필터에서 제외)
      · 원문/첨부를 못 열거나 빈약 → item['musicUnverified']=True (자동확인 불가 → 메일 문의 후보)
    """
    if item.get("subject"):
        return
    url = item.get("officialUrl")
    if not url:
        item["musicUnverified"] = True
        return
    try:
        r = get(s, url)
        if r.status_code != 200:
            item["musicUnverified"] = True
            return
    except Exception:
        item["musicUnverified"] = True
        return
    # 일부 대형 페이지(서울예술대 2.3MB 등)는 lxml이 다운로드 앵커를 누락 → html.parser 폴백
    atts = []
    for parser in ("lxml", "html.parser"):
        atts = find_attachments(BeautifulSoup(r.text, parser), r.url)
        if atts:
            break
    texts, seen = [], set()
    for furl, fname in atts:
        if furl in seen:
            continue
        seen.add(furl)
        try:
            fr = s.get(furl, timeout=40, verify=False, headers={"Referer": url})
            if fr.status_code != 200 or not (200 < len(fr.content) < 40_000_000):
                continue
            cd = fr.headers.get("Content-Disposition", "")
            m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
            name = m.group(1) if m else (fname or furl)
            texts.append(attach.extract_any(name, fr.content))
        except Exception:
            continue
        if len(texts) >= 6:
            break
    blob = "\n".join(texts)
    subs = find_music_subjects(blob)
    if subs:
        item["subject"] = " · ".join(subs)
        item["subjectFrom"] = "attach"
        courses = find_music_courses(blob)   # 담당 교과목(무엇을 가르치는지) 패널 노출용
        if courses:
            item["courses"] = courses
    elif len(re.sub(r"\s", "", blob)) > 800:   # 교과목표를 충분히 읽었는데 음악 0 → 비음악
        item["nonMusic"] = True
    else:
        item["musicUnverified"] = True


def enrich_deadline(s, item, allow_render=True, details_only=False):
    global _renders_used
    # 하이브레인 항목은 로그인 세션으로 이미 상세 파싱됨 — 여기서 item["url"](hibrain)을
    # 익명으로 다시 열면 '로그인후에 이용' 껍데기를 긁게 되므로 건너뛴다.
    # 단, 원문(officialUrl)이 '공지 목록'이면 상세 공고까지 파고들어 교체(창원대 케이스).
    if item.get("source") == "hibrain.net":
        _deepen_list_origin(s, item)
        return
    ry = _ref_year(item)
    try:
        r = get(s, item["url"])
        if r.status_code != 200:
            return
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "header", "footer", "nav"]):
            tag.decompose()
        page_text = soup.get_text(" ", strip=True)
        # 집계 포털 항목: 원문이 있으면 원문을 검증(죽은 링크 차단 + 진짜 마감일),
        # 원문이 없는 직접게시글이면 지원 연락처를 본문에서 확보한다.
        if item.get("source") in AGGREGATORS:
            if item.get("officialUrl"):
                _deepen_list_origin(s, item)   # 목록 origin이면 상세 공고까지 파고들기
                _origin_check(s, item, ry)
                if item.get("deadline") == "2000-01-01":
                    return  # 원문이 죽음 → 만료 처리하고 종료
            else:
                _extract_contact(page_text, item)
        # 기독정보넷은 전용 표 구조 — 별도 파서로 처리
        if item.get("source") == "cjob.co.kr":
            _cjob_detail(page_text, item)
            return
        # 채용부문/직책/인원 표 등 본문 상세 (마감 유무와 무관하게 항상)
        _extract_body_details(soup, page_text, item, ry)
        # 명시적 채용/모집 상태가 '마감/종료'면 만료 처리 (엉뚱한 날짜 추출 방지)
        # — gne 등은 접수기간이 첨부에만 있고 페이지엔 '채용상태 마감'만 명시됨
        if re.search(r"(?:채용|모집|진행)\s*상태\s*[:：]?\s*(?:마감|종료)|마감\s*되었습니다", page_text):
            item["deadline"] = "2000-01-01"
            item["deadlineFrom"] = "상태:마감"
            return
        # 마감일은 이미 확정 — 본문 요약만 필요한 경우
        if details_only:
            # 본문이 얇은 집계·게시판이면 첨부 공고문에서 요약 보강 (cwcf·bscc 등)
            if not item.get("bodyExcerpt") and len(page_text) < 800:
                _body_from_attachments(s, soup, r, item)
            return
        # 게시일이 없으면 상세의 등록일/작성일에서 보충
        if not item.get("date"):
            m = re.search(r"(?:등록일|작성일|게시일|등록 ?일자)\s*[:：]?\s*(20\d{2})[.\-](\d{1,2})[.\-](\d{1,2})", page_text)
            if m:
                item["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
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
                atext = attach.extract_any(name, fr.content)
                _apply_details_from_text(atext, item)  # 첨부 공고문에서 자격·인원·요약
                dl = extract_deadline(atext, ref_year=ry)
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
                    otext = attach.ocr_image(data)
                    _apply_details_from_text(otext, item)  # 이미지 공고문에서 자격·인원·요약
                    dl = extract_deadline(otext, ref_year=ry)
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
        # (집계 포털 무마감 공고를 '상시'로 눕히던 기본값 제거 — 상시는 본문에
        #  '상시모집' 등이 명시된 경우에만 위에서 설정된다. 마감을 못 찾은 항목은
        #  게시일 기준 노후 정리 로직이 정직하게 처리한다.)
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
            # 오늘 폴링 차례가 아님 → 이전 수집분 승계 (필터는 최신 기준으로 재적용)
            carried = [it for it in prev_items
                       if (it.get("channel") == src["id"]
                           or (not it.get("channel") and src["domain"] in it.get("source", "")))
                       and relevant(it["title"])
                       and musician_relevant(it["title"], it.get("kind", "기타"), it.get("org", ""))]
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
                    # 본문 파싱 결과 승계 — 재파싱 방지
                    for f_ in ("recruitParts", "recruitSummary", "positions",
                               "personnel", "auditionDate", "contract",
                               "qualification", "rehearsal", "concertDate",
                               "pay", "program", "bodyExcerpt", "instDetails",
                               "applyEmail", "applyPhone", "subject", "courses"):
                        if old.get(f_) and not it.get(f_):
                            it[f_] = old[f_]
                if not it["deadline"]:
                    tdl = deadline_from_title(it["title"], ref_year=_ref_year(it))
                    if tdl:
                        it["deadline"] = tdl
                        it["deadlineFrom"] = "title"
            # 상세 파싱 대상: (1) 마감 미확인 → 전체 보강, (2) 마감은 있으나
            # 본문 요약(자격·인원·일정)이 없는 항목 → 본문만 가볍게 보강
            # 기독정보넷은 상세가 가벼운 표 파싱 → 마감 유무와 무관하게 매 실행 전량 재추출
            # (마감 승계로 enrich를 건너뛰면 org가 폴백으로 되돌아가는 문제 방지)
            need = kept if src["id"] == "cjob" else [i for i in kept if not i["deadline"]]
            cap = len(need) if src["id"] == "cjob" else MAX_DETAIL_PER_SOURCE
            for it in need[:cap]:
                enrich_deadline(s, it, allow_render=src["layer"] in ("B", "D"))
            budget = MAX_DETAIL_PER_SOURCE - min(len(need), MAX_DETAIL_PER_SOURCE)
            detail_need = [i for i in kept if i["deadline"] and not i.get("bodyExcerpt")]
            for it in detail_need[:budget]:
                enrich_deadline(s, it, allow_render=False, details_only=True)
            # 원문이 '공지 목록'인 항목은 enrich 여부와 무관하게 상세 공고로 딥링크화
            # (마감·요약이 이미 있어 enrich를 건너뛴 hibrain 항목 등)
            for it in kept:
                if it.get("officialUrl") and _LIST_URL.search(it["officialUrl"]) \
                        and not it.get("originDeepened"):
                    _deepen_list_origin(s, it)
            # hibrain(대학 음악채용 카테고리) 항목 정밀화:
            #  · 제목에 이미 음악 전공/악기 신호가 있으면 신뢰(성악과·지휘 등) — 그대로 노출
            #  · '○○대 강사 모집'처럼 전공 미상 대학 공고면 원문 첨부 교과목표로 음악 전공 검증
            #  · 대학도 음악도 아닌 항목(인사혁신처 등 카테고리 오분류)은 제외
            for it in kept:
                if it.get("source") != "hibrain.net" or it.get("subject") or it.get("nonMusic"):
                    continue
                blob = it["title"] + " " + it.get("org", "")
                if _MUSIC_TITLE.search(blob):
                    continue
                if re.search(r"대학교|대학원|예술학교|대학\b", blob):
                    _music_from_origin(s, it)
                else:
                    it["nonMusic"] = True   # 비대학·비음악 (예: 인사혁신처 개방형직위)
            # 마감이 게시일보다 '한참'(>180일) 앞서면 연말→연초 연도 오타로 보고 +1년 보정
            # (며칠 앞선 건 그냥 지난 공고 — 잘못 미래로 밀어올리지 않음)
            for it in kept:
                if it["deadline"] and it["date"] and it["deadline"] < it["date"]:
                    try:
                        gap = (date.fromisoformat(it["date"]) - date.fromisoformat(it["deadline"])).days
                    except ValueError:
                        gap = 0
                    if gap > 180:
                        fixed = f"{int(it['deadline'][:4]) + 1}{it['deadline'][4:]}"
                        if fixed <= f"{int(it['date'][:4]) + 1}-12-31":
                            it["deadline"] = fixed
                            it["deadlineFrom"] = (it.get("deadlineFrom") or "") + "+yearfix"
            # 마감이 이미 지난 공고는 제거 (오늘 이전) — 만료 공고 노출 방지
            kept = [i for i in kept if not (i["deadline"] and i["deadline"] < today.isoformat())]
            # 마감을 못 찾았고 게시된 지 120일 넘은 공고는 정리 (사실상 만료 — 상시모집은 예외)
            # 무마감 공고를 '기한 확인 필요'로 오래 노출하지 않기 위함
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
    # 대학 전체 강사 초빙 중 첨부 확인 결과 음악 교과목이 전혀 없던 공고는 제외(비음악 확정)
    final = [i for i in final if not i.get("nonMusic")]
    for it in final:
        old = prev_by_id.get(it["id"])
        it["firstSeen"] = old.get("firstSeen", today.isoformat()) if old else today.isoformat()
        it["isNew"] = it["firstSeen"] == today.isoformat()
        it["extVer"] = EXT_VER
        # 제목 기반 분류(kind/tier/ageGroup)는 순수 함수 — 승계 항목도 최신 로직으로 재적용
        # (서버 장애로 원본 0건 승계된 항목이 옛 분류를 물고 오는 것 방지)
        it["ageGroup"] = age_group(it["title"], it.get("org", ""))
        it["kind"] = classify_kind(it["title"])
        it["tier"] = classify_tier(it["title"], it.get("org", ""))   # 등급 최신 로직 재적용
        it["obri"] = is_obri(it["title"], it.get("org", ""))
        # 자격 필드 — 본문(자격·요약)까지 반영해 정확도 향상
        qtext = " ".join(str(it.get(f, "") or "") for f in ("title", "qualification", "bodyExcerpt", "recruitSummary"))
        it["certReq"] = cert_required(it["tier"], it["title"], qtext)
        it["degreeReq"] = degree_req(qtext)
        it["careerReq"] = career_req(qtext)
        if it["kind"] == "교수" and not it.get("subject"):
            subj = find_subject(it["title"])
            if subj:
                it["subject"] = subj
    n_unclass = sum(1 for it in final if it["tier"] == "미분류")
    if n_unclass:
        log(f"미분류 큐: {n_unclass}건 — {'; '.join(it['title'][:24] for it in final if it['tier'] == '미분류')}")
    final.sort(key=lambda x: (x.get("date") or x["firstSeen"]), reverse=True)

    payload = {
        "collectedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sourceCount": len(SOURCES),
        "okCount": sum(1 for x in source_stats if x["ok"]),
        "instTotal": len(INSTITUTIONS),   # 대조 기관 명부 규모
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
    n_minor = sum(1 for it in final if it.get("ageGroup") == "미성년")
    log(f"연령 분포: 성인 {len(final) - n_minor} / 미성년 {n_minor}"
        + (f" → 미성년 공고: {'; '.join(it['title'][:30] for it in final if it.get('ageGroup') == '미성년')}" if n_minor else ""))
    log(f"완료: {len(final)}건 저장 (dedup 전 {len(uniq)}건) → {OUT}")

    # ---------- 안전장치: 소스 장애 텔레그램 알림 ----------
    # 실패(예외) 소스 + 0건 반환으로 승계된 소스를 요약해 알림 (정상이면 조용)
    fails = [x for x in source_stats if not x.get("ok")]
    if fails:
        try:
            sys.path.insert(0, r"C:\ohai\telegram-notify")
            from notify import send
            lines = [f"· {x['name']}: {x.get('error', '?')[:60]}" for x in fails[:8]]
            send(f"[포디엄] 크롤 소스 {len(fails)}곳 실패 "
                 f"(전체 {len(SOURCES)}곳, 수집 {len(final)}건)\n" + "\n".join(lines),
                 silent=True)
        except Exception:
            pass

if __name__ == "__main__":
    run(force_all="--all" in sys.argv)
