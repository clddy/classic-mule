# 5단계: 마지막 4곳 정밀 분석
import re, time
import requests
import urllib3
urllib3.disable_warnings()

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}
s = requests.Session(); s.headers.update(UA)

def sec(t): print(f"\n{'='*60}\n{t}\n{'='*60}")

# --- 대전시향 공지 board ---
sec("대전시향 a_idx=06_01")
r = s.get("https://dpo.artdj.kr/dpo/?a_idx=06_01", timeout=15, verify=False)
r.encoding = "euc-kr"
print(r.status_code, len(r.text))
for m in re.findall(r'<a[^>]+href="([^"]*d_no=\d+[^"]*)"[^>]*>([^<]{6,80})</a>', r.text)[:6]:
    print("  ", m[1].strip()[:60], "|", m[0][:90])
# 다른 패턴도
for m in re.findall(r'<a[^>]+href="(\?a_idx=06[^"]*)"[^>]*>\s*([^<]{6,80})', r.text)[:6]:
    print("  alt:", m[1].strip()[:60], "|", m[0][:90])

# --- 서울시향: ajax 엔드포인트 탐색 ---
sec("서울시향 orchestra/list ajax 탐색")
r = s.get("https://www.seoulphil.or.kr/recruit/orchestra/list", timeout=15, verify=False)
for m in set(re.findall(r'(?:url|action)\s*[:=]\s*["\']([^"\']{5,80})["\']', r.text)):
    if re.search(r"recruit|list|bbs|board", m, re.I): print("  ep:", m)
# tbody 안 내용 확인
tb = re.search(r"<tbody[\s\S]{0,3000}?</tbody>", r.text)
print("  tbody:", (tb.group(0)[:600] if tb else "없음"))

sec("서울시향 /srvc/bbs/4/list 시도")
r2 = s.get("https://www.seoulphil.or.kr/srvc/bbs/4/list", timeout=15, verify=False)
print(r2.status_code, len(r2.text))
for m in re.findall(r'<a[^>]+href="([^"]*dynmPstNo=\d+[^"]*)"[^>]*>\s*([^<]{6,80})', r2.text)[:6]:
    print("  ", m[1].strip()[:60], "|", m[0][:80])

# --- 국립오페라단: 제목 주변 마크업 ---
sec("국립오페라단 notice 제목 주변")
r = s.get("https://www.nationalopera.org/cpage/board/notice", timeout=15, verify=False)
i = r.text.find("직원 채용 공고")
print(r.text[max(0,i-700):i+150].replace("\n"," ")[:900] if i>0 else "제목 못찾음")

# --- 예술의전당 recruit list 아이템 ---
sec("예술의전당 recruit 아이템")
r = s.get("https://www.sac.or.kr/site/main/board/recruit/list", timeout=15, verify=False)
for m in re.findall(r'<a[^>]+href="([^"]*board/recruit/\d+[^"]*)"[^>]*>([\s\S]{0,200}?)</a>', r.text)[:6]:
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m[1])).strip()
    print("  ", txt[:70], "|", m[0][:80])

# --- 대구문화예술회관 채용 board 아이템 ---
sec("대구문화예술회관 menu_id=00001528")
r = s.get("https://daeguartscenter.or.kr/index.do?menu_id=00001528", timeout=15, verify=False)
print(r.status_code, len(r.text))
for m in re.findall(r'<a[^>]+href="([^"]*nttId=\d+[^"]*)"[^>]*>([\s\S]{0,150}?)</a>', r.text)[:6]:
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m[1])).strip()
    print("  ", txt[:70], "|", m[0][:100])

print("\ndone")
