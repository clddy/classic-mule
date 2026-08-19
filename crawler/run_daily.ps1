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
# 무인 실행에서 git이 자격증명을 물으면 안 된다. 2026-08-17 18:00 크롤은 GCM이
# 로그인 창을 띄웠는데 스케줄 작업은 창이 숨겨져 있어 아무도 못 눌렀고,
# "User cancelled dialog" → 푸시 실패로 하루치가 로컬에만 남았다. 물어보지 말고
# 그 자리에서 실패하게 해서 알림이 정확한 사유를 담게 한다.
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'
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

# PC가 꺼져 있던 날 Actions 백업이 크롤·푸시해 뒀을 수 있다. 먼저 원격을 당겨오지 않으면
# (1) 이번 크롤이 낡은 이전 수집분을 승계하고 (2) 마지막 푸시가 거부된다. (2026-07-29)
git pull --ff-only origin main 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Note "warn: pull 실패 — 로컬이 갈라졌을 수 있다 (계속 진행)" }

# 어제 푸시가 실패했다면 커밋은 로컬에 남아 있다. 오늘 수집분에 변경이 없으면
# 아래 커밋 블록을 안 타므로 그 커밋은 영영 안 올라간다 — 여기서 먼저 밀어준다.
$pending = git rev-list --count origin/main..HEAD
if ($pending -and [int]$pending -gt 0) {
    Note "밀리지 않은 커밋 $pending 개 — 먼저 푸시 시도"
    git push origin main
    if ($LASTEXITCODE -ne 0) { Note "warn: 밀린 커밋 푸시 실패 (크롤은 계속 진행)" }
    else { Note "밀린 커밋 $pending 개 푸시됨" }
}

Note "크롤 시작 ($PY)"
& $PY crawler\main.py
if ($LASTEXITCODE -ne 0) {
    Alert "main.py 종료코드 $LASTEXITCODE — 데이터 갱신 안 됨"
    exit 1
}

& $PY crawler\export_sources_md.py
if ($LASTEXITCODE -ne 0) { Note "warn: export_sources_md.py 종료코드 $LASTEXITCODE (계속 진행)" }

# 방문 데이터 수집 (GA4) — 미설정이면 스스로 스킵하므로 실패해도 크롤에 영향 없음
& $PY crawler\traffic.py
if ($LASTEXITCODE -ne 0) { Note "warn: traffic.py 종료코드 $LASTEXITCODE (계속 진행)" }

# 검색 노출·검색어 (Search Console) — GA4에 없는 '들어오기 전' 데이터
& $PY crawler\gsc.py
if ($LASTEXITCODE -ne 0) { Note "warn: gsc.py 종료코드 $LASTEXITCODE (계속 진행)" }

# 대시보드용 업로드 — 방문 통계는 공개 저장소에 못 올리므로 Worker(KV)로 보낸다.
# analytics.html이 관리자 열쇠로 이걸 받아 그린다. 열쇠 없으면 스스로 스킵.
& $PY crawler\dash_upload.py
if ($LASTEXITCODE -ne 0) { Note "warn: dash_upload.py 종료코드 $LASTEXITCODE (계속 진행)" }

# 연습실 수집 — 서울 yeyak + 공유누리 전국 순회 + 시설 묶음 재생성.
# 2026-08-03 사용자 지시로 매일 실행 (수분 수준이라 부담 없음).
# (2026-08-02 이식 당시 yeyak이 스케줄에 안 들어가 3주 낡은 채 방치돼 있었다)
Note "연습실 수집"
& $PY crawler\practice_yeyak.py
if ($LASTEXITCODE -ne 0) { Note "warn: practice_yeyak.py 종료코드 $LASTEXITCODE (계속 진행)" }
& $PY crawler\practice_sweep.py
if ($LASTEXITCODE -ne 0) { Note "warn: practice_sweep.py 종료코드 $LASTEXITCODE (계속 진행)" }
& $PY crawler\build_practice_eshare.py
if ($LASTEXITCODE -ne 0) { Note "warn: build_practice_eshare.py 종료코드 $LASTEXITCODE (계속 진행)" }

# main.py가 0으로 끝났어도 결과 파일이 실제로 갱신됐는지 확인한다
if ((Get-Item C:\ohai\podium\data\official.json).LastWriteTime -lt (Get-Date).AddHours(-2)) {
    Alert "official.json이 갱신되지 않았다 (종료코드는 0)"
    exit 1
}

# 정적 산출물(staticgen)까지 함께 커밋해야 검색 봇용 목록·공고 페이지가 갱신된다 —
# data/ 만 넣던 탓에 로컬 크롤로는 p/·jobs.html·sitemap이 낡은 채로 남았다 (2026-07-29)
#
# crawler/ 도 함께 커밋한다 (2026-08-02): 크롤러 코드 수정이 자동 커밋 경로에 없어서
# attach.py OCR 수정이 7일간 로컬에만 있었고, 그동안 Actions 백업 크롤(PC 꺼진 날)은
# 커밋된 낡은 추출기로 돌았다. 비밀은 .gitignore(crawler/.env·쿠키·캐시)가 걸러준다.
git add data/ p/ crawler/ jobs.html index.html sitemap.xml robots.txt
$changed = git status --porcelain data/ p/ crawler/ jobs.html index.html sitemap.xml robots.txt
if ($changed) {
    $today = Get-Date -Format 'yyyy-MM-dd'
    git -c user.name="ohmjin" -c user.email="ohmjin3141@naver.com" commit -m "auto: crawl $today"
    if ($LASTEXITCODE -ne 0) { Alert "커밋 실패"; exit 1 }
    git push origin main
    if ($LASTEXITCODE -ne 0) { Alert "푸시 실패 — 사이트에 반영 안 됨"; exit 1 }
    Note "크롤 완료 · 커밋+푸시됨"

    # 구글에 '이 공고 바뀌었다/내렸다'를 직접 알린다. 푸시 뒤에 두는 이유는, 구글이
    # 통보를 받고 바로 가지러 오는데 그때 새 페이지가 올라가 있어야 하기 때문이다.
    # 자격증명이 없으면 스스로 건너뛰므로 실패로 치지 않는다.
    & $PY "$PSScriptRoot\gindex.py"
    if ($LASTEXITCODE -ne 0) { Note "warn: gindex.py 종료코드 $LASTEXITCODE (계속 진행)" }

    # 네이버·빙에도 알린다(IndexNow). 구글은 위 gindex 가 맡는다 — 구글은 이 규격을 안 쓴다.
    & $PY "$PSScriptRoot\indexnow.py"
    if ($LASTEXITCODE -ne 0) { Note "warn: indexnow.py 종료코드 $LASTEXITCODE (계속 진행)" }
} else {
    Note "크롤 완료 · 데이터 변경 없음"
}
