# Daily: crawl -> commit data -> push (updates live GitHub Pages site)
#
# 이 스크립트가 조용히 죽던 이유 두 가지 (2026-07-16 규명):
#  ① 작업 스케줄러가 띄운 프로세스의 PATH엔 python이 없다. 파이썬이 레지스트리
#     PATH(사용자·시스템)에 등록돼 있지 않아서, 터미널에서만 잡히고 스케줄 실행에선
#     `& python`이 해석 실패한다. → py.exe 런처(C:\WINDOWS)로 실제 경로를 얻어 쓴다.
#  ② 실패를 삼켰다. main.py가 죽어도 다음 줄로 넘어가 exit 0으로 끝났고, 스케줄러는
#     '성공(0x0)'이라 보고했다. → 단계마다 확인하고 실패 시 텔레그램 알림 + 비0 종료.
#
# PLAYWRIGHT_BROWSERS_PATH를 박아두는 이유: 기본 위치(AppData\Local\ms-playwright)에
# 설치된 브라우저는 Claude 앱(MSIX 컨테이너) 안에서만 보인다 — 실제로는
# AppData\Local\Packages\Claude_*\LocalCache\ 아래로 리디렉션돼 있어서, 스케줄러가
# 띄운 프로세스에는 '브라우저 없음'으로 보인다. jsfetch.py(JS 렌더링)가 조용히 실패했다.
$env:PYTHONIOENCODING = 'utf-8'
$env:PLAYWRIGHT_BROWSERS_PATH = 'C:\ohai\playwright-browsers'
Set-Location C:\ohai\podium

$RunLog = 'C:\ohai\podium\data\run_daily.log'
function Note($msg) {
    $line = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $msg
    Write-Output $line
    Add-Content -Path $RunLog -Value $line -Encoding utf8
}
function Alert($msg) {
    Note "FAIL $msg"
    if ($script:PY) {
        try { & $script:PY C:\ohai\telegram-notify\notify.py "포디엄 크롤 실패: $msg" | Out-Null } catch { }
    }
}
function Resolve-Python {
    $c = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($c) { return $c }
    $c = & py -3 -c "import sys; print(sys.executable)" 2>$null   # py.exe는 C:\WINDOWS에 있어 항상 잡힌다
    if ($LASTEXITCODE -eq 0 -and $c -and (Test-Path $c.Trim())) { return $c.Trim() }
    return $null
}

$PY = Resolve-Python
if (-not $PY) {
    Note "FAIL 파이썬을 찾을 수 없다 (PATH·py 런처 모두 실패) — 알림도 못 보낸다"
    exit 1
}

Note "크롤 시작 ($PY)"
& $PY crawler\main.py
if ($LASTEXITCODE -ne 0) {
    Alert "main.py 종료코드 $LASTEXITCODE — 데이터 갱신 안 됨"
    exit 1
}

& $PY crawler\export_sources_md.py
if ($LASTEXITCODE -ne 0) { Note "warn: export_sources_md.py 종료코드 $LASTEXITCODE (계속 진행)" }

# main.py가 0으로 끝났어도 결과 파일이 실제로 갱신됐는지 확인한다
if ((Get-Item C:\ohai\podium\data\official.json).LastWriteTime -lt (Get-Date).AddHours(-2)) {
    Alert "official.json이 갱신되지 않았다 (종료코드는 0)"
    exit 1
}

git add data/
$changed = git status --porcelain data/
if ($changed) {
    $today = Get-Date -Format 'yyyy-MM-dd'
    git -c user.name="ohmjin" -c user.email="ohmjin3141@naver.com" commit -m "auto: crawl $today"
    if ($LASTEXITCODE -ne 0) { Alert "커밋 실패"; exit 1 }
    git push origin main
    if ($LASTEXITCODE -ne 0) { Alert "푸시 실패 — 사이트에 반영 안 됨"; exit 1 }
    Note "크롤 완료 · 커밋+푸시됨"
} else {
    Note "크롤 완료 · 데이터 변경 없음"
}
