# Repair-PipelineJson.ps1 - fix empty/corrupt event_queue.json and stale poll_log.json
# ASCII-only for Windows PowerShell 5.1

param(
    [string]$PipelineDir = "C:\Users\Mike\Desktop\Earthquake Feed Listener Engine",
    [string]$RepoDir = "C:\Users\Mike\Desktop\repo"
)

$ErrorActionPreference = "Stop"
$Base = "https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main"
$Files = @("event_queue.json", "poll_log.json", "running_log.json", "dyfi_pings.json")

function Write-Ok($m) { Write-Host "OK  $m" -ForegroundColor Green }

Write-Host ""
Write-Host "GPS Tsunami - repair pipeline JSON from GitHub" -ForegroundColor White
Write-Host "==============================================" -ForegroundColor White

foreach ($dir in @($PipelineDir, $RepoDir)) {
    if (-not (Test-Path $dir)) {
        Write-Host "SKIP  $dir (not found)" -ForegroundColor Yellow
        continue
    }
    Write-Host ""
    Write-Host "==> $dir" -ForegroundColor Cyan
    foreach ($f in $Files) {
        $url = "$Base/$f"
        $dest = Join-Path $dir $f
        try {
            Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
            Write-Ok "Downloaded $f"
        } catch {
            Write-Host "SKIP  $f (not on GitHub yet)" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "==> Running one USGS poll cycle" -ForegroundColor Cyan
Push-Location $PipelineDir
try {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 usgs_listener.py --once
    } else {
        python usgs_listener.py --once
    }
    Write-Ok "usgs_listener --once finished"
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "DONE. Re-run: py -3 health_check.py" -ForegroundColor Green
Write-Host ""
