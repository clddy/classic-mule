# 메인: 소스 레지스트리 기반 수집 → dedup(canonical) → 마감일 보강 → 커버리지 리포트
import json, os, re, sys, time, traceback
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (new_session, get, relevant, extract_deadline, priority_deadlines, deadline_from_title,
                    musician_relevant, youth_member, participant_only, student_target, dance_member, school_title, parse_recruit_table, summarize_recruit, find_position,
                    classify_insts, find_subject, find_music_subjects, find_music_courses,
                    classify_kind, classify_tier, is_obri, cert_required, degree_req, career_req, age_group,
                    region_from, EXCLUDE, compact_title, music_only_title, body_text, valid_addr,
                    insts_from_recruit_text, tls_blocked, curl_get, extract_fields, extract_contact)
from sources import SOURCES
from institutions import INSTITUTIONS
import attach
import rawstore

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
    # 2차: 같은 기관 + 같은 마감인데 악기 집합이 포함관계면 재공고(악기 추가)로 보고 병합.
    # (KBS '비올라·오보에' 원공고 → '비올라·오보에·타악기' 추가 재공고가 둘 다 남는 문제)
    by_org = {}
    for it in out:
        if it.get("deadline") and not GENERIC_ORG.search(it.get("org", "")):
            by_org.setdefault((norm_org(it["org"]), it["deadline"]), []).append(it)
    drop = set()
    for group in by_org.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda x: len(x.get("instDetails") or []), reverse=True)
        for i, small in enumerate(group[1:], 1):
            s = set(small.get("instDetails") or [])
            if s and any(s < set(big.get("instDetails") or []) for big in group[:i]):
                drop.add(small["id"])
    return [it for it in out if it["id"] not in drop]

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

EXT_VER = 69         # 마감일 추출기 버전 — 올리면 이전 수집의 마감일·전공 승계가 무효화됨
                     # v32(2026-08-02): 모집분야 구획 악기 추출(insts_from_recruit_text) + 원문 보관층
                     # 24: work.sen 등록일(게시일) 추출 추가 — date=None이던 승계분을 다시 뽑게
                     # 25: body_text 도입 — 본문을 <header>에 넣는 사이트(대전교육청)의 마감일을
                     #     스스로 날리던 버그 수정. 못 찾았던 항목들을 다시 뽑게 한다.
                     # 26: 자격 라벨쓰레기('경력 경력 학력') 거부 + 본문요약 메뉴·제목중복 제거
                     #     — 승계된 오염 값들을 재추출로 씻어낸다.
                     # 27: 본문요약 OCR 파편 배제(이미지 공고문이 깨져 기호만 남는 줄)
                     # 28: OCR 타일링 — 세로로 긴 인포그래픽(4500x13577 등)을 조각내 읽는다.
                     #     통짜로 넘기면 Tesseract가 뭉개 마감일을 통째로 놓쳤다.
                     # 29: 자격 중복라벨 정리·본문요약 메뉴 제거·악기군(현악부·관악부) 태그
                     # 30: 대학 전공 추출에 원문 본문 포함(첨부가 웹뷰어인 대학 대응)
                     # 31: 본문요약을 정보 가치순으로 선별(상투구 배제), 기타(guitar) 강사 제외
                     # 23: region_from 개편(전남광주통합특별시 반영, 경기 광주시 오분류 수정)
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
    if not (q and len(q) >= 5 and _QUAL_OK.search(q)):
        # 실제 자격 표현이 담긴 경우만 채택 (○실기·전형 조기절단 파편 배제)
        return None
    # 표의 열 제목만 긁힌 경우('경력 경력 학력') 배제 — 라벨 어휘로만 이뤄진 값은 정보가 아니다
    if re.fullmatch(r"(?:경력|학력|자격|연령|성별|무관|우대|사항|세부내용|및|과|[,·/\s])+", q):
        return None
    # 표의 '열 제목 + 값'이 나란히 긁혀 라벨이 겹치는 경우: '경력 경력 5년 학력 대학교(4년)'
    # → 앞의 홀로 선 라벨을 지워 '경력 5년 학력 대학교(4년)'로 읽히게 한다 (2026-08-02 지적)
    q = re.sub(r"(경력|학력|자격|연령|성별|우대)\s+(?=\1)", "", q)
    return q

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
    if not v or _PAY_NOISE.search(v):
        return None
    # 금액이 보이거나 '협의'라고 적힌 것만 페이로 인정한다. 예전엔 '규정'만 있어도
    # 통과시켰는데, 법령 이름에 그 낱말이 들어가는 바람에 「공무원보수규정」 제8조에 따라
    # 산정된 호봉의 봉급을… 같은 인용문이 페이 칸에 실렸다 — 읽어도 금액을 알 수 없다.
    # (2026-08-09. 같은 판정을 common.extract_fields·js/jobs.js okPay 와 세 곳에서 맞춘다)
    if not re.search(r"[\d,]{2,}\s*(?:만\s*)?원|시급|일당|협의", v):
        return None
    # 금액까지만 남긴다 — 뒤에 복무·보험 설명이 줄줄 이어지면 카드에서 읽히지 않는다
    m2 = re.search(r"(?:시간당|시급|월|주|일당|회당|연간?)?\s*[\d,]{2,}\s*(?:만\s*)?원"
                   r"(?:\s*\([^)]{1,10}\))?", v)
    return v[:m2.end()].strip(" ,·-–") if m2 else v

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
    # 개인정보 수집·이용 동의표. '개인정보'라는 낱말이 표 제목에만 있고 각 줄에는 없어서
    # 기존 규칙을 통과해 요약에 실렸다 — '이용 목적: 구직활동 지원 및…', '보유기간: 회원
    # 탈퇴 시까지(2년)', '제공받는자: 각급기관 채용담당자' (2026-08-08 사용자 지적).
    # 지원자에게 아무 정보도 주지 않는 줄이다.
    r"|이용 ?목적|보유 ?기간|제공받는 ?자|수집 ?항목|수집·?이용|제3자 ?제공|동의 ?여부|처리 ?방침"
    r"|\[채용공고\]|\[공지\]|\[입찰\]|\[결과\]|\[알림\]"
    # 게시판 메뉴 항목이 본문으로 긁힌 경우 (경기교육청: '교직원 온라인 채용', '구)자원봉사자모집')
    r"|온라인 ?채용$|^구 ?\)|자원봉사자 ?모집$"
    # 내용 없는 섹션 제목 줄 ('채용방법 및 일정')
    r"|^(?:채용|모집|지원|접수|전형) ?(?:방법|절차|일정|안내)(?: ?및 ?(?:방법|절차|일정|안내))?$"
    # 채용 사이트의 사이드 메뉴·표 헤더가 본문으로 긁힌 경우 (광진문화재단 등 gabia 채용 CMS)
    r"|진행 ?중인 다른|다른 채용 ?공고|채용공고명|담당업무 ?/|장애인 채용 ?희망|우대 ?조건 ?/"
    # 알맹이 없는 공문 상투구 — 어느 공고에나 있어 요약 자리를 낭비한다 (2026-08-02 김포여중)
    r"|다음과 같이 (?:공고|모집|채용|알려)|공고하고자|채용 ?계획을|위와 같이 ?공고"
    r"|^내국인으로서|^채용 ?(?:응시 )?자격$|^모집 ?세부 ?사항$|^응모 ?자격$|^채용 ?분야$")

def _body_excerpt_text(text, title=None):
    keep = []
    tnorm = re.sub(r"\s+", " ", title).strip() if title else ""
    for raw in (text or "").split("\n"):
        ln = re.sub(r"\s+", " ", raw).strip(" ·-•▷▶◦□■●○△*|:")
        if not (8 <= len(ln) <= 90) or ln in keep:
            continue
        # 게시글 제목이 본문 첫 줄로 반복되는 경우 — 요약에 제목을 또 싣지 않는다
        if tnorm and (tnorm[:14] == ln[:14] or tnorm in ln or ln in tnorm):
            continue
        # OCR 파편 배제 — 이미지 공고문을 읽다 깨지면 기호 부스러기만 남는다
        # ('— . 〈 오디션일정〉 rr', '. _ _ . . 모집파트 。 .' — 통영시민오케 2026-07-29).
        # 날짜·번호에 정상적으로 쓰이는 기호(. : , ~ ( ) / -)는 세지 않는다 —
        # 다 세면 '3. 서류접수: 2026. 7.24.(금)' 같은 알짜 줄까지 잘려나간다.
        solid = len(ln.replace(" ", ""))
        if solid and len(re.findall(r"[^가-힣A-Za-z0-9\s.:,~()/\-]", ln)) / solid > 0.15:
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
    if not keep:
        return None
    # 앞에서부터 4줄을 자르면 '채용 계획을 다음과 같이 공고하고자 합니다' 같은 도입부만
    # 실린다 — 김포여중은 강사료(시간 4만원)·운영조건·접수 이메일이 본문에 다 있는데도
    # 껍데기만 요약됐다(2026-08-02 지적). 그래서 '지원자가 궁금해할 사실'이 든 줄에 점수를
    # 매겨 상위 4줄만 남기고, 읽기 순서는 원문 그대로 되돌린다.
    ranked = sorted(keep, key=lambda l: (-_line_value(l), keep.index(l)))[:4]
    picked = [l for l in keep if l in ranked]
    return " · ".join(picked)[:240]


def _line_value(ln):
    """요약 줄의 정보 가치 — 금액·연락처·기간·인원처럼 지원 판단에 쓰이는 사실일수록 높다."""
    v = 0
    if re.search(r"\d[\d,]*\s*원", ln):                       v += 3   # 강사료·급여
    if re.search(r"[\w.+-]+@[\w.-]+|\d{2,4}-\d{3,4}-\d{4}", ln): v += 3   # 이메일·전화
    if re.search(r"20\d{2}\s*[.\-년]|\d{1,2}\s*월\s*\d{1,2}", ln): v += 2   # 날짜
    if re.search(r"주\s*\d+\s*회|\d+\s*시간|\d+\s*주\b|\d+\s*개반", ln):   v += 2   # 시수·운영조건
    if re.search(r"\d+\s*명", ln):                            v += 2   # 인원
    if re.search(r"자격증|학위|전공자|경력\s*\d|이상\s*(?:취득|소지)", ln): v += 2   # 자격 요건
    if re.search(r"[:：]", ln):                               v += 1   # 라벨형(값이 붙어 있음)
    return v

def _body_excerpt(soup, title=None):
    return _body_excerpt_text(soup.get_text("\n", strip=True), title=title)

def _merge_insts(item, grp, dets):
    """추출된 악기를 기존 태그와 합친다 — 제목 추출분을 지우지 않는다(악기명 보존 원칙)."""
    if not dets:
        return
    item["instDetails"] = list(dict.fromkeys((item.get("instDetails") or []) + dets))
    if item.get("inst") in (None, "", "전체", "기타") and grp:
        item["inst"] = grp

def _apply_details_from_text(text, item, want_excerpt=True):
    """평문 본문(페이지/첨부/OCR)에서 자격·인원·객원필드·요약을 채운다 (없는 것만)"""
    if not text:
        return
    # 모집분야 구획에서 악기 추출 — 제목엔 '예능단원'뿐이고 파트가 첨부 공고표에만 있는
    # 공고(대전시향 등)가 악기 미상의 최대 원인이었다 (2026-08-02, 163건 중 161건).
    _merge_insts(item, *insts_from_recruit_text(text))
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
        ex = _body_excerpt_text(text, title=item.get("title"))
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
        ex = _body_excerpt(soup, title=item.get("title"))
        if ex:
            item["bodyExcerpt"] = ex
    # 본문에서 악기 탐지 후 제목에서 뽑은 것과 **합친다**. 예전엔 제목에 악기가 하나라도
    # 있으면 본문을 안 봤는데, 군산시향처럼 제목엔 악기가 없고 본문 접수분야에 '피아노,
    # 현악부, 관악부, 타악부'가 있는 공고에서 일부만 태그되는 원인이었다 (2026-08-02).
    _merge_insts(item, *classify_insts(page_text[:3000]))

# 한 공고에서 열어 볼 첨부 수. 예전엔 '본문 요약이 채워지면 멈춤'이었는데, 그러면 첫 파일
# 하나만 읽고 끝난다 — 통영시립소년소녀합창단은 File#1 이 응시원서 서식이라 거기서 멈췄고
# 정작 마감일이 든 File#2 '공고문(합창지도자).pdf' 를 열지도 않았다 (2026-08-09).
MAX_ATTACH_PER_ITEM = 4


def _body_from_attachments(s, soup, r, item):
    """첨부 공고문(HWP/PDF)에서 본문 상세(자격·인원·요약) 보강 — 마감일 로직과 무관.
    본문이 첨부에만 있는 집계·게시판(cwcf·bscc 등) 대응."""
    # 공고문처럼 보이는 파일을 먼저 연다. 첨부 목록의 순서는 기관 마음이라, 응시원서 서식이
    # 1번이고 공고문이 2번인 곳이 흔하다 — 통영시립소년소녀합창단이 그랬다.
    files = sorted(find_attachments(soup, r.url),
                   key=lambda fn: 0 if re.search(r"공고|모집|채용", fn[1] or "") else 1)
    for furl, fname in files[:MAX_ATTACH_PER_ITEM]:
        try:
            fr = (curl_get(furl, referer=item["url"], timeout=30) if tls_blocked(furl)
                  else s.get(furl, timeout=30, verify=False, headers={"Referer": item["url"]}))
            if fr.status_code != 200 or not (200 < len(fr.content) < 20_000_000):
                continue
            cd = fr.headers.get("Content-Disposition", "")
            m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
            name = m.group(1) if m else (fname or furl)
            atext = attach.extract_any(name, fr.content)
            rawstore.stash(item.get("id"), "attach", atext, name=name)
            _apply_details_from_text(atext, item)
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
    # 기본정보 표의 주소 — 상세 본문에도 지역이 적히지만 오타가 잦다(성은교회 공고는 본문에
    # '수원시 오정구'라고 썼는데 수원엔 오정구가 없다. 표 쪽이 '부천시 오정구'로 맞다).
    addr = grab(r"-\s*주소\s*(.+?)\s*-\s*(?:연락처|담당자|담당|모시는분|등록일)")
    if addr and valid_addr(addr):
        item["addr"] = addr
    org = grab(r"단체\(회사\)이름\s*(.+?)\s*-\s*(?:주소|연락처|담당자|담당|모시는분)")
    if org and 2 <= len(org) <= 30 and org != "미정":
        item["org"] = org
    role = grab(r"모시는분\s*(.+?)\s*-\s*(?:지역|등록일|남은기간)")
    if role and len(role) <= 20:
        item["personnel"] = role
    reg = grab(r"지역\s*(.+?)\s*-\s*(?:등록일|남은기간)")
    if reg in _CJOB_REGIONS:
        item["region"] = region_from(reg)      # 17개 전 지역 유지 (예전엔 6개만 남기고 기타로 버렸다)
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
    # '회사명, 교회명(교단) : 인덕원꿈의교회 대한예수교장로회 (예장대신)' 처럼 교회 이름과
    # 교단이 한 칸에 같이 들어온다. 교회 이름은 카드 앞에 세울 딱지가 되므로 따로 뽑는다
    # ('[인덕원꿈의교회] 기타/첼로/유치원교사 구합니다' — 2026-08-09 사용자 지시).
    # 교단만 적힌 칸('예장 합동', '순복음')도 흔해서, 교회로 끝나는 이름이 있을 때만 쓴다.
    org_cell = grab(r"교회명\(교단\)\s*:?\s*([^:]{1,40}?)\s*(?:제출|주소|사례비|담당|연락처|사진|상세|모집|사역|$)")
    if org_cell:
        m_ch = re.search(r"([가-힣]{2,12}(?:교회|성당|채플))", org_cell)
        if m_ch:
            item["org"] = m_ch.group(1)
        denom = re.sub(r"[가-힣]{2,12}(?:교회|성당|채플)", "", org_cell).strip(" ()·-")
        if denom and 1 <= len(denom) <= 20:
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
        dl = extract_deadline(body_text(r.text), ref_year=ry)
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
            atext = attach.extract_any(name, fr.content)
            rawstore.stash(item.get("id"), "attach", atext, name=name)
            texts.append(atext)
        except Exception:
            continue
        if len(texts) >= 6:
            break
    # 첨부를 못 열어도 원문 본문에 초빙 분야가 적힌 대학이 많다 — 목원대는 첨부가 웹뷰어
    # (v.mokwon.ac.kr/View/...)라 다운로드 링크가 아예 없었지만, 본문에 '음악대학
    # 공연콘텐츠학부(성악전공·뮤지컬전공…)'이 그대로 있었다. 첨부만 보던 탓에 전공을
    # 놓치고 '자동확인 불가'로 눕혔다 (2026-08-02 지적).
    blob = "\n".join(texts + [body_text(r.text)]).strip()
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


def _refill_from_raw(items, today):
    """요약·마감이 빈 공고를 원문 보관층(data/raw)에서 되살린다 — 네트워크 없이.

    상세 방문은 소스당 MAX_DETAIL_PER_SOURCE(20)로 묶여 있어 뒤쪽 공고가 방문되지 못하는
    일이 있다. raw 층은 그럴 때 쓰라고 쌓아둔 것이라, 이미 받아둔 본문에 추출기를 다시
    돌려 메운다. 추출 규칙을 고치면 과거분에도 이 경로로 소급된다.

    (2026-08-07 정정: 마감 확보율이 84%→11%로 떨어진 것을 '방문 예산 부족'으로 적었었는데
     틀렸다. 마감 없는 67건 전부 실제로 방문돼 있었다 — 진짜 원인은 모집단 변화로,
     마감일이 원래 없는 교회 상시 공고가 대거 들어온 것이었다.)
    """
    n_ex = n_dl = n_fd = 0
    for it in items:
        raw = rawstore.load(it.get("id"))
        page = (raw or {}).get("page")
        if not page:
            continue
        # 급여·근무기간·근무시간·담당업무·나이 — 공고문이 '라벨 : 값'으로 적어 둔 것을 항목으로
        # 세운다. 본문 발췌는 문장을 골라 오는 것이라 조건을 한눈에 보기 어렵다
        # (2026-08-08 사용자 가이던스).
        # 기독정보넷은 상세 표를 전용 파서로 읽는다(단체명·지역·모시는분·남은기간). 그런데 그
        # 파서는 '상세를 직접 여는' 경로에만 있었다 — 방문 예산에 밀리거나 승계된 항목은
        # 원문을 보관해 두고도 표를 못 읽어, 기관이 '교회(기독정보넷)'·지역이 '기타'로 남았다
        # (2026-08-09 성은교회 공고: 원문엔 단체명·지역·사례비·업무가 다 있었다).
        if "cjob" in (it.get("source") or ""):
            _cjob_detail(rawstore.all_text(it["id"]), it)
        _raw = rawstore.all_text(it["id"])
        # 자격·연락처는 상세를 직접 여는 경로에만 있었다. 원문을 보관해 두고도 재추출에서
        # 빠져 있어 화면엔 0건이었다 — 원문으로 다시 뽑으면 자격 15건·연락처 22건이 나온다
        # (2026-08-11). 오늘 페이·기독정보넷 표에서 겪은 것과 같은 구조다.
        if not it.get("qualification"):
            q = _find_qualification(_raw)
            if q:
                it["qualification"] = q
        if not it.get("contact"):
            c = extract_contact(_raw)
            if c:
                it["contact"] = c
        fields = extract_fields(_raw)
        if fields:
            for k, v in fields.items():
                # 파서가 채운 값이 있으면 그쪽이 우선. 단 setdefault 는 키가 None 으로 이미
                # 있으면 그냥 넘어간다 — make_item 이 personnel 을 None 으로 만들어 두기
                # 때문에 '모집 인원: O명'이 영영 안 실렸다 (2026-08-08).
                if not it.get(k):
                    it[k] = v
            n_fd += 1
            # 공고문이 '구인 회사명'을 직접 밝혔으면 그게 고용주다. 게시판 주인도, 제목 맨 앞
            # 이름도 아니다 — 제주 신라호텔 공고는 연세대 게시판에 올라왔고 제목은 호텔
            # 이름으로 시작하지만, 실제로 뽑는 곳은 에이디엔노뜨이고 호텔은 공연 장소다.
            # 주소가 있으면 지역은 추측할 필요가 없다 — 제목·기관명 짐작보다 정확하다.
            ad = it.get("addr") or fields.get("addr")
            if ad:
                rg2 = region_from(ad)
                if rg2 and rg2 != "기타" and rg2 != it.get("region"):
                    it["regionBoard"], it["region"] = it.get("region"), rg2
            ho = fields.get("hiringOrg")
            if ho and 2 <= len(ho) <= 30 and ho != it.get("org"):
                it["orgBoard"] = it.get("org")
                it["org"] = ho
                # 게시판이 고용주가 아니면 게시판에서 따온 지역도 못 믿는다. _fix_org_from_title
                # 에도 같은 보정이 있지만 이 항목은 거기서 건너뛰므로 여기서 해 준다 —
                # 안 하면 제주 신라호텔 공고가 연세대 게시판 때문에 서울로 남는다.
                rg = region_from(f"{it.get('title','')} {fields.get('perfPlace','')}")
                if rg and rg != "기타" and rg != it.get("region"):
                    it["regionBoard"], it["region"] = it.get("region"), rg
        if not it.get("bodyExcerpt"):
            # 보관된 본문은 공백으로 이어붙인 한 덩어리다 — 줄 단위로 고르는 요약기가
            # 쓰도록 문장 끝·구분점에서 줄을 나눠 준다.
            lines = re.sub(r"(?<=[.。!?])\s+|\s*·\s*|\s{2,}", "\n", page)
            ex = _body_excerpt_text(lines, title=it.get("title"))
            if ex:
                it["bodyExcerpt"] = ex
                n_ex += 1
        if not it.get("deadline") and it.get("deadlineNote") != "상시":
            # 마감은 첨부까지 훑는다 — 공고문이 이미지 한 장뿐이고 본문엔 인사말만 있는
            # 경우가 흔하다. 통영시민오케스트라는 OCR 텍스트에 '접수기간 7.20~8.14'가
            # 멀쩡히 저장돼 있는데 본문만 보느라 놓쳤다 (2026-08-07).
            # 첨부 공고문을 먼저 본다 — 게시판 상세는 그 사이트의 다른 공고 목록을 달고
            # 오는 곳이 많아 본문부터 훑으면 남의 날짜를 문다 (rawstore.attach_text 머리말).
            cands = _raw_deadlines(it)
            dl = max(cands) if cands else extract_deadline(rawstore.all_text(it["id"]),
                                                           ref_year=_ref_year(it))
            # 제목에만 마감이 적힌 공고('…모집(~8/14)')는 본문 규칙으로 안 잡힌다.
            # 수집 때는 deadline_from_title 이 봤지만 재추출 경로엔 그 단계가 없었다.
            if not dl:
                dl = deadline_from_title((raw or {}).get("title") or it.get("title") or "",
                                         ref_year=_ref_year(it))
            # 지난 날짜를 마감으로 앉히면 멀쩡한 공고가 '마감'으로 사라진다 — 오늘 이후만
            if dl and dl >= today.isoformat():
                it["deadline"] = dl
                it["deadlineFrom"] = "raw"
                n_dl += 1
    if n_ex or n_dl or n_fd:
        log(f"원문 보관층에서 복구: 요약 {n_ex}건 · 마감 {n_dl}건 · 조건항목 {n_fd}건")


# 제목 맨 앞에 박힌 기관명. 게시판 주인이 아니라 **실제 뽑는 곳**이다.
_ORG_TAIL = (r"(?:교향악단|필하모닉|합창단|예술단|국악단|무용단|관현악단|오케스트라|오페라단"
             r"|문화재단|예술의전당|문화예술회관|아트센터|호텔"
             r"|중학교|고등학교|초등학교|대학교)")
# 붙여 쓴 이름을 **먼저** 시도하고, 그걸로 이름이 끝나지 않을 때만 한 칸 띄어쓰기를 넘는다
# ('제주 신라호텔', '대구광역시 시립교향악단'). 순서를 뒤집거나 한 패턴으로 합치면
# '조선대학교여자중학교'에서 멈추지 않고 뒤의 '학생오케스트라'까지 삼킨다 (2026-08-07).
_ORG_IN_TITLE = re.compile(
    r"^(?:\[[^\]]{1,14}\]\s*)?(?:20\d{2}\s*년?\s*)?(?:상반기|하반기|[1-4]차)?\s*"
    r"([가-힣]{2,14}" + _ORG_TAIL + r"|[가-힣]{2,10}\s[가-힣]{2,10}" + _ORG_TAIL + r")")


def _fix_org_from_title(items):
    """게시판 주인을 기관으로 적어 둔 공고를 바로잡는다.

    기관들은 서로의 채용 공고를 자기 게시판에 옮겨 싣는다. 그럼 파서가 게시판 주인을
    org로 잡아 카드에 엉뚱한 기관이 뜬다 — 연세대 음대 게시판의 '천안시립교향악단
    예술감독 모집'이 org=연세대학교, 고양문화재단 게시판의 '과천시립예술단 반주자
    공개채용'이 org=고양문화재단으로 나갔다 (2026-08-07).

    제목 맨 앞이 기관명이면 그게 뽑는 주체다. 게시판 주인과 겹치면(같은 기관이 자기
    공고를 올린 정상 경우) 손대지 않는다. 원래 값은 orgBoard 로 남겨 추적 가능하게 둔다.
    """
    fixed = []
    for it in items:
        # 공고문이 '구인 회사명'을 밝혀 이미 기관을 정한 항목은 건드리지 않는다. 제목 맨 앞은
        # 공연 장소일 수 있다 — 제주 신라호텔 공고의 고용주는 에이디엔노뜨다 (2026-08-08).
        if it.get("hiringOrg"):
            continue
        m = _ORG_IN_TITLE.match(it.get("title") or "")
        if not m:
            continue
        name, org = m.group(1), (it.get("org") or "")
        # 앞 두 글자만 견주면 지역명이 같다는 이유로 다른 기관을 같다고 본다
        # ('대전교육청' vs '대전선암초등학교'). 이름 전체의 포함 관계로만 같다고 인정한다.
        if not org or name in org or org in name:
            continue
        it["orgBoard"], it["org"] = org, name
        # 게시판이 뽑는 곳이 아니면 게시판에서 따온 지역도 못 믿는다 — '제주 신라호텔'이
        # 연세대 게시판 때문에 서울로, 천안시립교향악단이 서울로 떠 있었다.
        # 다만 제목에서 **구체적 지역이 나올 때만** 덮는다. '기타'로 떨어지면 게시판 쪽이
        # 오히려 맞다(함양제일고 → 경남을 '기타'로 지워 버릴 뻔했다).
        rg = region_from(it["title"]) or region_from(name)
        if rg and rg != "기타" and rg != it.get("region"):
            it["regionBoard"], it["region"] = it.get("region"), rg
        fixed.append(it)
    if fixed:
        log(f"기관명 정정 {len(fixed)}건 (게시판 주인 → 실제 모집 기관) — "
            + "; ".join(f"{i['orgBoard']}→{i['org']}" for i in fixed[:5]))
    return fixed


# 게시판이 스스로 붙인 접수 상태. '접수중·접수전'과 헷갈리지 않게 마감 어휘만 건다.
_BOARD_CLOSED = re.compile(r"(?:채용|접수|모집)\s*상태\s*[:\s]*(?:마감|종료)")


def _span_days(a, b):
    """두 ISO 날짜 사이 일수 — 마감일 후보들이 얼마나 흩어져 있는지 재는 데 쓴다."""
    try:
        return abs((date.fromisoformat(b) - date.fromisoformat(a)).days)
    except (ValueError, TypeError):
        return 0


# 게시판이 목록 칸 너비에 맞춰 제목을 잘라 놓은 흔적
_TRUNCATED = re.compile(r"(?:_+|\.{2,}|…|·{2,})\s*$")
# 잘린 제목의 뒤를 상세 원문에서 이어 붙일 때, 여기서 멈춘다 (게시판 표의 다음 칸)
_TITLE_TAIL = ("작성일", "등록일", "게시일", "조회", "작성자", "분류", "공유", "프린트",
               "첨부", "담당부서", "채용여부", "연락처")


# 원문(raw)에서 다시 뽑을 수 있는 값들. 추출기를 고치면 이 값들은 낡은 것이 된다.
_EXTRACTED_FIELDS = ("pay", "courses", "subject", "qualification", "bodyExcerpt",
                     "personnel", "recruitSummary", "positions", "duty", "workPeriod",
                     "workHours", "workPlace", "perfPeriod", "perfPlace", "perfSchedule",
                     "teamComp", "dayOff", "ageLimit", "contact", "hiringOrg")


# 뽑아낸 값이 '수상해 보이는' 신호들. 화면에 나가기 전에 우리가 먼저 잡기 위한 것이다.
# 그동안은 사용자가 카드를 눈으로 보고 알려 줘야 알았다 — 그건 탐지가 아니다 (2026-08-10).
_SUSPECT = [
    ("다른 항목이 딸려옴", re.compile(r"(?:후생복지|복무|제출서류|접수방법|전형|우대사항|문의처|서류|제출)\s*[:：]")),
    ("항목기호 섞임",     re.compile(r"\s[가나다라마바사아자차]\.\s")),
    ("참조 문구",         re.compile(r"(?:위\s*표|상기|붙임|별첨|공고문)\s*(?:와|과)?\s*(?:같|참조)")),
    ("한자 부스러기",     re.compile(r"[一-鿿]{2,}")),
    # 개인정보 동의표의 수집 항목 나열('취업지원대상 여부, 학력사항, 경력정보…')이 자격으로
    # 실렸다 — 동의표 특유의 낱말로 잡는다 (2026-08-11 화면 검증에서 발각)
    ("동의표 조각",       re.compile(r"학력사항|경력정보|어학능력|취업지원대상|희망근무지|자기소개서?,")),
    # 워크넷식 표는 머리글(고용형태·사회보험·퇴직금…)이 한 줄로 이어진 뒤 값 뭉텅이가 온다.
    # 이 낱말이 값 안에 있으면 표 머리를 물어 온 것이다 — 제물포구 여성합창단 근무시간에
    # '사회보험 퇴직금 지급 방법 월급 1,300,000원…'이 실렸다 (2026-08-12 사용자 발견)
    ("표 머리 조각",       re.compile(r"사회보험|퇴직금|고용형태|접수마감일")),
    # OCR 이 한글을 영단어로 오인한 흔적 — 'SAS 가지고 We 자' (종로문화재단, 워크오더 F20).
    # 한글 사이에 낀 고립 영단어가 둘 이상이면 오염으로 본다 (SNS·PC 같은 정상 약어는 한 개까지 허용)
    ("OCR 영단어 혼입",    re.compile(r"(?:[가-힣]\s+[A-Za-z]{2,6}\s+[가-힣].*){2,}")),
    # 문장 중간을 뚝 잘라 온 값 — '자는 관련 법률…', '여부, 학력사항…' 처럼 조사·꼬리말로
    # 시작하면 어떤 항목의 값도 아니다 (2026-08-12 전라중·상일미디어고)
    ("문장 조각",         re.compile(r"^(?:자는|자로서|여부|하는|되는|또는|및|등|의|을|를)[\s,]")),
]
# 법령 인용은 통째로 버리지 않고 그 앞까지만 남긴다 — '만 34세 이하(1991.1.1. 이후 출생자)
# (* 청년고용촉진특별법 제2조 준용)' 에서 앞부분은 지원자에게 필요한 정보다 (2026-08-11).
# (급여만 예외로 통째로 버린다 — 거기 법령만 있으면 금액을 알 수 없어 쓸모가 0이다)
_LAW_CITE = re.compile(r"\s*\(?\s*[*※]?\s*[「『]?[가-힣][가-힣\s]{1,28}(?:법률?|규정|예규|조례|지침)[」』]?\s*"
                       r"제?\s*\d+\s*조.*$")
_QC_FIELDS = ("pay", "workPeriod", "workHours", "workPlace", "duty", "ageLimit",
              "perfPeriod", "perfPlace", "perfSchedule", "teamComp", "dayOff",
              "personnel", "contact", "addr", "qualification")

# 게시 직전 최종 검수 — 값이 '그 항목답게' 생겼는가. 추출이 어디서 왔든(직접 방문·재추출·
# 승계·overrides) 여기서 한 번은 반드시 걸러진다. 통과 못 하면 빈칸으로 내보낸다 —
# "빈칸이 있다면 과감히 빈칸으로" (2026-08-11 사용자 지시).
_QC_MUST = {
    "workPeriod": re.compile(r"\d"),                              # 기간엔 숫자가 있어야 한다
    "perfPeriod": re.compile(r"\d"),
    "pay":        re.compile(r"[\d,]{2,}\s*(?:만\s*)?원|시급|일당|사례|협의|상담|추후|결정"),
    "contact":    re.compile(r"^0\d{1,2}-?\d{3,4}-?\d{4}$"),      # 전화번호 그 자체여야 한다
    # 인원 칸엔 숫자 대신 역할명이 오기도 한다 — 기독정보넷 '모시는분: 반주자'.
    # 짧은 순한글(콜론 없음)이면 역할명으로 인정한다. 첫 검수에서 이걸 몰라
    # 정상값 '반주자' 26건을 먹었다 (2026-08-11).
    "personnel":  re.compile(r"\d|[Oo○]\s*명|^[가-힣·/\s]{2,16}$"),
    "ageLimit":   re.compile(r"\d|제한\s*없|무관"),
    "dayOff":     re.compile(r"[월화수목금토일]|주\s*\d|협의|지정"),
}


def _qc_fields(items):
    """수상한 값을 찾아 비우고 로그로 남긴다.

    규칙을 아무리 다듬어도 게시판이 늘면 새로운 꼴이 나온다. 그때 화면에 실려 나가는 대신
    여기서 걸러 두고, 무엇이 걸렸는지 남겨 다음 규칙의 재료로 쓴다.
    길이 상한도 함께 본다 — 카드에서 읽히지 않는 값은 없느니만 못하다.
    """
    hits = []
    for it in items:
        for f in _QC_FIELDS:
            v = it.get(f)
            if not isinstance(v, str) or not v:
                continue
            cut = _LAW_CITE.sub("", v).strip(" ,·-–")
            if cut != v and len(cut) >= 4:
                it[f] = v = cut          # 법령 인용만 떼고 앞부분은 살린다
            why = next((name for name, pat in _SUSPECT if pat.search(v)), None)
            if not why and len(v) > 90:
                why = f"너무 김({len(v)}자)"
            # 항목별 필수 모양 — 기간에 숫자가 없거나 연락처가 번호 꼴이 아니면 그 항목이 아니다
            must = _QC_MUST.get(f)
            if not why and must and not must.search(v):
                why = "모양 불일치"
            # 주소는 시도로 시작해야 한다. valid_addr(도로명+번지)까지 요구하면 지오코딩이
            # 만든 '서울특별시 광진구 군자로'(건물번호 없음)가 억울하게 잘린다.
            if not why and f == "addr" and not re.match(
                    r"^(?:\(?우?\)?\s*\d{5}\s*)?(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충[북남청]|전[북남라]|경[북남상]|제주)", v):
                why = "주소 모양 아님"
            if why:
                hits.append((f, why, it.get("title", "")[:22], v[:46]))
                it.pop(f, None)
    if hits:
        log(f"수상한 값 {len(hits)}건 제거:")
        for f, why, title, v in hits[:8]:
            log(f"   [{f}] {why} — {title} · {v}")
    return hits


def _attach_coords(items):
    """주소를 안 적은 공고에 기관 이름으로 찾아 둔 위치를 붙인다(crawler/geocode_jobs.py).

    공고 대부분이 주소를 안 적는데, 연주자에게 '어디인지'는 지원 여부를 가르는 정보다 —
    악기를 들고 가야 하기 때문이다 (2026-08-09 사용자 지시).
    """
    coords = {}
    try:
        with open(os.path.join(BASE, "data", "org-coords.json"), encoding="utf-8") as f:
            coords = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0
    n = 0
    for it in items:
        if it.get("addr"):
            continue
        key = re.sub(r"\([^)]*\)", " ", it.get("org") or "")
        key = re.sub(r"\s+", " ", key).strip(" ·-")
        c = coords.get(key)
        if c and c.get("addr"):
            it["addr"], it["lat"], it["lng"], it["addrFrom"] = c["addr"], c["lat"], c["lng"], "geo"
            n += 1
    return n


def _reset_stale_extracted(items):
    """추출기 버전이 낡은 항목의 '뽑아낸 값'을 비워 재추출 대상으로 만든다.

    소스가 0건을 돌려주면 이전 수집분을 통째로 승계한다(서버 장애로 공고가 사라지지 않게).
    그런데 승계 항목은 재파싱을 거치지 않으므로, 추출기를 고쳐도 옛 값이 그대로 남는다 —
    강원교육청 공고의 페이가 「공무원보수규정」 제8조… 인용문인 채로 버텼다. 규칙을 세 곳
    모두 고치고도 값이 안 바뀌어 한참 헤맸다 (2026-08-09).

    비워 두면 바로 뒤 _refill_from_raw 가 원문 보관층에서 다시 뽑는다. 원문이 없어 못 뽑으면
    비어 있게 되는데, 그게 틀린 값을 남기는 것보다 낫다.
    """
    n = 0
    for it in items:
        if it.get("extVer") == EXT_VER:
            continue
        # 마감일도 추출 유래(raw/page/attachment/title)면 함께 비운다. 규칙을 고쳐도 옛
        # 오염 마감이 승계로 영생했다 — 삼양초 12-31(정답 08-10), 중목초 08-24(정답 08-20),
        # 남성중 08-19(정답 08-18). 소스가 직접 준 값(cjob-남은기간·origin·상태:마감)은
        # 재추출로 복원할 수 없으므로 남긴다 (2026-08-15 워크오더 A·B).
        if it.get("deadline") and (it.get("deadlineFrom") in ("raw", "page", "attachment", "title", None)):
            it.pop("deadline", None)
            it.pop("deadlineFrom", None)
        if any(it.get(f) for f in _EXTRACTED_FIELDS):
            for f in _EXTRACTED_FIELDS:
                it.pop(f, None)
            n += 1
    return n


def _posted_date(it):
    """믿을 수 있는 게시일만 돌려준다.

    집계 포털은 자기가 그 글을 실은 날을 게시일로 준다 — 아트인포가 넘긴 경상북도
    도립예술단 공고의 '게시 2026-08-06'은 우리가 수집한 날이고, 실제 원서접수는 6월이었다.
    이 값을 '마감일이 게시일보다 이르면 남의 날짜' 판정에 쓰면, 정작 끝난 공고가
    계속 '기한 미정'으로 남는다 (2026-08-09).
    """
    return None if (it.get("source") or "") in AGGREGATORS else it.get("date")


def _raw_deadlines(it):
    """이 공고의 마감일 후보 — 첨부 공고문을 먼저 보되, 게시일보다 이른 값은 물리친다.

    첨부가 본문보다 정확하다(게시판 상세는 남의 공고 목록을 달고 온다). 다만 첨부에 지난
    회차 서식이 섞여 있는 곳도 있어서, 첨부값이 자기 게시일보다 이르면 그건 이 공고의
    날짜가 아니다 — 예울마루는 첨부에 2025-02 문서가 붙어 있어 본문의 제 날짜(2026-06-24)를
    밀어냈다 (2026-08-09).
    """
    ry, posted = _ref_year(it), _posted_date(it)
    for text in (rawstore.attach_text(it.get("id")), rawstore.all_text(it.get("id"))):
        cands = priority_deadlines(text, ref_year=ry)
        if cands and (not posted or max(cands) >= posted):
            return cands
    # 어느 쪽도 게시일 검사를 통과하지 못하면 첨부 → 본문 순으로 있는 대로 돌려준다
    return (priority_deadlines(rawstore.attach_text(it.get("id")), ref_year=ry)
            or priority_deadlines(rawstore.all_text(it.get("id")), ref_year=ry))


def _repair_titles(items):
    """게시판에서 잘려 온 제목의 뒤를 상세 원문에서 되찾는다.

    목록의 제목 칸은 너비가 정해져 있어 긴 제목이 '…' 이나 '_' 로 끊긴다. 우리는 그 목록
    글자를 그대로 제목으로 삼아 왔기 때문에 카드에도 잘린 채 실렸다
    ('대전선암초등학교 계약제교원(기간제교사-음악)채용_...' — 2026-08-08 사용자 지적).
    상세 페이지에는 온전한 제목이 있으므로, 잘린 앞부분을 실마리로 찾아 뒤를 잇는다.
    """
    fixed = 0
    for it in items:
        t = (it.get("title") or "").strip()
        # 제목에 학교·기관 이름이 전혀 없는데 본문에 '[강원사대부설고]' 같은 딱지가 있으면
        # 그걸 앞에 세운다 — 교육청 포털 제목은 '기간제교원(음악) 채용'처럼 밋밋해서
        # 어느 학교인지 카드만 봐서는 알 수 없다 (2026-08-11 사용자 지적).
        if not re.search(r"[가-힣]{2,}(?:초|중|고|학교|대학교|교회|성당|악단|합창단|재단)", t):
            page0 = re.sub(r"\s+", " ", (rawstore.load(it.get("id")) or {}).get("page") or "")
            mtag = re.search(r"\[([가-힣]{2,14}(?:초|중|고|여중|여고|예고|학교))\]", page0)
            if mtag:
                it["title"] = f"[{mtag.group(1)}] {t}"
                fixed += 1
                continue
        if not _TRUNCATED.search(t):
            continue
        page = (rawstore.load(it.get("id")) or {}).get("page") or ""
        if not page:
            continue
        stem = _TRUNCATED.sub("", t).strip()
        if len(stem) < 8:
            continue
        page1 = re.sub(r"\s+", " ", page)
        i = page1.find(stem)
        if i < 0:
            continue
        end = len(page1)
        for w in _TITLE_TAIL:                      # 제목 뒤에 오는 표의 다음 칸에서 끊는다
            j = page1.find(w, i + len(stem))
            if j > 0:
                end = min(end, j)
        full = page1[i:min(end, i + len(stem) + 40)].strip()
        if len(full) > len(stem) + 1:
            it["title"] = compact_title(music_only_title(full))
            it["title"] = school_title(it["title"], it.get("org"))
            fixed += 1
    if fixed:
        log(f"잘린 제목 복원 {fixed}건")
    return fixed


def _drop_reposts(items):
    """같은 기관이 같은 제목으로 여러 번 올린 재공고는 최신 것만 남긴다.

    학교들은 사람이 안 구해지면 같은 공고를 다시 올린다. 게시글 번호가 달라 URL도 id도
    달라서 기존 중복 제거로는 안 걸린다 — 함양제일고 관악부 강사 채용이 4월분·5월분
    두 건으로 나란히 떠 있었다 (2026-08-08 버그 브리핑).
    지원자에게는 같은 자리 하나이므로 최신 회차만 남기는 게 맞다.
    """
    # 같은 자리인데 제목 끝에 마감 표기만 다르게 붙은 경우가 있다 — 천안시립교향악단
    # 예술감독 공고가 '…모집' 과 '…모집(~8/14)' 두 건으로 떴다(하나는 대학 게시판 경유).
    # 비교할 때는 그 표기와 공백을 지운 뒤 견준다 (2026-08-08).
    def _key_title(t):
        t = re.sub(r"[(（]\s*[~∼]\s*[\d./]+\s*[)）]", "", t or "")
        return re.sub(r"\s+", "", t)

    best = {}
    for it in items:
        k = ((it.get("org") or "").strip(), _key_title(it.get("title")))
        cur = best.get(k)
        if cur is None or (it.get("date") or "") > (cur.get("date") or ""):
            best[k] = it
    keep = set(id(v) for v in best.values())
    dropped = [i for i in items if id(i) not in keep]
    if dropped:
        items[:] = [i for i in items if id(i) in keep]
        log(f"재공고 중복 {len(dropped)}건 정리 — "
            + "; ".join(f"{i.get('org')}/{i['title'][:20]}" for i in dropped[:3]))
    return dropped


def _drop_expired(items, today):
    """접수가 끝난 공고를 내린다 — ① 아는 마감일이 지났거나 ② 원문에 지난 마감이 확정 표기된 것.

    마감일을 못 뽑은 공고는 화면에 '기한 미정'으로 남는데, 그중 상당수는 마감일이 없는 게
    아니라 **이미 끝난** 것이었다 — 2026-08-07 점검에서 게시중 95건 중 51건이 그랬고
    제목에 '(마감)'이 박힌 것, 1년도 더 지난 2025-04 공고까지 섞여 있었다.
    _refill_from_raw 가 '지난 날짜는 앉히지 않는다'로 버린 뒤 아무도 줍지 않은 자리다.

    오탐이 곧 살아있는 공고 삭제라 근거를 겹으로 조인다:
     ⓪ 게시판이 스스로 '접수상태: 마감'이라 적어 뒀으면 그게 제일 확실하다 — 날짜를 캘 것도 없다.
     ① '원서접수·접수기간·남은기간' 같은 확정 어휘 윈도에서 나온 날짜만 본다(폴백 금지).
     ② 후보들이 한 달 넘게 흩어져 있으면 남의 공고 목록이 섞인 것으로 보고 보류한다.
     ③ 자기 게시일보다 이른 마감일은 남의 날짜다 — 보류.
    보류한 것은 종전대로 '기한 미정'으로 남으니, 판단이 서지 않을 때의 기본값은 '그대로 둠'이다.
    """
    gone = []
    for it in items:
        if it.get("deadlineNote") == "상시":
            continue
        raw = rawstore.all_text(it.get("id"))
        # ⓪ 게시판이 스스로 붙인 상태값. 경남교육청은 상세에 '채용상태 마감', 목록에
        # '접수상태 접수중/접수전/마감'을 적어 둔다 — 우리 날짜 추출보다 이쪽이 정확하다.
        # 실제로 화정초·경남관광고는 우리가 2027-02-28 같은 엉뚱한 마감일을 붙여 뒀는데
        # 게시판은 진작 '마감'이었다 (2026-08-08 버그 브리핑).
        if raw and _BOARD_CLOSED.search(raw):
            it["expiredOn"] = it.get("deadline") or "게시판:마감"
            gone.append(it)
            continue
        # 이미 마감일을 아는데 그게 지났으면 그대로 내린다. 소스별 수집 구간에도 같은 필터가
        # 있지만 거긴 승계 경로가 비켜 간다 — 양현고 시간강사 공고가 마감 7-29 인 채로
        # 8-07 화면에 남아 있었다 (2026-08-07).
        if it.get("deadline"):
            if it["deadline"] < today.isoformat():
                it["expiredOn"] = it["deadline"]
                gone.append(it)
            continue
        # 여기서도 첨부 공고문이 먼저다. 본문에는 남의 공고 날짜가 섞여 후보가 흩어지고,
        # 그러면 '판단 보류'로 빠져 끝난 공고가 계속 남는다.
        cands = _raw_deadlines(it)
        # 후보 개수로 가르던 것을 '흩어진 정도'로 바꾼다. 같은 공고가 접수기간·서류마감처럼
        # 며칠 사이 날짜를 여럿 갖는 건 정상인데, 개수만 세면 그런 멀쩡한 공고까지 보류됐다
        # (조선대여중은 6-25·26·29 세 개가 전부 같은 공고의 날짜였다).
        # 반대로 군산시립교향악단 상세엔 시청 채용공고 목록이 통째로 딸려 와 2024~2026이
        # 뒤섞이는데, 그건 한 달 기준에서 확실히 걸린다.
        if not cands or _span_days(cands[0], cands[-1]) > 30:
            continue
        dl = max(cands)
        if dl >= today.isoformat():
            continue
        if _posted_date(it) and dl < _posted_date(it):
            continue
        it["expiredOn"] = dl
        gone.append(it)
    if gone:
        items[:] = [i for i in items if "expiredOn" not in i]
        log(f"접수 종료 확인 {len(gone)}건 제외 — "
            + "; ".join(f"{i['expiredOn']} {i['title'][:20]}" for i in gone[:5]))
    return gone


def _apply_overrides(items, verbose=False):
    """사람이 직접 확인한 사실(전화·메일 회신, 손수 찾은 원문 링크)을 크롤 결과 위에 덮어쓴다.
    crawler/overrides.json — URL 키라 제목이 바뀌어도 안정적이고, 공고가 내려가면 자동 무시된다."""
    ov_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overrides.json")
    if not os.path.exists(ov_path):
        return
    try:
        with open(ov_path, encoding="utf-8") as f:
            overrides = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
        n_ov = 0
        for it in items:
            ov = overrides.get(it.get("url")) or overrides.get(it.get("officialUrl") or "")
            if ov:
                it.update(ov)
                n_ov += 1
        if verbose and n_ov:
            log(f"확인정보 병합: {n_ov}건 (overrides.json)")
    except Exception as e:
        log(f"WARN overrides.json 병합 실패: {e}")


def _dl_hints(text):
    """마감 추출 실패 시 규칙 개선용 단서 — 기한 어휘 주변 문구를 최대 2개 발췌.

    deadline_misses.json에 쌓이는 이 발췌가 '왜 못 읽었나'를 보여준다: 새 날짜 표기가
    보이면 extract_deadline에 규칙을 추가하는 개선 루프의 입력이다 (미분류 큐와 같은 구조)."""
    hints = []
    for m in re.finditer(r"마감|접수|기한|까지|모집 ?기간|지원 ?기간|제출", text):
        s = text[max(0, m.start() - 40): m.start() + 50].strip()
        if re.search(r"\d", s) and all(s not in h and h not in s for h in hints):
            hints.append(s)
        if len(hints) >= 2:
            break
    return hints or None


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
        # 이전글·다음글 영역을 먼저 걷어낸다 — 이 soup는 본문 요약(_body_excerpt)에도 쓰이므로,
        # 안 지우면 다른 공고 제목이 요약에 실린다 (2026-08-04 연세대 사례)
        strip_navi(soup)
        # 본문 텍스트는 body_text로 뽑는다 — soup에서 헤더를 직접 지우면 본문을 <header>에
        # 넣는 사이트(대전교육청)의 내용을 통째로 날린다. soup 자체는 첨부·이미지 탐색에 계속 쓰므로 보존.
        page_text = body_text(r.text)
        # 원문 보관층: 페이지 본문을 txt로 저장 (추출기 개선 시 재추출의 원본 — rawstore.py)
        rawstore.stash(item.get("id"), "page", page_text, url=item.get("url"), title=item.get("title"))
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
                # 일부 CMS(부천 등)는 Referer 없으면 다운로드 거부. TLS 차단 호스트는 curl 우회
                fr = (curl_get(furl, referer=item["url"], timeout=30) if tls_blocked(furl)
                      else s.get(furl, timeout=30, verify=False, headers={"Referer": item["url"]}))
                if fr.status_code != 200 or not (200 < len(fr.content) < 20_000_000):
                    continue
                cd = fr.headers.get("Content-Disposition", "")
                m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
                name = m.group(1) if m else (fname or furl)
                atext = attach.extract_any(name, fr.content)
                rawstore.stash(item.get("id"), "attach", atext, name=name)
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
                    rawstore.stash(item.get("id"), "attach", otext, name=f"ocr:{src_url.rsplit('/', 1)[-1][:40]}")
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
                dl = extract_deadline(body_text(html), ref_year=ry)
                if dl:
                    item["deadline"] = dl
                    item["deadlineFrom"] = "page-js"
            except Exception:
                pass
        # 전 단계(본문→첨부→OCR→렌더)를 소진하고도 못 찾은 경우 — 단서만 채집해 둔다
        if not item.get("deadline") and not item.get("deadlineNote"):
            item["dlHint"] = _dl_hints(page_text)
        # (집계 포털 무마감 공고를 '상시'로 눕히던 기본값 제거 — 상시는 본문에
        #  '상시모집' 등이 명시된 경우에만 위에서 설정된다. 마감을 못 찾은 항목은
        #  게시일 기준 노후 정리 로직이 정직하게 처리한다.)
    except Exception:
        log(f"  enrich 실패 {item['url'][:60]}")

# ---------- 마감 미확인 추적 ----------
# '기한 확인필요'를 화면에 오래 두지 않기로 함 (2026-07-23): 크롤러가 매 회차 전 단계
# (본문→첨부→OCR→렌더)를 재시도하고, 3회차까지 못 찾으면 텔레그램으로 사용자에게 보고한다
# (사용자가 직접 확인하거나 기관에 문의). dlHint 발췌는 추출 규칙 보강 재료.
def track_deadline_misses(final):
    miss_path = os.path.join(BASE, "data", "deadline_misses.json")
    prev = {}
    try:
        with open(miss_path, encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        pass
    today = date.today().isoformat()
    cur = {}
    for it in final:
        # 교회(상시 포지션)·상시모집·마감 확보 항목은 추적 대상이 아니다
        if it.get("deadline") or it.get("deadlineNote") == "상시" or it.get("obri"):
            continue
        url = it.get("officialUrl") or it.get("url")
        e = prev.get(url) or {"firstSeen": today, "tries": 0, "reported": False}
        if e.get("lastTry") != today:      # 하루 여러 번 돌아도 1회차로 센다
            e["tries"] = e.get("tries", 0) + 1
            e["lastTry"] = today
        e["title"], e["org"] = it.get("title"), it.get("org")
        if it.get("dlHint"):
            e["hint"] = it["dlHint"]
        cur[url] = e
    # 마감이 확보됐거나 내려간 공고는 큐에서 빠진다 — 이 파일은 캐시가 아니라 '미해결 큐'
    due = [(u, e) for u, e in cur.items() if e["tries"] >= 3 and not e.get("reported")]
    if due:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 번들 crawler/notify.py
            from notify import send
            lines = [f"· {e['org']} — {e['title'][:40]}\n  {u}" for u, e in due[:6]]
            send(f"[포디엄] 마감일을 3회차까지 못 찾은 공고 {len(due)}건 — "
                 f"직접 확인이나 기관 문의가 필요해요\n" + "\n".join(lines), silent=True)
            for _, e in due:
                e["reported"] = True
        except Exception:
            pass
    with open(miss_path, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    if cur:
        log(f"마감 미확인 {len(cur)}건 추적 중 (이번에 보고 {len(due)}건) → deadline_misses.json")


# 본문에 <img> 로 박힌 공고 이미지. 첨부 링크(find_attachments)만 찾던 탓에 이런 공고는
# 텍스트가 한 줄도 안 남았다 — 경북 도립예술단·통영 꿈의오케스트라가 그랬다 (2026-08-11).
# '이미지의 모든 텍스트를 데이터화한다'(사용자 지시)의 마지막 공백.
_IMG_CONTENT = re.compile(r"upload|editor|files|attach|data|bbs|smartupload", re.I)
_IMG_CHROME = re.compile(r"icon|logo|btn|banner|bullet|emoticon|blank|spacer|/_next/image", re.I)


def _find_content_images(soup, base_url, limit=3):
    from urllib.parse import urljoin
    out, seen = [], set()
    for im in soup.find_all("img"):
        src = im.get("src") or ""
        if not src or not _IMG_CONTENT.search(src) or _IMG_CHROME.search(src):
            continue
        full = urljoin(base_url, src)
        if full not in seen:
            seen.add(full)
            out.append(full)
        if len(out) >= limit:
            break
    return out


def _ensure_raw_attachments(final, cap=50):
    """원문 보관층 보완 패스 — 첨부를 아직 저장하지 못한 공고를 한 번씩 마저 긁는다.

    enrich_deadline은 마감일이 페이지에서 바로 나오면 첨부를 열지 않고 돌아간다(효율).
    그 결과 악기·파트가 첨부 공고표에만 있는 공고(대전시향 '예능단원')는 원문 보관층에
    첨부가 안 쌓이고 악기 미상으로 남는다. 여기서 전 공고의 본문+첨부를 빠짐없이 저장한다.

    저장은 불변 누적이라 공고당 평생 한 번이다 — tried 마커(rawstore.RETRY_DAYS)로
    실패 재시도도 며칠에 한 번으로 묶는다. cap은 크롤 시간 방어(며칠에 걸쳐 수렴).
    """
    todo = [it for it in final
            if it.get("id") and it.get("url")
            and it.get("source") != "hibrain.net"           # 로그인 게이트 — 익명 재방문 무의미
            # 첨부가 하나라도 있으면 통과시키던 것을 고친다. 첨부가 여럿인 공고에서 우리가
            # 첫 파일만 받아 둔 경우가 있는데, 하필 그게 응시원서 서식이면 마감일이 든
            # 공고문을 영영 못 연다 — 통영시립소년소녀합창단이 그랬다 (2026-08-09).
            # 그래서 '마감을 아직 모르는 공고'는 첨부가 있어도 한 번 더 들러 나머지를 받는다.
            and (not rawstore.has_attach(it["id"])
                 or (not it.get("deadline") and it.get("deadlineNote") != "상시"))
            and not rawstore.tried_recently(it["id"])]
    if not todo:
        return 0
    s = new_session()
    done = 0
    for it in todo[:cap]:
        iid = it["id"]
        try:
            r = get(s, it["url"])
            if r.status_code != 200:
                rawstore.mark_tried(iid)
                continue
            rawstore.stash(iid, "page", body_text(r.text), url=it["url"], title=it.get("title"))
            atts = []
            for parser in ("lxml", "html.parser"):   # 대형 페이지 lxml 앵커 누락 폴백
                atts = find_attachments(BeautifulSoup(r.text, parser), r.url)
                if atts:
                    break
            for furl, fname in atts[:rawstore.MAX_ATTACH]:
                try:
                    fr = (curl_get(furl, referer=it["url"], timeout=30) if tls_blocked(furl)
                          else s.get(furl, timeout=30, verify=False, headers={"Referer": it["url"]}))
                    if fr.status_code != 200 or not (200 < len(fr.content) < 20_000_000):
                        continue
                    cd = fr.headers.get("Content-Disposition", "")
                    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
                    name = m.group(1) if m else (fname or furl)
                    rawstore.stash(iid, "attach", attach.extract_any(name, fr.content), name=name)
                except Exception:
                    continue
            # 본문에 <img> 로 박힌 공고 이미지도 OCR 한다 — 첨부 링크가 없는 이미지 공고는
            # 이 경로가 유일한 텍스트화 기회다. OCR 비용 때문에 공고당 2장으로 묶는다.
            try:
                for imurl in _find_content_images(BeautifulSoup(r.text, "lxml"), r.url, limit=2):
                    try:
                        fr = (curl_get(imurl, referer=it["url"], timeout=30) if tls_blocked(imurl)
                              else s.get(imurl, timeout=30, verify=False, headers={"Referer": it["url"]}))
                        if fr.status_code == 200 and 2_000 < len(fr.content) < 20_000_000:
                            name = "img:" + imurl.rsplit("/", 1)[-1][:40]
                            rawstore.stash(iid, "attach", attach.extract_any(name + ".png", fr.content), name=name)
                    except Exception:
                        continue
            except Exception:
                pass
            rawstore.mark_tried(iid)
            done += 1
        except Exception:
            rawstore.mark_tried(iid)
    if len(todo) > cap:
        log(f"원문 보관: 이번 회차 {cap}건까지 — 남은 {len(todo) - cap}건은 다음 크롤에서")
    return done


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
                       and not it.get("nonMusic")
                       and musician_relevant(it["title"], it.get("kind", "기타"), it.get("org", ""))]
            for it in carried:
                it["channel"] = src["id"]
                it["layer"] = src["layer"]
                it.pop("extVer", None)      # 재파싱을 안 했으므로 추출 인증을 지운다(아래 주석)
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
                if it.get("nonMusic") or not musician_relevant(it["title"], it["kind"], it.get("org", "")):
                    continue   # nonMusic: 원제목 기준 음악 곁다리 판정 (make_item에서 세팅)
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
                    # 승계 항목은 이번 회차에 파싱하지 않았다. 그런데 마지막에 모든 항목이
                    # extVer 도장을 받으므로, 그대로 두면 '최신 추출기로 뽑은 값'으로 인증돼
                    # 다음 회차의 재추출 대상에서도 빠진다 — 강원교육청 페이가 「공무원보수규정」
                    # 인용문인 채로 버틴 이유다 (2026-08-09). 도장을 지워 재추출 대상으로 남긴다.
                    for it in carried:
                        it.pop("extVer", None)
                    log(f"WARN {src['name']}: 0건 반환 — 이전 {len(carried)}건 승계 (서버 장애 추정)")
            all_items.extend(kept)
            source_stats.append({**meta, "ok": True, "raw": len(raw), "kept": len(kept)})
            log(f"OK  {src['name']}: 원본 {len(raw)}건 → 수집 {len(kept)}건")
        except Exception as e:
            # 파서가 죽어도 그 기관 공고를 사이트에서 사라지게 두지 않는다 — 0건 반환과 같은
            # 논리로 이전 수집분을 승계한다. (2026-07-27 대구문화예술회관 ReadTimeout 사고:
            # 서버 딸꾹질 한 번에 해당 기관 공고가 통째로 목록에서 빠졌다. 만료된 건은
            # 뒤의 마감·노후 정리 단계가 어차피 걸러내므로 승계가 유령 공고를 만들지 않는다.)
            carried = [it for it in prev_items if it.get("channel") == src["id"]]
            if carried:
                for it in carried:
                    it.pop("extVer", None)      # 파싱을 못 했으므로 추출 인증도 없다
                all_items.extend(carried)
            source_stats.append({**meta, "ok": False, "kept": len(carried),
                                 "error": f"{type(e).__name__}: {str(e)[:120]}"})
            log(f"FAIL {src['name']}: {type(e).__name__}: {str(e)[:120]}"
                + (f" — 이전 {len(carried)}건 승계" if carried else ""))
            traceback.print_exc()

    # id 중복 제거 → canonical dedup → firstSeen
    seen, uniq = set(), []
    for it in all_items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)
    final = dedup(uniq)
    # 승계 경로로 들어온 항목까지 포함해 음악인 대상 필터를 최종 일괄 적용.
    # youth_member 도 여기서 다시 본다 — relevant()는 수집 시점에만 도는데, 이미 실려 있던
    # 공고는 승계로 들어와 그 관문을 통과하지 않는다. 규칙을 새로 넣은 날 기존 분이 그대로
    # 남는 이유가 이것이다 (구리시립청소년교향악단, 2026-08-07).
    final = [i for i in final if not i.get("nonMusic")
             and not youth_member(i["title"]) and not participant_only(i["title"])
             and musician_relevant(i["title"], i.get("kind", ""), i.get("org", ""))]
    # 대학 전체 강사 초빙 중 첨부 확인 결과 음악 교과목이 전혀 없던 공고는 제외(비음악 확정)
    final = [i for i in final if not i.get("nonMusic")]
    # 승계로 들어온 옛 값을 먼저 비운다 — 안 그러면 아래 재추출이 '이미 값이 있다'며 건너뛴다
    n_stale = _reset_stale_extracted(final)
    if n_stale:
        log(f"낡은 추출값 초기화 {n_stale}건 (추출기 v{EXT_VER})")
    _refill_from_raw(final, today)
    # 새로 들어온 공고의 기관 위치를 이번 회차에 바로 찾는다. Nominatim 예의상 초당 1건이라
    # 회차당 12곳으로 묶는다(≈13초) — 못 찾은 곳은 다음 크롤에서 이어 찾는다.
    try:
        import geocode_jobs
        n_new = geocode_jobs.run(limit=12, verbose=False, items=final)
        if n_new:
            log(f"기관 위치 새로 조회 {n_new}곳")
    except Exception as e:
        log(f"WARN 위치 조회 건너뜀: {type(e).__name__}: {e}")
    # 몸통 기반 아동 판정 — 자격 칸이 '재학 중인 학생'이면 단원 모집은 참여지 채용이 아니다.
    # 제목 규칙은 여기(자격 추출) 뒤에야 판단 재료가 생기므로 이 자리에서 거른다.
    _kids = [it for it in final
             if it.get("kind") == "단원" and student_target(it.get("qualification"), it.get("ageLimit"))]
    if _kids:
        final[:] = [it for it in final if it not in _kids]
        log(f"학생 대상 단원 모집 {len(_kids)}건 제외 — "
            + "; ".join(i["title"][:24] for i in _kids[:3]))
    # 기관 칩엔 학교명만 — '(서울시교육청)' 접미는 소속 필드로 분리(출처와 중복, 워크오더 D11)
    for it in final:
        m_a = re.match(r"^(.+?)\s*\(([^()]*교육청[^()]*)\)$", it.get("org") or "")
        if m_a:
            it["org"], it["orgAffil"] = m_a.group(1).strip(), m_a.group(2).strip()
    # 무용 단체의 단원 모집은 무용수 자리 — 제외 (워크오더 E14)
    _dance = [it for it in final if dance_member(it.get("title", ""), it.get("org", ""))]
    if _dance:
        final[:] = [it for it in final if it not in _dance]
        log(f"무용수 모집 {len(_dance)}건 제외 — " + "; ".join(i["title"][:22] for i in _dance[:3]))
    _qc_fields(final)          # 수상한 값은 화면에 나가기 전에 우리가 먼저 거른다
    n_geo = _attach_coords(final)
    if n_geo:
        log(f"기관 이름으로 찾은 위치 {n_geo}건 연결")
    _repair_titles(final)
    # 게시판 주인이 아니라 실제 뽑는 기관을 org로. overrides 앞에 두어 사람이 손수 넣은
    # 기관명이 있으면 그쪽이 최종적으로 이기게 한다.
    _fix_org_from_title(final)
    # 사람이 찾아 넣은 사실(overrides.json)을 **지원경로 판정 전에** 먼저 얹는다.
    # 순서가 반대면, 원문 링크를 손수 찾아 넣어도 그 공고가 이미 제외된 뒤라 되살아나지
    # 못한다 — 천안시립교향악단이 실제로 그랬다 (2026-08-02). 아래 최종 단계에서 한 번 더
    # 병합하는 것은 그대로 둔다(그때는 분류 재적용 뒤 값을 덮어쓰는 게 목적).
    _apply_overrides(final)
    # 마감이 지난 게 원문에 확정 표기된 공고를 내린다. overrides 뒤에 두는 이유는,
    # 사람이 손수 넣은 마감일이 있으면 그쪽이 우선이고 여기 판정은 아예 건너뛰기 때문이다.
    _drop_expired(final, today)
    _drop_reposts(final)
    # 마감 미상 + 게시일 미상 공고는 첫 관측일 기준 60일에서 내린다 — date 가 없으면 120일
    # 규칙을 영영 비켜 가 영생했다(서울발레시어터, 워크오더 E15)
    _cut60 = (today - timedelta(days=60)).isoformat()
    _aged = [i for i in final
             if not i.get("deadline") and i.get("deadlineNote") != "상시" and not i.get("obri")
             and not i.get("date") and (i.get("firstSeen") or "9999") < _cut60]
    if _aged:
        final[:] = [i for i in final if i not in _aged]
        log(f"게시일 미상·60일 경과 {len(_aged)}건 정리 — " + "; ".join(i["title"][:20] for i in _aged[:3]))
    # 지원할 방법이 하나도 없는 공고는 싣지 않는다 — 집계 포털에서 왔는데 기관 원문도,
    # 이메일·전화도 못 뽑은 경우다. 포털로는 링크를 내지 않기로 했으므로(CLAUDE.md) 카드에
    # '기관명으로 검색하세요'라는 빈 안내만 남아 사용자가 할 수 있는 게 없다 (2026-07-29 지적).
    # 조용히 버리지 않고 로그로 남긴다 — 연락처 추출 규칙을 보강할 재료다.
    _portal_src = AGGREGATORS + ("hibrain.net",)   # 링크를 내보내지 않기로 한 집계 포털들
    _dead_end = [i for i in final
                 if (i.get("source") or "") in _portal_src
                 and not i.get("officialUrl") and not i.get("applyEmail") and not i.get("applyPhone")]
    if _dead_end:
        final = [i for i in final if i not in _dead_end]
        log(f"지원경로 없음 {len(_dead_end)}건 제외 — "
            + "; ".join(f"{i.get('org')}/{i['title'][:22]}" for i in _dead_end[:5]))
    # 원본이 삭제된 공고 제거 — 헬스체크(health_check.py)가 2회 연속 404/410으로
    # 확인한 링크 + 묘비(tombstone)에 새겨진 링크를 거른다.
    #
    # 묘비가 필요한 이유(2026-07-18 규명): 헬스체크는 official.json 에 없는 URL 의
    # streak 을 청소하는데(무한 증식 방지), 우리가 여기서 제거한 URL 이 정확히 그
    # 경우다. cjob 처럼 삭제글이 소스 목록에 계속 남는 곳은 다음 크롤에 재수집되고,
    # streak 이 0부터 다시 쌓여 이틀 뒤 또 제거… 를 반복하며 헬스 알림이 이틀마다
    # 울린다. 그래서 한 번 확정된 죽음은 data/dead_tombstones.json 에 새겨 재수집을
    # 계속 막는다. 묘비는 120일 뒤 소멸 — 같은 URL 로 진짜 새 공고가 올라오는 드문
    # 경우의 안전판(무마감 공고 정리 기준 120일과 같은 지평선).
    hist_path = os.path.join(BASE, "data", "health_history.json")
    tomb_path = os.path.join(BASE, "data", "dead_tombstones.json")
    try:
        with open(hist_path, encoding="utf-8") as f:
            _dead = {u for u, s in (json.load(f).get("deadLinks") or {}).items()
                     if s.get("n", 0) >= 2}
    except (FileNotFoundError, json.JSONDecodeError):
        _dead = set()
    try:
        with open(tomb_path, encoding="utf-8") as f:
            tombs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        tombs = {}
    tombs = {u: t for u, t in tombs.items()
             if (today - date.fromisoformat(t["since"])).days <= 120}
    _dead |= set(tombs)
    if _dead:
        gone = [i for i in final if i.get("url") in _dead]
        final = [i for i in final if i.get("url") not in _dead]
        for g in gone:
            u = g.get("url")
            if u not in tombs:
                tombs[u] = {"since": today.isoformat(), "org": g.get("org"),
                            "title": (g.get("title") or "")[:60]}
            log(f"DROP 원본 삭제(연속 404): {g.get('org')} / {(g.get('title') or '')[:40]}")
    with open(tomb_path, "w", encoding="utf-8") as f:
        json.dump(tombs, f, ensure_ascii=False, indent=1)
    # 원문 보관층 보완 — 전 공고의 본문+첨부를 txt로 확보 (공고당 평생 한 번)
    try:
        n_raw = _ensure_raw_attachments(final)
        if n_raw:
            log(f"원문 보관: {n_raw}건 본문+첨부 수집")
            # 방금 받아 온 공고문을 이번 회차에 바로 쓴다. 이 보완 패스가 마감 추출보다
            # 뒤에 있어서, 예전엔 새로 받은 첨부가 다음 크롤에서야 반영됐다 — 통영
            # 합창지도자는 공고문 PDF를 받고도 하루를 더 '기한 미정'으로 있었다 (2026-08-09).
            _refill_from_raw(final, today)
            # ★ 재추출이 검수(1804) 뒤에 한 번 더 돌므로, 여기서 걸러낸 값이 도로 채워진다.
            #   상일미디어고 자격('여부, 학력사항…')이 검수 규칙이 있는데도 살아남은 이유다
            #   (2026-08-12). 늦은 재추출 뒤에는 반드시 검수도 다시 돈다.
            _qc_fields(final)
            gone_late = _drop_expired(final, today)
            if gone_late:
                log(f"  └ 새로 받은 공고문으로 {len(gone_late)}건 추가 정리")
    except Exception as e:
        log(f"WARN 원문 보관 실패: {type(e).__name__}: {e}")
    for it in final:
        old = prev_by_id.get(it["id"])
        it["firstSeen"] = old.get("firstSeen", today.isoformat()) if old else today.isoformat()
        # NEW: 게시 시작 기준 '만 48시간' = 게시일 당일 + 다음 날까지 (2026-07-27 사용자:
        # 3일은 NEW가 너무 많음). 기준은 게시일(date), 모르면 firstSeen 폴백 — firstSeen만
        # 쓰면 파서를 고친 날 옛 공고가 전부 NEW로 뜬다(work.sen 12건 사고).
        # 프론트 isFresh(jobs.js)·staticgen._is_fresh와 같은 규칙 — 셋이 어긋나면 안 된다.
        _basis = it.get("date") or it["firstSeen"]
        try:
            it["isNew"] = 0 <= (today - date.fromisoformat(_basis)).days <= 1
        except ValueError:
            it["isNew"] = (today - date.fromisoformat(it["firstSeen"])).days <= 1
        it["extVer"] = EXT_VER
        # 제목 기반 분류(kind/tier/ageGroup)는 순수 함수 — 승계 항목도 최신 로직으로 재적용
        # (서버 장애로 원본 0건 승계된 항목이 옛 분류를 물고 오는 것 방지)
        it["ageGroup"] = age_group(it["title"], it.get("org", ""))
        it["kind"] = classify_kind(it["title"])
        it["tier"] = classify_tier(it["title"], it.get("org", ""))   # 등급 최신 로직 재적용
        it["obri"] = is_obri(it["title"], it.get("org", ""))
        # 제목 정리도 순수 함수 — 압축 규칙(compact_title)을 승계 항목에 최신 로직으로 재적용
        it["title"] = compact_title(music_only_title(it["title"]))
        # 학교 약칭도 여기서 함께 재적용한다 — 승계로 들어온 항목은 수집 시점의 규칙만
        # 거쳤으므로, 이걸 빼면 규칙을 새로 넣은 날 기존 분이 옛 제목으로 남는다.
        it["title"] = school_title(it["title"], it.get("org"))
        # 자격 필드 — 본문(자격·요약)까지 반영해 정확도 향상
        qtext = " ".join(str(it.get(f, "") or "") for f in ("title", "qualification", "bodyExcerpt", "recruitSummary"))
        it["certReq"] = cert_required(it["tier"], it["title"], qtext)
        it["degreeReq"] = degree_req(qtext)
        it["careerReq"] = career_req(qtext)
        if it["kind"] == "교수" and not it.get("subject"):
            subj = find_subject(it["title"])
            if subj:
                it["subject"] = subj
        # 악기 재추출 — 원문 보관층(txt) 위에서 매 크롤 최신 추출기로 다시 뽑는다.
        # 승계(extVer) 경로와 무관하게 자기치유되므로, 추출기를 고치면 다음 크롤에서
        # 과거 저장분까지 소급 적용된다 (이 구조가 없어서 미상 161건이 회복 불가였다).
        if not it.get("instDetails"):
            _merge_insts(it, *insts_from_recruit_text(rawstore.all_text(it["id"])))
    # 제외 규칙은 소스 파싱 때만 걸린다 — 규칙을 새로 넣어도(수시모집 등 입시 공지)
    # 이미 수집·승계된 항목이 살아남는 문제 방지: 최신 EXCLUDE를 전체에 재적용
    n0 = len(final)
    final = [it for it in final if not EXCLUDE.search(it["title"])]
    if len(final) != n0:
        log(f"제외 규칙 재적용: {n0 - len(final)}건 정리")
    n_unclass = sum(1 for it in final if it["tier"] == "미분류")
    if n_unclass:
        log(f"미분류 큐: {n_unclass}건 — {'; '.join(it['title'][:24] for it in final if it['tier'] == '미분류')}")
    _apply_overrides(final, verbose=True)
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

    # 원문 보관층 디스크 반영 — 크롤 중 stash된 본문·첨부 텍스트를 data/raw/에 병합 저장
    try:
        n_flushed = rawstore.flush()
        if n_flushed:
            log(f"원문 보관: {n_flushed}개 파일 저장/갱신 (data/raw/)")
    except Exception as e:
        log(f"WARN 원문 보관 저장 실패: {type(e).__name__}: {e}")

    # 아카이브 누적 — official.json 은 살아있는 공고만 남기므로 마감된 공고가 매일
    # 사라진다. 수요 지도(crawler/demand_map.py)의 원본이 되도록 여기 따로 쌓는다.
    try:
        import archive
        n_arc = archive.merge(BASE, final)
        log(f"아카이브: 신규 {n_arc}건 · 누적 {len(archive.load(BASE))}건")
    except Exception as e:
        log(f"WARN 아카이브 병합 실패: {type(e).__name__}: {e}")

    # 정적 렌더링 (검색 봇·JS 실패 대비) — 실패해도 크롤 자체는 성공으로 둔다
    try:
        import staticgen
        n_static = staticgen.generate(BASE)
        log(f"정적 생성: 공고 {n_static}건 (p/*.html, 목록 삽입, sitemap)")
    except Exception as e:
        log(f"WARN 정적 생성 실패: {type(e).__name__}: {e}")

    coverage_report(final, today)
    n_minor = sum(1 for it in final if it.get("ageGroup") == "미성년")
    log(f"연령 분포: 성인 {len(final) - n_minor} / 미성년 {n_minor}"
        + (f" → 미성년 공고: {'; '.join(it['title'][:30] for it in final if it.get('ageGroup') == '미성년')}" if n_minor else ""))
    log(f"완료: {len(final)}건 저장 (dedup 전 {len(uniq)}건) → {OUT}")

    track_deadline_misses(final)

    # ---------- 안전장치: 소스 장애 텔레그램 알림 ----------
    # 실패(예외) 소스 + 0건 반환으로 승계된 소스를 요약해 알림 (정상이면 조용)
    fails = [x for x in source_stats if not x.get("ok")]
    if fails:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 번들 crawler/notify.py
            from notify import send
            lines = [f"· {x['name']}: {x.get('error', '?')[:60]}" for x in fails[:8]]
            send(f"[포디엄] 크롤 소스 {len(fails)}곳 실패 "
                 f"(전체 {len(SOURCES)}곳, 수집 {len(final)}건)\n" + "\n".join(lines),
                 silent=True)
        except Exception:
            pass

if __name__ == "__main__":
    run(force_all="--all" in sys.argv)
