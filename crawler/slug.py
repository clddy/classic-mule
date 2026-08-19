# 공고 상세 URL 슬러그 — /p/{지역}-{악기·전공}-{기관축약}-{id8}.html
#
# 왜 바꾸나(작업 B, 2026-08-20): 기존 /p/{sha1-16}.html 은 사람도 검색엔진도 읽을 수 없다.
# 상세 28건이 전부 미색인이고 일 방문이 10명일 때가 URL 을 바꿀 수 있는 마지막 시점이다.
#
# 사전 우선순위는 **유량(flow) 분포**를 따른다 — 아카이브 전체 분포를 쓰면 8월 소급수집분
# (cjob 692건)이 상위를 점령해 '피아노·반주' 중심 사전이 만들어진다. 실제 유입은
# 학교·교육청 강사가 최상위다 (flowstats.py 참고).
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from romanize import slugify  # noqa: E402

# 16개 시도 — 고정 표 (common.REGION_ORDER 와 같은 어휘)
REGION = {
    "서울": "seoul", "부산": "busan", "대구": "daegu", "인천": "incheon",
    "대전": "daejeon", "울산": "ulsan", "세종": "sejong", "경기": "gyeonggi",
    "강원": "gangwon", "충북": "chungbuk", "충남": "chungnam", "전북": "jeonbuk",
    "광주·전남": "gwangju-jeonnam", "경북": "gyeongbuk", "경남": "gyeongnam", "제주": "jeju",
}
# 악기·전공 — 최근 90일 유량 상위부터 등재 (flowstats.distribution('instDetails'))
INST = {
    "바이올린": "violin", "지휘": "conductor", "피아노": "piano", "관악": "wind",
    "타악": "percussion", "첼로": "cello", "비올라": "viola", "바순": "bassoon",
    "클라리넷": "clarinet", "플루트": "flute", "플룻": "flute", "호른": "horn",
    "더블베이스": "doublebass", "콘트라베이스": "doublebass", "오보에": "oboe",
    "알토": "alto", "소프라노": "soprano", "테너": "tenor", "베이스": "bass",
    "성악": "vocal", "작곡": "composition", "반주": "accompanist", "오르간": "organ",
    "하프": "harp", "트럼펫": "trumpet", "트롬본": "trombone", "튜바": "tuba",
    "색소폰": "saxophone", "현악": "strings", "국악": "gugak", "합창": "choir",
}
# 직무 — 악기·전공이 없을 때 자리를 대신한다
KIND = {
    "강사": "gangsa", "교수": "professor", "단원": "member", "객원·대체": "guest",
    "직원": "staff", "지휘": "conductor", "반주": "accompanist", "교원": "teacher",
    "솔리스트": "soloist", "기타": "etc",
}
# 기관 유형 → 영문 약어. 기관이 스스로 쓰는 영문명을 따른다 —
# '서운중학교'의 공식 영문명은 Seoun Middle School 이므로 seoun-ms 가 되어야지,
# 한글을 그대로 굴린 seounjunghakgyo 가 되면 안 된다 (2026-08-20 사용자 지적).
_ORG_TYPE = [
    (r"여자중학교$", "gms"), (r"여자고등학교$", "ghs"),
    (r"예술고등학교$", "ahs"), (r"예술중학교$", "ams"),
    (r"초등학교$", "es"), (r"중학교$", "ms"), (r"고등학교$", "hs"),
    (r"특수학교$", "sps"), (r"유치원$", "kg"), (r"어린이집$", "dc"),
    (r"대학교$|대학$", "univ"), (r"대학원$", "grad"),
    (r"교향악단$|필하모닉$", "so"), (r"오케스트라$", "orch"),
    (r"합창단$", "choir"), (r"오페라단$", "opera"),
    (r"국악관현악단$|관현악단$", "orch"), (r"예술단$", "arts"),
    (r"문화재단$|문화관광재단$|문화예술재단$|예술재단$|재단$", "cf"),
    (r"문화회관$|예술회관$|아트센터$|아트홀$|예술의전당$|문화의전당$", "hall"),
    (r"교회$", "church"), (r"성당$", "cath"),
]
# ★ 기관이 스스로 쓰는 영문명이 최우선이다 (2026-08-20 사용자 지시).
# 자동 로마자 변환은 이 표에 없을 때만 쓰는 폴백이다. 새 기관이 반복해서 들어오면
# 그 기관 홈페이지·간판의 영문 표기를 확인해 여기 등재할 것 — 한 번 정하면 URL 로 굳는다.
_ORG_ALIAS = {
    "한국교원대학교": "knue", "예술의전당": "sac", "KBS교향악단": "kbs-so",
    "국립합창단": "nationalchorus", "국립오페라단": "nationalopera",
    "국립심포니오케스트라": "kns", "서울시립교향악단": "seoul-po",
    "한국예술종합학교": "karts", "세종문화회관": "sejongpac",
    "제물포문화재단": "jemulpo-cf", "종로문화재단": "jongno-cf",
    "부천필하모닉오케스트라": "bucheon-po", "대전시립교향악단": "daejeon-po",
    "광주광역시립교향악단": "gwangju-so", "울산시립합창단": "ulsan-choir",
    "국립극장": "ntok", "정동극장": "jeongdong",
}
# 슬러그 앞에 이미 지역이 붙으므로 기관명 머리의 지역 중복은 뗀다 (서울서운중 → seoun-ms)
_REGION_HEAD = re.compile(r"^(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
                          r"(?=[가-힣]{2,})")
_ORG_DROP = re.compile(r"\([^)]*\)|재단법인|사단법인|\(재\)|\(사\)|주식회사")


def org_short(org):
    """기관명 → (고유명, 유형약어). '서운중학교' → ('서운', 'ms')."""
    if not org:
        return "", ""
    t = _ORG_DROP.sub("", str(org)).strip()
    if t in _ORG_ALIAS:
        return _ORG_ALIAS[t], ""
    for pat, abbr in _ORG_TYPE:
        m = re.search(pat, t)
        if m:
            name = t[:m.start()].strip()
            name = _REGION_HEAD.sub("", name) or name
            return name, abbr
    return _REGION_HEAD.sub("", t) or t, ""


def build(item):
    """공고 → 슬러그 파일명(확장자 제외)."""
    region = REGION.get(item.get("region") or "", slugify(item.get("region"), 12))
    insts = item.get("instDetails") or []
    what = ""
    if insts:
        what = INST.get(insts[0], slugify(insts[0], 14, INST))
    if not what and item.get("subject"):
        what = slugify(re.sub(r"(?:학과|학부|전공|과)$", "", str(item["subject"]).split("·")[0]), 14, INST)
    if not what:
        what = KIND.get(item.get("kind") or "", slugify(item.get("kind"), 12, KIND))
    name, otype = org_short(item.get("org"))
    org = slugify(name, 16)
    if org and otype:
        org = f"{org}-{otype}"
    parts = [p for p in (region, what, org) if p]
    tail = (item.get("id") or "")[:8]
    return re.sub(r"-{2,}", "-", "-".join(parts + [tail])).strip("-").lower()
