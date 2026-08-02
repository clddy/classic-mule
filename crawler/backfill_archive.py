# 과거 공고 복원 — git 히스토리에 박힌 data/official.json 스냅샷을 전부 훑어
# data/archive.json 을 채운다. 아카이브 도입(2026-08) 이전 수집분을 살리는 1회성 작업이지만,
# 여러 번 돌려도 안전하다(병합이라 중복이 쌓이지 않음).
#
# 왜 되는가: 크롤이 매일 data/ 를 커밋해 왔기 때문에 커밋 하나하나가 그날의 스냅샷이다.
# 커밋 날짜를 그날의 관측일로 삼아 firstSeen/lastSeen/days 를 재구성한다.
#
#   python crawler/backfill_archive.py            # 실행
#   python crawler/backfill_archive.py --dry-run  # 뭐가 들어올지만 확인
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archive  # noqa: E402

TARGET = "data/official.json"


def git(*args):
    r = subprocess.run(["git", "-C", BASE, *args], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} 실패: {r.stderr.decode('utf-8', 'replace')[:200]}")
    return r.stdout.decode("utf-8", "replace")


def commits():
    """(sha, YYYY-MM-DD) 오래된 것부터."""
    out = git("log", "--reverse", "--format=%H\t%ad", "--date=short", "--", TARGET)
    return [tuple(l.split("\t")) for l in out.splitlines() if "\t" in l]


def main():
    dry = "--dry-run" in sys.argv
    cs = commits()
    if not cs:
        print(f"{TARGET} 커밋 이력이 없다 — 저장소가 맞는지 확인할 것", file=sys.stderr)
        return 1
    print(f"커밋 {len(cs)}개 ({cs[0][1]} ~ {cs[-1][1]})")

    # 메모리에 한 벌 들고 순차 병합한 뒤 마지막에 한 번만 쓴다.
    arc = archive.load(BASE)
    before = len(arc)
    skipped = 0
    for i, (sha, day) in enumerate(cs, 1):
        try:
            doc = json.loads(git("show", f"{sha}:{TARGET}"))
        except (RuntimeError, json.JSONDecodeError) as e:
            # 초기 커밋은 스키마가 다르거나 파일이 없을 수 있다 — 건너뛰되 조용히 넘기지 않는다
            print(f"  [{i}/{len(cs)}] skip {day} {sha[:8]}: {type(e).__name__}")
            skipped += 1
            continue
        items = doc.get("items") if isinstance(doc, dict) else doc
        if not isinstance(items, list):
            print(f"  [{i}/{len(cs)}] skip {day} {sha[:8]}: items 배열 없음 (옛 스키마)")
            skipped += 1
            continue
        n = archive.merge(BASE, items, seen_on=day, arc=arc, save=False)
        print(f"  [{i}/{len(cs)}] {day} {sha[:8]} · 스냅샷 {len(items):3d}건 · 신규 {n:3d}건 · 누적 {len(arc)}건")

    print(f"\n복원 결과: {before}건 → {len(arc)}건 (+{len(arc) - before}), 건너뜀 {skipped}개 커밋")
    if dry:
        print("--dry-run 이므로 저장하지 않았다.")
        return 0
    archive.write(BASE, arc)
    print(f"저장: data/archive.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
