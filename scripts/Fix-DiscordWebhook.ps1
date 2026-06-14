# Fix-DiscordWebhook.ps1
# One-shot fix for Discord webhook disconnect spam on Windows.
#
# Usage (paste in PowerShell):
#   irm https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/cursor/discord-webhook-spam-fix-fa7f/scripts/Fix-DiscordWebhook.ps1 | iex
#
# Or with your new webhook URL already copied:
#   & $env:TEMP\Fix-DiscordWebhook.ps1 -WebhookUrl "https://discord.com/api/webhooks/ID/TOKEN"

[CmdletBinding()]
param(
    [string]$WebhookUrl,
    [string]$PipelineDir = "",
    [string]$RepoDir = "",
    [switch]$SkipGitHubSecret
)

$ErrorActionPreference = "Stop"
$Branch = "cursor/discord-webhook-spam-fix-fa7f"
$RawBase = "https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/$Branch"
$FilesToSync = @(
    "notify_discord.py",
    "pipeline.py",
    "health_check.py"
)

function Write-Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "OK  $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }

function Resolve-DefaultDirs {
    $candidates = @(
        "C:\Users\Mike\Desktop\Earthquake Feed Listener Engine",
        "C:\Users\Mike\Desktop\repo",
        (Join-Path $env:USERPROFILE "Desktop\repo"),
        (Join-Path $env:USERPROFILE "Desktop\Earthquake Feed Listener Engine")
    )
    if (-not $PipelineDir) {
        foreach ($p in $candidates) {
            if (Test-Path (Join-Path $p "pipeline.py")) { $script:PipelineDir = $p; break }
        }
    }
    if (-not $RepoDir) {
        foreach ($p in $candidates) {
            if (Test-Path (Join-Path $p ".git")) { $script:RepoDir = $p; break }
        }
    }
    if (-not $PipelineDir -and $RepoDir) { $PipelineDir = $RepoDir }
    if (-not $RepoDir -and $PipelineDir) { $RepoDir = $PipelineDir }
}

function Update-EnvWebhook([string]$dir, [string]$url) {
    $envPath = Join-Path $dir ".env"
    $line = "DISCORD_WEBHOOK_URL=$url"
    if (-not (Test-Path $envPath)) {
        New-Item -ItemType File -Path $envPath -Force | Out-Null
        Set-Content -Path $envPath -Value $line -Encoding utf8
        return "created"
    }
    $raw = Get-Content -Path $envPath -Raw -Encoding UTF8
    if ($raw -match "(?m)^DISCORD_WEBHOOK_URL=") {
        $new = [regex]::Replace($raw, "(?m)^DISCORD_WEBHOOK_URL=.*", $line)
    } else {
        $new = $raw.TrimEnd() + "`n" + $line + "`n"
    }
    [System.IO.File]::WriteAllText($envPath, $new, [System.Text.UTF8Encoding]::new($false))
    return "updated"
}

function Sync-FileFromGitHub([string]$destDir, [string]$name) {
    $url = "$RawBase/$name"
    $dest = Join-Path $destDir $name
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

function Test-DiscordWebhook([string]$url) {
    try {
        $req = [System.Net.WebRequest]::Create($url)
        $req.Method = "GET"
        $req.UserAgent = "gps-tsunami-fix-script"
        $req.Timeout = 15000
        $resp = $req.GetResponse()
        $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
        $body = $reader.ReadToEnd()
        $reader.Close()
        $resp.Close()
        if ($body -match '"name"\s*:\s*"([^"]+)"') {
            return $Matches[1]
        }
        return "valid"
    } catch [System.Net.WebException] {
        $code = [int]$_.Exception.Response.StatusCode
        throw "Webhook test failed (HTTP $code). Regenerate in Discord and paste the full URL."
    }
}

Write-Host ""
Write-Host "GPS Tsunami — Discord webhook fix" -ForegroundColor White
Write-Host "=================================" -ForegroundColor White

Resolve-DefaultDirs
if (-not $PipelineDir -or -not (Test-Path $PipelineDir)) {
    $PipelineDir = Read-Host "Pipeline folder path (folder containing pipeline.py)"
}
if (-not (Test-Path (Join-Path $PipelineDir "pipeline.py"))) {
    throw "pipeline.py not found under $PipelineDir"
}
Write-Ok "Pipeline folder: $PipelineDir"
if ($RepoDir -and (Test-Path $RepoDir)) { Write-Ok "Repo folder: $RepoDir" }

if (-not $WebhookUrl) {
    Write-Step "Paste your NEW Discord webhook URL"
    Write-Host "  Discord -> channel -> Edit -> Integrations -> Webhooks -> Copy Webhook URL"
    $WebhookUrl = Read-Host "Webhook URL"
}
$WebhookUrl = $WebhookUrl.Trim()
if ($WebhookUrl -notmatch "^https://discord\.com/api/webhooks/\d+/") {
    throw "That does not look like a Discord webhook URL."
}

Write-Step "Testing webhook"
$channel = Test-DiscordWebhook -url $WebhookUrl
Write-Ok "Webhook works — channel: $channel"

Write-Step "Updating .env files"
foreach ($dir in @($PipelineDir, $RepoDir) | Select-Object -Unique) {
    if ($dir -and (Test-Path $dir)) {
        $action = Update-EnvWebhook -dir $dir -url $WebhookUrl
        Write-Ok ".env $action in $dir"
    }
}

Write-Step "Downloading fixed pipeline files from GitHub"
$targets = @($PipelineDir)
if ($RepoDir -and $RepoDir -ne $PipelineDir) { $targets += $RepoDir }
foreach ($dir in $targets | Select-Object -Unique) {
    foreach ($f in $FilesToSync) {
        Sync-FileFromGitHub -destDir $dir -name $f
        Write-Ok "Synced $f -> $dir"
    }
    $state = Join-Path $dir ".discord_webhook_state.json"
    if (Test-Path $state) {
        Remove-Item $state -Force
        Write-Ok "Removed stale $state"
    }
}

if (-not $SkipGitHubSecret) {
    Write-Step "GitHub secret (optional — stops CI double-posting)"
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh) {
        $repoRoot = if ($RepoDir -and (Test-Path (Join-Path $RepoDir ".git"))) { $RepoDir } else { $null }
        if ($repoRoot) {
            Push-Location $repoRoot
            try {
                echo $WebhookUrl | gh secret set DISCORD_WEBHOOK_URL 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { Write-Ok "GitHub secret DISCORD_WEBHOOK_URL updated" }
                else { Write-Warn "Could not set GitHub secret — run: gh secret set DISCORD_WEBHOOK_URL" }
            } finally { Pop-Location }
        } else {
            Write-Warn "No git repo found — skip GitHub secret or set manually in repo Settings -> Secrets"
        }
    } else {
        Write-Warn "gh CLI not installed — skip GitHub secret or install gh and run: gh secret set DISCORD_WEBHOOK_URL"
    }
}

Write-Step "Running health check"
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py -3" } else { "python" }
$hc = Join-Path $PipelineDir "health_check.py"
if (Test-Path $hc) {
    Push-Location $PipelineDir
    try { Invoke-Expression "$py `"$hc`"" } finally { Pop-Location }
} else {
    Write-Warn "health_check.py not found — skipped"
}

Write-Host ""
Write-Host "DONE. Discord webhook fix applied." -ForegroundColor Green
Write-Host "If Task Scheduler is running, the next 15-min cycle should stop spamming disconnect errors." -ForegroundColor Green
Write-Host ""
