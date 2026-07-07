# 크롤링 소스 현황을 옵시디언 노트로 내보내기 (run_daily에서 매일 갱신)
import json, os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sources import SOURCES

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT_NOTE = r"C:\ohai\vault\포디움 크롤링 소스.md"

LAYER_DESC = {"A": "전국 집계", "B": "지역 재단·회관", "C": "도메인 포털", "D": "기관 원천"}
POLL_DESC = {"daily": "매일", "weekly": "주 2~3회", "seasonal": "시즌"}

def main():
    data = {}
    try:
        with open(os.path.join(BASE, "data", "official.json"), encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        pass
    stats = {s["id"]: s for s in data.get("sources", [])}
    items = data.get("items", [])
    by_channel = {}
    for it in items:
        by_channel[it.get("channel")] = by_channel.get(it.get("channel"), 0) + 1

    coverage = {}
    try:
        with open(os.path.join(BASE, "data", "coverage_report.json"), encoding="utf-8") as f:
            coverage = json.load(f)
    except Exception:
        pass

    queue = {}
    try:
        with open(os.path.join(BASE, "data", "source_queue.json"), encoding="utf-8") as f:
            queue = json.load(f)
    except Exception:
        pass

    lines = [
        "---",
        "tags: [포디움, 크롤링]",
        f"updated: {datetime.now():%Y-%m-%d %H:%M}",
        "---",
        "",
        "# 포디움 크롤링 소스 현황",
        "",
        f"- 수집 시각: **{data.get('collectedAt', '-')}** · 소스 **{data.get('okCount', 0)}/{data.get('sourceCount', 0)}** 응답 · 공고 **{len(items)}건**",
        f"- 마감 확보: **{sum(1 for i in items if i.get('deadline'))}건** · 상시 **{sum(1 for i in items if i.get('deadlineNote') == '상시')}건**",
        "- 라이브: https://clddy.github.io/classic-mule/ · 저장소: https://github.com/clddy/classic-mule",
        "",
        "## 소스 목록",
        "",
        "| 소스 | 층위 | 주기 | 현재 수집 | 상태 | 게시판 |",
        "|---|---|---|---|---|---|",
    ]
    for s in SOURCES:
        st = stats.get(s["id"], {})
        if st.get("skipped"):
            status = "승계(주기 외)"
        elif st.get("ok"):
            status = "정상"
        elif st:
            status = "⚠ 실패"
        else:
            status = "-"
        cnt = by_channel.get(s["id"], 0)
        lines.append(f"| {s['name']} | {s['layer']} {LAYER_DESC[s['layer']]} | {POLL_DESC[s['poll']]} "
                     f"| {cnt}건 | {status} | {s['domain']} |")

    lines += [
        "",
        "## 커버리지 공백 (명부 대조, 자동 감지)",
        "",
        f"명부 {coverage.get('total', 0)}곳 중 최근 공고 미확인 **{coverage.get('gapCount', 0)}곳**:",
        "",
    ]
    gaps = coverage.get("gaps", [])
    lines.append(", ".join(f"{g['name']}({g['region']})" for g in gaps) or "-")

    fails = (queue.get("failed") or [])
    if fails:
        lines += ["", "## 디스커버리 실패 (수동 대응 필요)", ""]
        for f_ in fails:
            lines.append(f"- {f_['name']} — {f_['reason']}")
    q = (queue.get("queue") or [])
    if q:
        lines += ["", "## 확인 대기 큐", ""]
        for e in q:
            lines.append(f"- {e['name']} — {e['board_url']}")

    lines += [
        "",
        "## 백로그",
        "",
        "- 워크넷 오픈API (고용24 인증키 발급 대기)",
        "- KOPIS 오픈API (kopis.or.kr 승인 대기) — 세션 수요 선행지표",
        "- 나라일터 (세션 POST 검색 — 구조 추적 필요)",
        "- 시도교육청 15곳 (경남만 연결됨; 경기·인천·대전은 봇차단/ajax)",
        "- 포항·춘천·서울·인천·부산문화재단 (목록 JS/특수 구조)",
        "- 아르떼 꿈의오케스트라 (채용 게시판 목록 미노출)",
        "",
    ]

    os.makedirs(os.path.dirname(VAULT_NOTE), exist_ok=True)
    with open(VAULT_NOTE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"노트 갱신: {VAULT_NOTE}")

if __name__ == "__main__":
    main()
