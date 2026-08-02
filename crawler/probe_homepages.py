# URL 발굴 3단계 — 후보 URL을 생성해 실접속으로 검증하는 프로버.
#
# 지방문화원 229곳은 도메인 패턴이 강하다(한국문화원연합회 {로마자}.kccf.or.kr — 종로문화원
# jongno.kccf.or.kr 로 검증됨 2026-08-02). 여기에 {로마자}culture.or.kr 류 변형을 더해
# 후보를 만들고, 실제로 열어 "문화원"+지역명이 페이지에 있는지 확인한 것만 채택한다.
# 그 외 백로그(교육청·천주교 교구·대형교회 등)는 아는 후보를 수록해 같은 검증을 태운다.
#
# 검증을 통과한 것만 data/fullsweep/probed_homepages.json 에 저장(병합) →
# fill_urls.py 가 institutions.csv 에 채운다. 빗나간 것은 misses 로 남아 웹 검색 대상.
#
#   python crawler/probe_homepages.py            # 전체
#   python crawler/probe_homepages.py --limit 20
import csv
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import urllib3
urllib3.disable_warnings()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import curl_get  # noqa: E402

CSV = os.path.join(BASE, "crawler", "institutions.csv")
OUT = os.path.join(BASE, "data", "fullsweep", "probed_homepages.json")

# 표준 로마자(RR) — 문화원 이름의 지역 토큰용
ROMAN = {
    "종로": "jongno", "중구": "junggu", "용산": "yongsan", "성동": "seongdong", "광진": "gwangjin",
    "동대문": "dongdaemun", "중랑": "jungnang", "성북": "seongbuk", "강북": "gangbuk", "도봉": "dobong",
    "노원": "nowon", "은평": "eunpyeong", "서대문": "seodaemun", "마포": "mapo", "양천": "yangcheon",
    "강서": "gangseo", "구로": "guro", "금천": "geumcheon", "영등포": "yeongdeungpo", "동작": "dongjak",
    "관악": "gwanak", "서초": "seocho", "강남": "gangnam", "송파": "songpa", "강동": "gangdong",
    "부산진": "busanjin", "동래": "dongnae", "영도": "yeongdo", "서구": "seogu", "동구": "donggu",
    "남구": "namgu", "북구": "bukgu", "해운대": "haeundae", "사하": "saha", "금정": "geumjeong",
    "연제": "yeonje", "수영": "suyeong", "사상": "sasang", "기장": "gijang",
    "수성": "suseong", "달서": "dalseo", "달성": "dalseong", "군위": "gunwi",
    "미추홀": "michuhol", "연수": "yeonsu", "남동": "namdong", "부평": "bupyeong", "계양": "gyeyang",
    "강화": "ganghwa", "옹진": "ongjin", "광산": "gwangsan", "유성": "yuseong", "대덕": "daedeok",
    "울주": "ulju", "세종": "sejong",
    "수원": "suwon", "성남": "seongnam", "의정부": "uijeongbu", "안양": "anyang", "부천": "bucheon",
    "광명": "gwangmyeong", "평택": "pyeongtaek", "동두천": "dongducheon", "안산": "ansan",
    "고양": "goyang", "과천": "gwacheon", "구리": "guri", "남양주": "namyangju", "오산": "osan",
    "시흥": "siheung", "군포": "gunpo", "의왕": "uiwang", "하남": "hanam", "용인": "yongin",
    "파주": "paju", "이천": "icheon", "안성": "anseong", "김포": "gimpo", "화성": "hwaseong",
    "광주": "gwangju", "양주": "yangju", "포천": "pocheon", "여주": "yeoju", "연천": "yeoncheon",
    "가평": "gapyeong", "양평": "yangpyeong",
    "춘천": "chuncheon", "원주": "wonju", "강릉": "gangneung", "동해": "donghae", "태백": "taebaek",
    "속초": "sokcho", "삼척": "samcheok", "홍천": "hongcheon", "횡성": "hoengseong", "영월": "yeongwol",
    "평창": "pyeongchang", "정선": "jeongseon", "철원": "cheorwon", "화천": "hwacheon", "양구": "yanggu",
    "인제": "inje", "고성": "goseong", "양양": "yangyang",
    "청주": "cheongju", "충주": "chungju", "제천": "jecheon", "보은": "boeun", "옥천": "okcheon",
    "영동": "yeongdong", "증평": "jeungpyeong", "진천": "jincheon", "괴산": "goesan", "음성": "eumseong",
    "단양": "danyang",
    "천안": "cheonan", "공주": "gongju", "보령": "boryeong", "아산": "asan", "서산": "seosan",
    "논산": "nonsan", "계룡": "gyeryong", "당진": "dangjin", "금산": "geumsan", "부여": "buyeo",
    "서천": "seocheon", "청양": "cheongyang", "홍성": "hongseong", "예산": "yesan", "태안": "taean",
    "전주": "jeonju", "군산": "gunsan", "익산": "iksan", "정읍": "jeongeup", "남원": "namwon",
    "김제": "gimje", "완주": "wanju", "진안": "jinan", "무주": "muju", "장수": "jangsu",
    "임실": "imsil", "순창": "sunchang", "고창": "gochang", "부안": "buan",
    "목포": "mokpo", "여수": "yeosu", "순천": "suncheon", "나주": "naju", "광양": "gwangyang",
    "담양": "damyang", "곡성": "gokseong", "구례": "gurye", "고흥": "goheung", "보성": "boseong",
    "화순": "hwasun", "장흥": "jangheung", "강진": "gangjin", "해남": "haenam", "영암": "yeongam",
    "무안": "muan", "함평": "hampyeong", "영광": "yeonggwang", "장성": "jangseong", "완도": "wando",
    "진도": "jindo", "신안": "sinan",
    "포항": "pohang", "경주": "gyeongju", "김천": "gimcheon", "안동": "andong", "구미": "gumi",
    "영주": "yeongju", "영천": "yeongcheon", "상주": "sangju", "문경": "mungyeong", "경산": "gyeongsan",
    "의성": "uiseong", "청송": "cheongsong", "영양": "yeongyang", "영덕": "yeongdeok", "청도": "cheongdo",
    "고령": "goryeong", "성주": "seongju", "칠곡": "chilgok", "예천": "yecheon", "봉화": "bonghwa",
    "울진": "uljin", "울릉": "ulleung",
    "창원": "changwon", "진주": "jinju", "통영": "tongyeong", "사천": "sacheon", "김해": "gimhae",
    "밀양": "miryang", "거제": "geoje", "양산": "yangsan", "의령": "uiryeong", "함안": "haman",
    "창녕": "changnyeong", "남해": "namhae", "하동": "hadong", "산청": "sancheong", "함양": "hamyang",
    "거창": "geochang", "합천": "hapcheon", "제주시": "jeju", "서귀포": "seogwipo",
}
METRO = {"서울": "seoul", "부산": "busan", "대구": "daegu", "인천": "incheon",
         "광주": "gwangju", "대전": "daejeon", "울산": "ulsan", "강원": "gangwon", "경남": "gyeongnam"}

# 문화원 외 백로그 — 아는 후보 (전부 검증을 거친다; 키워드는 페이지에 있어야 하는 문자열)
KNOWN = {
    "서울시교육청": ("https://www.sen.go.kr", "교육"), "부산시교육청": ("https://www.pen.go.kr", "교육"),
    "대구시교육청": ("https://www.dge.go.kr", "교육"), "인천시교육청": ("https://www.ice.go.kr", "교육"),
    "광주시교육청": ("https://www.gen.go.kr", "교육"), "대전시교육청": ("https://www.dje.go.kr", "교육"),
    "울산시교육청": ("https://www.use.go.kr", "교육"), "세종시교육청": ("https://www.sje.go.kr", "교육"),
    "경기도교육청": ("https://www.goe.go.kr", "교육"), "강원도교육청": ("https://www.gwe.go.kr", "교육"),
    "충청북도교육청": ("https://www.cbe.go.kr", "교육"), "충청남도교육청": ("https://www.cne.go.kr", "교육"),
    "전북특별자치도교육청": ("https://www.jbe.go.kr", "교육"), "전라남도교육청": ("https://www.jne.go.kr", "교육"),
    "경상북도교육청": ("https://www.gbe.go.kr", "교육"), "경상남도교육청": ("https://www.gne.go.kr", "교육"),
    "제주도교육청": ("https://www.jje.go.kr", "교육"),
    "천주교 서울대교구": ("https://aos.catholic.or.kr", "교구"),
    "천주교 수원교구": ("https://www.casuwon.or.kr", "교구"),
    "천주교 인천교구": ("https://www.caincheon.or.kr", "교구"),
    "광림교회": ("https://www.kwanglim.or.kr", "광림"),
    "오륜교회": ("https://www.oryun.org", "오륜"),
    "주안장로교회": ("https://www.juan.or.kr", "주안"),
    "만나교회": ("https://www.manna.or.kr", "만나"),
    "충현교회": ("https://www.choonghyun.org", "충현"),
    "할렐루야교회": ("https://www.hcc.or.kr", "할렐루야"),
    "새에덴교회": ("https://www.saeeden.kr", "새에덴"),
    "국립현대무용단": ("https://www.kncdc.kr", "무용"),
    "국립정동극장": ("https://www.jeongdong.or.kr", "정동"),
    "서울돈화문국악당": ("https://www.sdtt.or.kr", "국악"),
    "부산콘서트홀": ("https://www.busanconcerthall.or.kr", "콘서트"),
    "제주아트센터": ("https://www.jejuartscenter.or.kr", "아트"),
    "제주도립제주교향악단": ("https://www.jejusi.go.kr", "교향"),
    "제주도립서귀포합창단": ("https://culture.seogwipo.go.kr", "합창"),
    "광명시립합창단": ("https://www.gm.go.kr", "합창"),
    "천안시립합창단": ("https://www.cheonan.go.kr", "천안"),
    "국립경찰교향악단": ("https://www.police.go.kr", ""),
    "김포문화재단": ("https://www.gcf.or.kr", "김포"),
    "파주문화재단": ("https://www.pajucf.or.kr", "파주"),
    "강릉문화재단": ("https://www.gncaf.or.kr", "강릉"),
    "시흥시청소년재단": ("https://www.shyouth.or.kr", "시흥"),
    "노원문화예술회관": ("https://www.nowonart.kr", "노원"),
    "구로아트밸리": ("https://www.gaac.or.kr", "구로"),
    "서울장신대학교": ("https://www.sjs.ac.kr", ""),
    "감리교신학대학교": ("https://www.mtu.ac.kr", ""),
    "서원대학교": ("https://www.seowon.ac.kr", ""),
    "예원예술대학교": ("https://www.yewon.ac.kr", ""),
    "경상국립대학교": ("https://www.gnu.ac.kr", ""),
    "대구예술대학교": ("https://www.dgau.ac.kr", ""),
}


def rows_backlog():
    out = []
    with open(CSV, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].lstrip().startswith("#") or row[0] == "기관명" or len(row) < 8:
                continue
            if row[7].strip() == "확정" and not row[4].strip().startswith("http"):
                out.append({"name": row[0], "cat": row[1], "sub": row[2], "region": row[3]})
    return out


def cw_candidates(name, region):
    """문화원 이름 → (지역토큰, [후보 URL...]). 광역 접두(서울종로문화원)는 떼고 로마자로."""
    core = re.sub(r"문화원$", "", name)
    for m in METRO:
        if core.startswith(m) and len(core) > len(m):
            core = core[len(m):]
            break
    r = ROMAN.get(core)
    if not r:
        return core, []
    cands = [f"http://{r}.kccf.or.kr", f"https://{r}.kccf.or.kr",
             f"http://www.{r}culture.or.kr", f"https://www.{r}culture.or.kr"]
    # 광역 구 단위는 도시 접두 하위도메인도 흔하다 (busanjunggu 등)
    for m, mr in METRO.items():
        if name.startswith(m) and core in ("중구", "서구", "동구", "남구", "북구", "강서"):
            cands.insert(2, f"http://{mr}{r}.kccf.or.kr")
    return core, cands


def verify(url, *keywords, timeout=10):
    """실접속 검증. requests 가 아니라 curl 을 쓴다 — 파이썬 TLS 지문을 막는 국내
    관공서 사이트가 있어서(창원 cwcf 사례) requests 만 보면 멀쩡한 곳도 실패로 샌다.

    판정: 200 + 최소 크기 + 키워드. 단 JS 리다이렉트 스텁(3KB 미만)은 키워드가 없는 게
    정상이라 크기만으로 통과시킨다 — 어차피 fullsweep 이 게시판을 못 찾으면 걸러진다.
    """
    try:
        r = curl_get(url, timeout=timeout)
        if r.status_code != 200 or len(r.content) < 400:
            return False
        text = r.text[:60_000]
        if len(r.content) < 3000:      # 스텁 — 본문이 JS로 로드됨
            return True
        return all(k in text for k in keywords if k)
    except Exception:
        return False


def probe_one(item):
    name, sub, region = item["name"], item["sub"], item["region"]
    if sub == "지방문화원":
        core, cands = cw_candidates(name, region)
        for u in cands:
            # 페이지에 '{지역}문화원'이 통째로 있어야 채택 — 동명 구(중구 등) 오연결 방지
            if verify(u, core + "문화원"):
                return name, u, "pattern"
        return name, None, "miss"
    if name in KNOWN:
        u, kw = KNOWN[name]
        if verify(u, kw):
            return name, u, "known"
        return name, None, "known_fail"
    return name, None, "no_candidate"


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    backlog = rows_backlog()
    if limit:
        backlog = backlog[:limit]
    print(f"백로그 {len(backlog)}곳 프로브 (병렬 12)")
    found, misses = {}, []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(probe_one, it): it for it in backlog}
        for i, fut in enumerate(as_completed(futs), 1):
            name, url, via = fut.result()
            if url:
                found[name] = {"url": url, "via": via}
                print(f"  [{i}/{len(backlog)}] ✔ {name} → {url}")
            else:
                misses.append({"name": name, "why": via, **{k: futs[fut][k] for k in ("cat", "sub", "region")}})
    # 병합 저장 — 기존 발견을 덮지 않는다
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        old = {"found": {}, "misses": []}
    old["found"].update(found)
    old["misses"] = misses          # misses 는 최신 상태가 진실 (found 로 옮겨간 것 제거)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, indent=1)
    print(f"\n발견 {len(found)} · 실패 {len(misses)} · {time.time() - t0:.0f}초")
    print(f"저장: data/fullsweep/probed_homepages.json — fill_urls.py 가 시드와 함께 사용")
    from collections import Counter
    print("실패 사유:", Counter(m["why"] for m in misses).most_common())
    return 0


if __name__ == "__main__":
    sys.exit(main())
