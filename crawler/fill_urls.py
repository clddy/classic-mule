# URL 발굴 파이프 1단계 — homepage_seeds.json 의 시드를 institutions.csv 빈 홈페이지 칸에 채운다.
#
# 원칙:
#  ① 빈 칸에만 쓴다 — 사람이 이미 채운 값은 절대 덮지 않는다.
#  ② 시드가 틀려도 괜찮다 — fullsweep 이 검증한다 (home_unreachable → 백로그로 복귀).
#  ③ 시드에 없는 기관은 그대로 남는다 = 웹 검색 백로그.
#  ④ CSV 는 주석·행 순서 보존해 라인 단위로 다시 쓴다 (쉼표 든 값은 csv.writer 인용 —
#     손으로 이어붙이면 열이 밀린다는 CLAUDE.md 함정 준수).
#
#   python crawler/fill_urls.py            # 채우기
#   python crawler/fill_urls.py --dry-run  # 뭐가 채워질지만
import csv
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "institutions.csv")
SEEDS = os.path.join(HERE, "homepage_seeds.json")


def norm(s):
    return "".join((s or "").split()).replace("(재)", "").replace("재단법인", "")


def main():
    dry = "--dry-run" in sys.argv
    seeds = {norm(k): v for k, v in json.load(open(SEEDS, encoding="utf-8")).items()
             if not k.startswith("_")}
    # 프로버(probe_homepages.py)가 실접속 검증까지 마친 발견분 — 시드보다 신뢰도가 높다
    probed = os.path.join(os.path.dirname(HERE), "data", "fullsweep", "probed_homepages.json")
    try:
        for k, v in json.load(open(probed, encoding="utf-8"))["found"].items():
            seeds[norm(k)] = v["url"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    out_lines, filled, backlog = [], [], 0
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        for line in f:
            raw = line.rstrip("\n")
            # 주석·헤더는 그대로 통과
            if not raw or raw.lstrip().startswith("#") or raw.startswith("기관명"):
                out_lines.append(raw)
                continue
            row = next(csv.reader([raw]))
            if len(row) < 8:
                out_lines.append(raw)
                continue
            if row[7].strip() == "확정" and not row[4].strip().startswith("http"):
                url = seeds.get(norm(row[0]))
                if url:
                    row[4] = url
                    filled.append(f"{row[0]} → {url}")
                    buf = io.StringIO()
                    csv.writer(buf, lineterminator="").writerow(row)
                    out_lines.append(buf.getvalue())
                    continue
                backlog += 1
            out_lines.append(raw)

    print(f"채움 {len(filled)}건 · 백로그(시드 없음) {backlog}건")
    for x in filled[:15]:
        print("  +", x)
    if len(filled) > 15:
        print(f"  … 외 {len(filled) - 15}건")
    if dry:
        print("--dry-run — 저장 안 함")
        return 0
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(out_lines) + "\n")
    print(f"저장: crawler/institutions.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
