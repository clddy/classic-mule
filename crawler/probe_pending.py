# 미부착 기관 게시판 목록 URL 자동 탐색
# 홈페이지 → 채용/모집/공고/오디션 링크 후보 수집 → 음악 공고 유무 판정
import re, sys
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from common import new_session, get

BOARD_HINT = re.compile(r"채용|모집|공고|오디션|구인|알림|공지|게시판|소식|recruit|notice|bbs|board")
MUSIC = re.compile(r"교향|합창|오케스트라|필하모닉|단원|연주|성악|반주|악기|오디션|예술단|바이올린|첼로|관현악|타악|성가")
JOBWORD = re.compile(r"모집|채용|초빙|공고|오디션|위촉|충원")

# (이름, 홈페이지, [추가 후보 URL])
TARGETS = [
    ("포항문화재단", "https://www.phcf.or.kr", []),
    ("원주시청", "https://www.wonju.go.kr", []),
    ("강릉시청", "https://www.gn.go.kr", []),
    ("진주시청", "https://www.jinju.go.kr", []),
    ("구미문화예술회관", "https://www.gumi.go.kr/gumiartcenter", []),
    ("목포시청", "https://www.mokpo.go.kr", []),
    ("여수시청", "https://www.yeosu.go.kr", []),
    ("익산시청", "https://www.iksan.go.kr", []),
    ("김천시청", "https://www.gimcheon.go.kr", []),
    ("과천시립예술단", "https://www.gcart.or.kr", []),
    ("경상북도청", "https://www.gb.go.kr", []),
    ("청주시청", "https://www.cheongju.go.kr", []),
]

def scan(s, name, home, extra):
    print(f"\n### {name}  <{home}>")
    try:
        r = get(s, home)
    except Exception as e:
        print(f"  [홈 접속실패] {type(e).__name__}: {str(e)[:80]}")
        return
    print(f"  home HTTP {r.status_code}, {len(r.text)//1024}KB")
    soup = BeautifulSoup(r.text, "lxml")
    cands = {}
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        h = a["href"]
        if h.startswith(("javascript", "#", "mailto")):
            continue
        if BOARD_HINT.search(t) and 2 <= len(t) <= 20:
            full = urljoin(r.url, h)
            cands.setdefault(full, t)
    for u in extra:
        cands.setdefault(u, "(수동후보)")
    if not cands:
        print("  게시판 후보 링크 없음 (JS 메뉴 가능성)")
        return
    # 후보 상위 12개만 열어 음악 공고 확인
    shown = 0
    for url, label in list(cands.items())[:12]:
        try:
            rr = get(s, url)
        except Exception as e:
            print(f"  - {label:14} {url}  [실패 {type(e).__name__}]")
            continue
        body = BeautifulSoup(rr.text, "lxml").get_text(" ", strip=True)
        music = len(MUSIC.findall(body))
        job = len(JOBWORD.findall(body))
        flag = "★음악공고有" if music >= 2 and job >= 2 else ("·구인板" if job >= 3 else "")
        print(f"  - {label:14} HTTP{rr.status_code} music={music:2} job={job:2} {flag}  {url}")
        shown += 1
    if shown == 0:
        print("  후보 열람 실패")

if __name__ == "__main__":
    s = new_session()
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    for name, home, extra in TARGETS:
        if only and not any(o in name for o in only):
            continue
        scan(s, name, home, extra)
