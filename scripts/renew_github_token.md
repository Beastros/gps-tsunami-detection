# Renew GitHub push credentials (Windows)

Use this when `run_and_push.bat` logs `git push FAILED` or `health_check.py` section [15] reports push auth failure.

## 1. Create a new token

1. Open https://github.com/settings/tokens
2. **Generate new token (classic)** with scope: `repo`
   - Or use a **fine-grained** token on `Beastros/gps-tsunami-detection` with **Contents: Read and write**
3. Copy the token immediately (GitHub shows it once)

## 2. Update Windows Credential Manager

```powershell
# Optional: remove stale github.com entry so Git prompts fresh
cmdkey /list | Select-String github
cmdkey /delete:git:https://github.com
```

Then either:

- **Control Panel** → Credential Manager → Windows Credentials → `git:https://github.com` → Edit  
  - Username: your GitHub username  
  - Password: the **new PAT**

Or let Git prompt on the next push:

```powershell
cd C:\Users\Mike\Desktop\repo
git push --dry-run origin main
```

When prompted, use your GitHub username and paste the PAT as the password.

## 3. Verify

```powershell
cd C:\Users\Mike\Desktop\repo
git push --dry-run origin main
python health_check.py
.\run_and_push.bat
```

Check `task_runner.log` — there should be no `git push FAILED` line.

## What stays connected without your PAT

GitHub Actions (`Pipeline poll and push` workflow) still commits USGS/DYFI poll updates every 15 minutes using the built-in `GITHUB_TOKEN`. Your PAT is only needed for **Windows Task Scheduler** pushes that upload full pipeline JSON (including RINEX-backed results from your local `.env`).
