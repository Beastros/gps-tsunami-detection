# Fix Discord webhook disconnect spam

## Symptoms

- Constant Discord mobile notifications about webhook disconnect / failed delivery
- Often after regenerating a webhook in Discord channel settings

## Root cause

Two runners were both posting every 15 minutes:

1. **Windows Task Scheduler** (`run_and_push.bat` → `pipeline.py`)
2. **GitHub Actions** (`Pipeline poll and push` workflow)

If the webhook URL in `.env` or the `DISCORD_WEBHOOK_URL` GitHub secret is **stale** (old URL after regenerate), Discord gets hammered with failed posts and may spam disconnect notices.

## Fix (do all three)

### 1. Regenerate webhook in Discord

1. Discord → your alerts channel → **Edit Channel** → **Integrations** → **Webhooks**
2. Delete the old webhook (or create a new one)
3. Copy the **new** webhook URL

### 2. Update Windows `.env`

In your pipeline folder (e.g. `C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\.env`):

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/NEW_ID/NEW_TOKEN
```

Also update the same line in your git repo copy if you keep a separate `.env` there.

### 3. Update or remove GitHub secret

GitHub → **Beastros/gps-tsunami-detection** → **Settings** → **Secrets** → **Actions**

- Either **update** `DISCORD_WEBHOOK_URL` to the new URL
- Or **delete** the secret (CI no longer sends phone alerts after this patch)

After the code fix merges, CI sets `DISCORD_ALERTS_ENABLED=0` — only your Windows machine should push to your phone.

### 4. Clear circuit-breaker state (optional)

If spam continues after updating the URL, delete `.discord_webhook_state.json` in the pipeline folder (created when a dead webhook was detected).

### 5. Verify

```powershell
cd C:\Users\Mike\Desktop\repo
python health_check.py
```

Section **[ 13 ] Discord Webhook** should show `OK` with your channel name.

Run one pipeline cycle and confirm `task_runner.log` / `pipeline.log` has no repeated `Discord webhook failed: HTTP 401`.
