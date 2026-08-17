# 원문 보관층(raw store) — 공고의 페이지 본문·첨부 텍스트를 통째로 저장한다.
#
# 왜 필요한가(2026-08-02 규명): 지금까지는 크롤 시점에 필드를 추출하고 원문을 버렸다.
# 그래서 추출기를 고쳐도 마감돼 원문이 죽은 공고엔 재적용이 불가능했다 — 악기 미상
# 보강대상 163건 중 161건이 회복 불가였던 이유. 원문을 보관하면 추출기 개선이
# 과거분까지 소급된다(reextract.py). 파이프라인:
#   소스 순회 → 제목 필터 → [본문+첨부 txt화 → 여기 저장] → 추출 → official/archive
#
# 저장 형태: data/raw/<id>.json  {"url","title","fetchedAt","page","attach":[{name,text}]}
# 원칙:
#  ① 불변 누적 — 이미 저장된 섹션은 덮어쓰지 않는다(같은 이름의 첨부는 갱신이 아니라 보존).
#  ② 실패도 기록 — 첨부를 시도했는데 못 얻은 날짜를 attachTried에 남겨 매일 재시도 폭주를 막되,
#     영영 포기하지는 않는다(RETRY_DAYS 지나면 다시 시도).
import json
import os
import re
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE, "data", "raw")
MAX_SECTION = 120_000   # 섹션당 텍스트 상한 (OCR 폭주·거대 xlsx 방어)
MAX_ATTACH = 8
RETRY_DAYS = 7          # 첨부 실패 후 재시도 간격

_buf = {}               # id → {"url","title","page","attach":[...]} (크롤 중 메모리 버퍼)


def _path(iid):
    # id는 sha1 16자리 hex — 경로 조작 여지가 없지만 방어적으로 걸러둔다
    iid = re.sub(r"[^0-9a-f]", "", iid or "")
    return os.path.join(RAW_DIR, f"{iid}.json")


def load(iid):
    """저장된 원문. **이번 크롤에서 방금 담은 것(메모리 버퍼)까지 함께 보여준다.**

    ★ 이걸 디스크만 읽게 두면 '오늘 처음 들어온 공고'는 원문이 빈 것으로 보인다 —
      버퍼는 크롤 마지막에 flush 되는데 재추출(_refill_from_raw)은 그 전에 돌기 때문이다.
      그래서 마감·연락처·이메일처럼 재추출 경로에만 있는 값이 신규 공고에서 통째로
      비었고, 다음 날 크롤에서야 채워졌다(하루 늦은 자기치유). 인천중산고 카드가
      기관·지역만 남아 텅 빈 채로 배포된 원인이다 (2026-08-17 규명).
    """
    try:
        with open(_path(iid), encoding="utf-8") as f:
            doc = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        doc = None
    b = _buf.get(iid)
    if not b:
        return doc
    if not doc:
        # 아직 파일이 없다 — 버퍼 내용만으로 flush 와 같은 모양을 만들어 돌려준다
        return {"url": b.get("url"), "title": b.get("title"),
                "page": b.get("page"), "attach": list(b.get("attach") or [])}
    # 파일과 버퍼를 겹친다 (flush 와 같은 규칙: 기존 섹션 보존, 새 이름의 첨부만 추가)
    merged = dict(doc)
    merged["page"] = doc.get("page") or b.get("page")
    attach = list(doc.get("attach") or [])
    names = {a.get("name") for a in attach}
    for a in (b.get("attach") or []):
        if a.get("name") not in names and len(attach) < MAX_ATTACH:
            attach.append(a)
            names.add(a.get("name"))
    merged["attach"] = attach
    return merged


def has_attach(iid):
    doc = load(iid)
    return bool(doc and doc.get("attach"))


def tried_recently(iid):
    doc = load(iid)
    if not doc or not doc.get("attachTried"):
        return False
    try:
        return (date.today() - date.fromisoformat(doc["attachTried"])).days < RETRY_DAYS
    except ValueError:
        return False


def stash(iid, kind, text, name=None, url=None, title=None):
    """크롤 중 확보한 텍스트를 버퍼에 쌓는다. kind: 'page' | 'attach' | 'ocr'"""
    if not iid or not text or not text.strip():
        return
    b = _buf.setdefault(iid, {"url": url, "title": title, "page": None, "attach": []})
    if url and not b.get("url"):
        b["url"], b["title"] = url, title
    text = text[:MAX_SECTION]
    if kind == "page":
        if not b["page"]:
            b["page"] = text
    else:
        label = name or kind
        if len(b["attach"]) < MAX_ATTACH and all(a["name"] != label for a in b["attach"]):
            b["attach"].append({"name": label, "text": text})


def mark_tried(iid):
    """첨부를 시도했음을 기록 (0건이어도) — 다음 크롤의 재시도 여부 판단용"""
    b = _buf.setdefault(iid, {"url": None, "title": None, "page": None, "attach": []})
    b["_tried"] = True


def flush():
    """버퍼를 디스크에 병합 저장. 기존 섹션은 보존(불변 누적). 저장 건수를 돌려준다."""
    os.makedirs(RAW_DIR, exist_ok=True)
    saved = 0
    for iid, b in _buf.items():
        old = load(iid) or {}
        doc = {
            # url 은 '이 원문을 어디서 걷었나' — 최신 수집처가 이긴다. 집계 포털에서 걷었다가
            # 나중에 기관 원문을 찾으면 그쪽이 정본이고, 이 값이 갱신돼야 '원문 주소가 바뀐
            # 공고 재수집' 판정(main._ensure_raw_attachments)이 한 번으로 끝난다 (2026-08-18).
            "url": b.get("url") or old.get("url"),
            "title": old.get("title") or b.get("title"),
            "fetchedAt": old.get("fetchedAt") or date.today().isoformat(),
            "page": old.get("page") or b.get("page"),
            "attach": list(old.get("attach") or []),
        }
        names = {a["name"] for a in doc["attach"]}
        for a in b["attach"]:
            if a["name"] not in names and len(doc["attach"]) < MAX_ATTACH:
                doc["attach"].append(a)
                names.add(a["name"])
        if b.get("_tried"):
            doc["attachTried"] = date.today().isoformat()
        elif old.get("attachTried"):
            doc["attachTried"] = old["attachTried"]
        # 저장할 내용이 아무것도 없으면(빈 껍데기) 파일을 만들지 않는다
        if not doc["page"] and not doc["attach"] and not doc.get("attachTried"):
            continue
        p = _path(iid)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        os.replace(tmp, p)
        saved += 1
    _buf.clear()
    return saved


def attach_text(iid):
    """첨부(공고문)만 이어 붙인다.

    마감일은 웹페이지보다 첨부 공고문이 정확하다. 게시판 상세 페이지는 그 사이트의 다른
    공고 목록을 함께 실어 오는 곳이 많아, 본문부터 훑으면 남의 날짜를 먼저 문다 —
    군산시립교향악단 공고는 시청의 채용공고 목록이 딸려 와 2026-07-28(남의 공고)을 물었고,
    첨부 공고문만 보면 제 날짜인 2026-06-11 이 바로 나온다 (2026-08-09).
    """
    doc = load(iid)
    if not doc:
        return ""
    return "\n".join(a.get("text") or "" for a in (doc.get("attach") or []) if a.get("text"))


def all_text(iid):
    """저장된 원문 전체를 하나의 문자열로 — 재추출용.

    제목을 맨 앞에 붙인다. 제목에만 마감이 적힌 공고가 흔한데('…모집(~8/14)'),
    본문·첨부만 이어 붙이던 탓에 재추출 경로에서는 그 정보가 통째로 없는 셈이었다
    (2026-08-08 사용자 지적). 수집 당시에는 deadline_from_title 이 따로 봤지만,
    나중에 추출 규칙을 고쳐 소급 적용할 때는 아무도 제목을 보지 않았다.
    """
    doc = load(iid)
    if not doc:
        return ""
    parts = [doc.get("title") or "", doc.get("page") or ""]
    parts += [a.get("text") or "" for a in doc.get("attach") or []]
    return "\n".join(p for p in parts if p)
