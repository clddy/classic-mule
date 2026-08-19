# 한글 → 로마자 (국어의 로마자 표기법, 문화체육관광부 고시 기준 축약 구현).
#
# URL 슬러그 전용이라 학술적 정확성보다 '안정성·가독성·충돌 없음'이 목표다.
# 외부 라이브러리를 쓰지 않는 이유: 슬러그는 한 번 정하면 URL로 굳는다. 라이브러리
# 버전이 바뀌어 표기가 달라지면 색인된 주소가 통째로 흔들린다 (2026-08-20).
#
# 구현 범위
#  · 초성·중성·종성 3분해 후 음절 경계에서 자음동화(비음화·유음화) 주요 규칙만 반영
#  · 사전 등재어(악기·직무·지역)는 표에서 직접 꺼낸다 — 자동 변환보다 읽기 좋다
import re

CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj",
       "ch", "k", "t", "p", "h"]
JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe",
        "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
JONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "l", "l", "l", "l", "l", "l",
        "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]

# 종성 + 다음 초성 자리에서 일어나는 소리 바뀜 (URL 가독성에 영향이 큰 것만)
# ★ 자음동화(비음화·유음화)는 적용하지 않는다 (2026-08-20 사용자 지시).
# 소리 규칙대로 굴리면 '종로→jongno', '신라→silla' 처럼 기관이 스스로 쓰는 표기와
# 어긋난다. 우리는 발음 표기가 아니라 '그 기관의 이름'을 URL 에 적는 것이므로,
# 글자를 그대로 옮기고 알려진 영문명은 slug._ORG_ALIAS 에서 직접 꺼낸다.

def _syllables(text):
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            i = code - 0xAC00
            yield (CHO[i // 588], JUNG[(i % 588) // 28], JONG[i % 28])
        else:
            yield ch


def romanize(text):
    """한글 문자열 → 로마자. 한글이 아닌 글자는 소문자로 흘려보낸다."""
    syls = list(_syllables(text or ""))
    out = []
    for idx, s in enumerate(syls):
        if not isinstance(s, tuple):
            out.append(str(s).lower())
            continue
        cho, jung, jong = s
        out.append(cho + jung + jong)
    return "".join(out)


def slugify(text, maxlen=20, table=None):
    """URL 조각으로. 사전(table)에 있으면 사전 값을 쓰고, 없으면 로마자 변환."""
    if not text:
        return ""
    t = str(text).strip()
    if table and t in table:
        return table[t]
    t = re.sub(r"\([^)]*\)", "", t)                  # 괄호 주석 제거
    t = re.sub(r"[·/,]", " ", t)
    t = romanize(t)
    t = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    return t[:maxlen].rstrip("-")
