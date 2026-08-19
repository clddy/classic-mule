# -*- coding: utf-8 -*-
"""IndexNow 통보 — 새 공고를 네이버·빙에 직접 알린다 → data/indexnow_state.json

왜: 검색엔진이 우리 사이트를 언제 다시 볼지는 자기가 정한다. 실제로 구글은 2026-08-03에
왔다 간 뒤 닷새를 안 왔다. 매일 수집이 이 사이트의 핵심인데 그게 검색에 닿지 않으면 의미가
없다. IndexNow 는 그 순서를 뒤집어 **우리가 먼저 알린다**.

구글은 IndexNow 를 지원하지 않는다 — 구글 쪽은 crawler/gindex.py(Indexing API)가 맡는다.
대신 IndexNow 는 페이지 종류 제한이 없어서 목록 페이지도 통보할 수 있고(구글 Indexing API 는
채용공고·생방송만 허용), 계정·심사가 필요 없다.

인증: 사이트 최상위의 <키>.txt 파일에 같은 키가 적혀 있으면 그 사이트의 소유자로 본다.
      이 파일은 **공개가 정상**이다 — 남이 우리 주소를 함부로 통보하지 못하게 하는 장치일 뿐,
      비밀값이 아니다. 그래서 저장소에 커밋한다.
"""
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(BASE, "data", "indexnow_state.json")
SITE = "https://podiumclassical.kr"
HOST = "podiumclassical.kr"
# 여러 엔진에 함께 통보한다. api.indexnow.org 가 참여 엔진에 배포해 주긴 하지만, 네이버는
# 자체 엔드포인트를 따로 안내한다 — 신규 사이트라 수집이 느린 판에 배포를 기다릴 이유가 없다
# (2026-08-19: 네이버 수집 현황이 열흘째 0건이었다).
ENDPOINTS = [
    ("indexnow", "https://api.indexnow.org/indexnow"),
    ("naver", "https://searchadvisor.naver.com/indexnow"),
]
MAX_URLS = 2000          # 규격 상한은 10,000. 우리는 훨씬 적다


def _key():
    """사이트 최상위의 <32자리>.txt 가 키 파일이다."""
    for p in glob.glob(os.path.join(BASE, "*.txt")):
        name = os.path.basename(p)[:-4]
        if len(name) == 32 and all(c in "0123456789abcdef" for c in name):
            return name
    return None


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def notify(verbose=True):
    key = _key()
    if not key:
        if verbose:
            print("[indexnow] 키 파일 없음 — 건너뜀")
        return 0

    import requests
    doc = _load(os.path.join(BASE, "data", "official.json"), {})
    items = doc.get("items") if isinstance(doc, dict) else doc
    live = {f"{SITE}/p/{i['id']}.html" for i in (items or []) if i.get("id")}
    seen = set(_load(STATE, []))

    # 목록 페이지는 내용이 매일 바뀌므로 늘 함께 알린다.
    always = [f"{SITE}/", f"{SITE}/jobs.html", f"{SITE}/practice.html"]
    # 상세 페이지는 새로 생긴 것만. 사라진 것도 알린다 — 검색결과에 유령 공고가 남지 않게
    # (IndexNow 는 삭제 전용 신호가 없다. 통보하면 엔진이 다시 와서 404 를 보고 지운다).
    fresh = sorted(live - seen)
    gone = sorted(seen - live)
    urls = always + fresh + gone
    if len(urls) > MAX_URLS:
        if verbose:
            print(f"[indexnow] {len(urls)}건 중 {MAX_URLS}건만 — 나머지는 다음 회차")
        urls = urls[:MAX_URLS]

    payload = {"host": HOST, "key": key,
               "keyLocation": f"{SITE}/{key}.txt", "urlList": urls}
    results, ok_any = [], False
    for name, url in ENDPOINTS:
        try:
            r = requests.post(url, timeout=30, json=payload)
        except Exception as e:
            results.append(f"{name}:{type(e).__name__}")
            continue
        # 200·202 가 정상. 그 밖의 코드는 이유를 남긴다(422=키 불일치, 403=키 파일 못 읽음).
        results.append(f"{name}:{r.status_code}")
        if r.status_code in (200, 202):
            ok_any = True
        else:
            print(f"[indexnow/{name}] {r.status_code} {r.text[:150]}")

    # 한 곳이라도 받았으면 통보한 것으로 친다 — 전부 실패했을 때만 다음 회차에 다시 보낸다
    if not ok_any:
        return 0
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(sorted(live), f, ensure_ascii=False, indent=1)
    if verbose:
        print(f"[indexnow] {len(urls)}건 통보 (신규 {len(fresh)} · 내려감 {len(gone)}) · "
              + " ".join(results))
    return len(urls)


if __name__ == "__main__":
    sys.exit(0 if notify() >= 0 else 1)
