# Discord webhook disconnect — one command fix

## Paste this in PowerShell (Admin not required)

```powershell
irm https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/cursor/discord-webhook-spam-fix-fa7f/scripts/Fix-DiscordWebhook.ps1 | iex
```

The script will:
1. Ask for your **new** Discord webhook URL (get it from Discord → channel → Integrations → Webhooks)
2. Test the URL
3. Update `.env` in your pipeline + repo folders
4. Download the fixed `notify_discord.py`, `pipeline.py`, `health_check.py`
5. Clear the circuit-breaker state file
6. Try to update the GitHub secret (if `gh` is logged in)
7. Run `health_check.py`

## If you already have the URL on your clipboard

```powershell
$u = Read-Host "Paste webhook URL"
irm https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/cursor/discord-webhook-spam-fix-fa7f/scripts/Fix-DiscordWebhook.ps1 -OutFile $env:TEMP\Fix-DiscordWebhook.ps1
& $env:TEMP\Fix-DiscordWebhook.ps1 -WebhookUrl $u
```

## Double-click option

Copy `scripts\Fix-DiscordWebhook.cmd` from the repo to your Desktop and double-click it.
