# 명부 URL 정합성 검증 — institutions.csv 의 홈페이지가 진짜 살아있는지 확인한다.
#
# 왜 필요한가(2026-08-02): probe_homepages.py 가 "3KB 미만은 JS 스텁이니 통과"라는
# 완화 규칙을 뒀는데, 국내 사이트의 404 안내 페이지도 딱 그 크기다. 그 결과
# junggu.kccf.or.kr 처럼 존재하지 않는 주소 203개가 명부에 들어갔다. 명부가 거짓이면
# 커버리지 리포트도 fullsweep 백로그도 전부 거짓이 된다.
#
# 판정: curl 200 + 에러 문구 없음 + (본문이 충분하거나, 스텁이면 리다이렉트 흔적 있음)
#
#   python crawler/verify_urls.py            # 검사만 (리포트)
#   python crawler/verify_urls.py --clean    # 죽은 URL을 CSV에서 비운다(백로그로 복귀)
import csv
import io
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import curl_get, UA  # noqa: E402
import urllib3
urllib3.disable_warnings()

CSV_PATH = os.path.join(HERE, "institutions.csv")

# 국내 사이트의 '없는 주소' 안내 — 200 으로 돌려주는 곳이 많아 상태코드로는 못 거른다
ERR_PAT = re.compile(
    r"찾을\s*수\s*없|존재하지\s*않|잘못\s*입력|없는\s*페이지|삭제되었|이용할\s*수\s*없"
    r"|서비스\s*점검|접근\s*권한|not\s*found|404\s*error|forbidden|bad\s*request", re.I)
# 스텁이 진짜 리다이렉트 스텁인지 (meta refresh · location · frame)
REDIR_PAT = re.compile(r"http-equiv=[\"']?refresh|location\s*[.=]|<frame|window\.open|<script", re.I)
# 살아있는 JS 스텁과 가짜 주소의 에러 페이지는 스크립트 유무로 갈린다 (2026-08-02 확인):
#  · 서울시교육청 477B — netfunnel.js·jQuery 로드 / 조선대 369B — location = "http://www3..."
#  · junggu.kccf.or.kr 451B — 스크립트 0개, "주소가 잘못 입력되었거나…" 표만 있는 순수 HTML


def _fetch_either(url, timeout=12):
    """curl(Schannel) → requests(OpenSSL) 순으로 시도. 하나라도 되면 그 응답.

    두 엔진의 사각이 서로 반대다: cwcf 계열은 파이썬 TLS를 막고(curl만 성공),
    국립합창단은 curl 이 SSL 협상 실패(exit 35)인데 requests 는 정상이다.
    한쪽만 보면 살아있는 사이트를 죽었다고 판정한다 (2026-08-02).
    """
    import requests
    # https 를 거절하고 http 로만 여는 곳도 있다 (국립합창단: https 406 / http 200)
    cands = [url] + ([url.replace("https://", "http://", 1)] if url.startswith("https://") else [])
    last = (599, "", 0)
    for u in cands:
        r = curl_get(u, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 0:
            return r.status_code, r.text, len(r.content)
        last = (r.status_code, r.text, len(r.content))
        try:
            rr = requests.get(u, timeout=timeout, verify=False, headers=UA, allow_redirects=True)
            if rr.encoding in (None, "ISO-8859-1"):
                rr.encoding = rr.apparent_encoding
            if rr.status_code == 200:
                return rr.status_code, rr.text, len(rr.content)
            last = (rr.status_code, rr.text, len(rr.content))
        except Exception:
            pass
    return last


def check(name, url):
    status, body, size = _fetch_either(url)
    if status != 200:
        return name, url, "unreachable"
    text = body[:20_000]
    # 에러 판정은 좁게 — 본문 전체에서 문구를 찾으면 살아있는 사이트의 JS 에러 핸들러·
    # 검색 안내문에 걸린다(2026-08-02: 세종문화회관·경기문화재단 등 현役 소스가 오탐).
    # 제목에 있거나, 페이지가 통째로 작을 때만 에러로 본다.
    title = (re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I) or [None, ""])[1]
    if ERR_PAT.search(title) or (size < 5000 and ERR_PAT.search(text)):
        return name, url, "error_page"
    if size < 1200 and not REDIR_PAT.search(text):
        return name, url, "empty_stub"
    return name, url, "ok"


def main():
    clean = "--clean" in sys.argv
    rows, targets = [], []
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        for line in f:
            raw = line.rstrip("\n")
            rows.append(raw)
            if not raw or raw.lstrip().startswith("#") or raw.startswith("기관명"):
                continue
            row = next(csv.reader([raw]))
            if len(row) >= 8 and row[7].strip() == "확정" and row[4].strip().startswith("http"):
                targets.append((len(rows) - 1, row))

    print(f"검증 대상 {len(targets)}곳 (병렬 14)")
    bad = {}
    with ThreadPoolExecutor(max_workers=14) as ex:
        futs = {ex.submit(check, r[0], r[4].strip()): i for i, r in targets}
        for k, fut in enumerate(as_completed(futs), 1):
            name, url, verdict = fut.result()
            if verdict != "ok":
                bad[futs[fut]] = (name, url, verdict)
            if k % 100 == 0:
                print(f"  … {k}/{len(targets)} (불량 {len(bad)})")

    from collections import Counter
    print(f"\n불량 {len(bad)} / {len(targets)}")
    print(Counter(v[2] for v in bad.values()).most_common())
    for i, (n, u, v) in list(bad.items())[:20]:
        print(f"  [{v}] {n} — {u}")
    if len(bad) > 20:
        print(f"  … 외 {len(bad) - 20}곳")

    if not clean:
        print("\n--clean 을 주면 CSV의 해당 URL을 비운다(발굴 백로그로 복귀)")
        return 0
    for idx, (n, u, v) in bad.items():
        row = next(csv.reader([rows[idx]]))
        row[4] = ""
        buf = io.StringIO()
        csv.writer(buf, lineterminator="").writerow(row)
        rows[idx] = buf.getvalue()
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(rows) + "\n")
    print(f"\n정리 완료: {len(bad)}곳의 URL을 비웠다 — crawler/institutions.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
