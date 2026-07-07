# Daily: crawl -> commit data -> push (updates live GitHub Pages site)
$env:PYTHONIOENCODING = 'utf-8'
Set-Location C:\ohai\classic-mule
& python crawler\main.py
& python crawler\export_sources_md.py
git add data/
$changed = git status --porcelain data/
if ($changed) {
    $today = Get-Date -Format 'yyyy-MM-dd'
    git -c user.name="ohmjin" -c user.email="ohmjin3141@naver.com" commit -m "auto: crawl $today"
    git push origin main
}
