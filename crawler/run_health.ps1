# Daily: 크롤 결과·배포 사이트 헬스체크. 이상 있을 때만 텔레그램으로 알린다.
#
# 크롤(run_daily.ps1, 18:00)과 별도 작업으로 도는 게 중요하다 — 크롤이 아예
# 실행되지 않은 날에도 이게 돌아야 "크롤이 안 돌았다"를 알아챌 수 있다.
#
# python을 직접 부르지 않는 이유는 run_daily.ps1 주석 참고 (스케줄러 PATH에 없음).
$env:PYTHONIOENCODING = 'utf-8'
$env:PLAYWRIGHT_BROWSERS_PATH = 'C:\ohai\playwright-browsers'   # 이유는 run_daily.ps1 주석 참고
Set-Location C:\ohai\podium

function Resolve-Python {
    $c = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($c) { return $c }
    $c = & py -3 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $c -and (Test-Path $c.Trim())) { return $c.Trim() }
    return $null
}

$PY = Resolve-Python
if (-not $PY) {
    Add-Content -Path 'C:\ohai\podium\data\health.log' -Encoding utf8 `
        -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] FAIL 파이썬을 찾을 수 없다"
    exit 9
}

& $PY crawler\health_check.py --site
$code = $LASTEXITCODE

# 0=이상없음(또는 경미), 1=HIGH 발견, 2=official.json 없음, 그 외=헬스체크 자체가 죽음
if ($code -gt 2) {
    try {
        & $PY C:\ohai\telegram-notify\notify.py "포디엄 헬스체크 자체가 실패했다 (종료코드 $code) — 점검 필요"
    } catch { }
}
exit $code
