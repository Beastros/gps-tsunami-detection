#Requires -Version 5.1
<#
Download sync-fix.patch and apply on hantavirus-dashboard main.

.EXAMPLE
  cd C:\Users\Mike\dev\hantavirus-dashboard
  powershell -ExecutionPolicy Bypass -File .\scripts\Apply-SyncFix-FromUrl.ps1
#>
$ErrorActionPreference = 'Stop'

$PatchUrl = 'https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/hantavirus-dashboard-patches/sync-fix.patch'

$Root = (Get-Location).Path
if (-not (Test-Path (Join-Path $Root '.git'))) {
    throw "Run from hantavirus-dashboard repo root (folder with .git). Current: $Root"
}
if (-not (Test-Path (Join-Path $Root 'package.json'))) {
    throw 'This does not look like hantavirus-dashboard (missing package.json).'
}

$scriptsDir = Join-Path $Root 'scripts'
New-Item -ItemType Directory -Force -Path $scriptsDir | Out-Null
$patch = Join-Path $scriptsDir 'sync-fix.patch'

Write-Host "Downloading patch from gps-tsunami-detection..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $PatchUrl -OutFile $patch -UseBasicParsing

git checkout main
git pull origin main
git apply --check $patch
if ($LASTEXITCODE -ne 0) {
    throw 'Patch does not apply. Run: git pull origin main  then retry.'
}
git apply $patch
git add -A
git status
git commit -m "fix: sync dashboard data on each ingest (jsDelivr, publish-pages, region rollup)"
git push origin main
Write-Host 'Done. Open Actions: Ingest + Pages should run. Hard-refresh https://beastros.github.io/hantavirus-dashboard/' -ForegroundColor Green
