# 6단계(최종): 서울시향 ajax / 오페라단 상세URL / 대전·대구·SAC 아이템 패턴
import re, json
import requests
import urllib3
urllib3.disable_warnings()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9", "X-Requested-With": "XMLHttpRequest"}
s = requests.Session(); s.headers.update(UA)

def sec(t): print(f"\n{'='*60}\n{t}\n{'='*60}")

# --- 서울시향 ajax ---
sec("서울시향 selectNoticeList POST")
for method in ("post", "get"):
    try:
        r = getattr(s, method)("https://www.seoulphil.or.kr/recruit/orchestra/selectNoticeList",
                               data={"pageIndex": 1, "pageUnit": 10}, timeout=15, verify=False)
        print(method, r.status_code, r.headers.get("content-type"), len(r.text))
        if r.status_code == 200 and len(r.text) > 50:
            print(r.text[:800]); break
    except Exception as e:
        print(method, "ERR", str(e)[:80])

# --- 국립오페라단 상세 URL 추정 ---
sec("국립오페라단 boardSeq 상세 URL")
for u in ["https://www.nationalopera.org/cpage/board/noticeView?boardSeq=16519",
          "https://www.nationalopera.org/cpage/board/notice/view?boardSeq=16519",
          "https://www.nationalopera.org/cpage/board/noticeDetail?boardSeq=16519"]:
    r = s.get(u, timeout=15, verify=False)
    ok = "채용" in r.text
    print(u[:80], "->", r.status_code, len(r.text), "본문에 '채용':", ok)
    if ok: break

# --- 대전 06_01 페이지 구조 ---
sec("대전 06_01 앵커 전수")
r = s.get("https://dpo.artdj.kr/dpo/?a_idx=06_01", timeout=15, verify=False)
r.encoding = "euc-kr"
anchors = re.findall(r'<a[^>]+href="([^"]{3,120})"[^>]*>([\s\S]{0,100}?)</a>', r.text)
for h, t in anchors:
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t)).strip()
    if txt and not h.startswith("#"): print("  ", h[:80], "|", txt[:50])

# --- SAC recruit 제목 주변 ---
sec("SAC recruit '채용' 주변")
r = s.get("https://www.sac.or.kr/site/main/board/recruit/list", timeout=15, verify=False)
i = r.text.find("채용", 100000)
idxs = [m.start() for m in re.finditer(r"(모집|채용) ?공고", r.text)][:3]
for i in idxs:
    print(re.sub(r"\s+", " ", r.text[max(0,i-500):i+120])[:600], "\n  ---")

# --- 대구문화예술회관 selectBoardArticle ---
sec("대구문화예술회관 selectBoardArticle 패턴")
r = s.get("https://daeguartscenter.or.kr/index.do?menu_id=00001528", timeout=15, verify=False)
hits = re.findall(r'href="([^"]*selectBoardArticle[^"]*)"[^>]*>([\s\S]{0,150}?)</a>', r.text)[:5]
for h, t in hits:
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t)).strip()
    print("  ", h[:110], "|", txt[:60])
if not hits:
    i = r.text.find("공개모집")
    print(re.sub(r"\s+"," ",r.text[max(0,i-600):i+150])[:700] if i>0 else "  없음")

print("\ndone")
