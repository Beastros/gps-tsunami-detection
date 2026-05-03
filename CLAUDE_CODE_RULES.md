# Claude Code Rules — GPS Tsunami Detection Project

Lessons learned, Windows deployment pitfalls, and architecture reference for agents and humans editing this repo.

**Last updated:** 2026-05-03 · **Doc version:** V8+ (aligned with 8-channel stack, DYFI map, Poll Log redesign, `usgs_listener` near-miss fix)

---

## 1. Purpose of this file

- Avoid repeat mistakes (PowerShell quoting, UTF-8/BOM, CDDIS auth, claude.ai hyperlink mangling `.py` names).
- Record **two-root** layout: **pipeline folder** (where Task Scheduler runs) vs **git repo** (GitHub + Pages).
- Point to **authoritative** detail: `README.md` for user-facing architecture; this file for **operator and editor** hazards.

---

## 2. CRITICAL: claude.ai / chat UI breaks `.py` filenames in PowerShell

The UI turns tokens like `discord.py`, `notify.py`, `pipeline.py` into markdown links. Pasted commands break.

**Safe:** `setup_discord.py`, `fix_notify.py`, `run_pipeline_once.py`  
**Risky:** any `something.py` where `something` looks like a hostname or product name.

**Mitigations**

- Prefer **wildcard** paths: `Get-ChildItem "C:\...\repo" -Filter "pipeline*"` then pass `.FullName` to Python.
- Never put bare `*.py` names inside **quoted** PowerShell strings in copy-paste blocks.
- Rule of thumb: **patch `index.html` and any Unicode-heavy files with Python** (`open(..., encoding="utf-8", newline="\n")`), not `Set-Content` / `Out-File` (BOM and mojibake risk; see §19).

---

## 3. PowerShell vs CMD

| Avoid (CMD / wrong) | Use (PowerShell) |
|---------------------|-------------------|
| `&&` to chain | Separate lines or `;` |
| `copy /Y` | `Copy-Item ... -Force` |
| `dir /s /b` | `Get-ChildItem -Recurse -Filter "*.ext"` |

**Here-strings** for in-place patches (not nested `python -c "..."`):

```powershell
@'
p = r"C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\target.py"
s = open(p, encoding="utf-8").read()
s = s.replace("old", "new")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("OK")
'@ | Out-File patch_tmp.py -Encoding utf8
python patch_tmp.py
```

---

## 4. UTF-8 everywhere (Windows)

- **All** Python `open()` for text: `encoding="utf-8"` (or `utf-8-sig` when reading files that may have BOM — see §18).
- **`Path.write_text` / `read_text`:** pass `encoding="utf-8"` so repo JSON (`event_queue.json`, `poll_log.json`) is not corrupted by cp1252.
- **Logging:** `FileHandler(..., encoding="utf-8")`. Prefer ASCII in `log.info` on Windows if `StreamHandler` still hits cp1252.
- **`.env`:** Notepad may prepend BOM. When parsing manually, strip `b"\xef\xbb\xbf"` before decode (see `health_check.py` pattern).
- **This project:** avoid `python-dotenv` for `.env` if comments/blank lines cause noise — manual parse is fine (see existing `health_check.py`).

---

## 5. NASA CDDIS / RINEX

- **Not** basic `requests.get(url, auth=(user,pass))` alone — Earthdata session / redirect behavior needs the **session** pattern in `rinex_downloader.py` (re-send auth on redirect).
- After download: reject **`text/html`** bodies and magic byte `<` (HTML error page saved as `.Z`).
- **ncompress / decompress:** can return `None` on garbage input — validate magic / size before treating as success.

---

## 6. Paths (Mike’s machine — adjust if layout changes)

| Role | Path |
|------|------|
| **Pipeline** (Task Scheduler, `.env`, most runtime) | `C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\` |
| **Git repo** (commit, `index.html`, JSON pushed to GitHub) | `C:\Users\Mike\Desktop\repo\` |
| **RINEX per event** | `...\Earthquake Feed Listener Engine\rinex_live\<usgs_id>\` |
| **Downloads** (Chrome duplicates `file (1).py`) | `%USERPROFILE%\Downloads\` |

**Git remote:** `https://github.com/Beastros/gps-tsunami-detection` · **branch:** `main`  
**Pages:** `https://beastros.github.io/gps-tsunami-detection/`  
**Raw JSON for dashboard:** `https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/<file>.json`

After editing Python in the pipeline folder, **copy** into repo when the file is dual-homed:

```powershell
Copy-Item "C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\usgs_listener.py" "C:\Users\Mike\Desktop\repo\usgs_listener.py" -Force
```

Then `git add` / `commit` / `push` from **repo** directory.

---

## 7. Environment variables (`.env` in pipeline folder — never commit)

Use **your own** credentials; placeholders only in docs:

```
EARTHDATA_USER=<earthdata username>
EARTHDATA_PASS=<earthdata password>
NOTIFY_EMAIL=<smtp sender for alerts>
NOTIFY_APP_PASSWORD=<app password if Gmail>
DISCORD_WEBHOOK_URL=<webhook URL — rotate if ever pasted in chat>
```

- **Public inquiries** (footer on `index.html`, README): **`emfproj@proton.me`** — not the same as `NOTIFY_EMAIL` unless you intentionally use Proton SMTP for sends.
- Regenerate **Discord webhook** if it was ever exposed in a chat log.

---

## 8. Pipeline architecture (current)

**Frozen detector params:** 2025-04-22 (see `detector_runner.py` / `README.md`).

**Stages (high level)** — see `README.md` for exact wording:

1. `usgs_listener` — USGS `4.5_week` feed; Mw **6.5+** candidates; ShakeMap / tsunamigenic gate; **`recent_seismicity`** near-miss log for `poll_log.json`; **`pending`** per poll row; UTF-8 JSON; **fast_poll.json** on Mw **≥6** Pacific.
2. `rinex_downloader` — CDDIS RINEX.
3. `detector_runner` — 8-channel fusion (TEC + space weather + constellations + dTEC + DART + ionosonde + ShakeMap prior; DYFI fusion fields where applicable).
4. `scorer` — tide gauges at T+24h → `running_log.json`.
5. `dyfi_poller` — `dyfi_pings.json` for **GitHub Pages** map (see §10).
6. Notify — email + Discord; pipeline errors to Discord.

**Task Scheduler:** task name **`GPS Tsunami Master`** · target **`run_and_push.bat`** · ~15 min.

**Live log file:** `task_runner.log` (from batch job) is the right freshness signal for scheduled runs — not only `pipeline.log` from manual runs.

---

## 9. `usgs_listener.py` / `poll_log.json` — near-misses (fixed 2026-05)

**Bug (historical):** `near_misses.append(...)` lived in an `else` branch incorrectly tied to a **duplicate** `if mag >= FAST_POLL_MW_TRIGGER`, so **Mw ≥ 6** events **never** populated `recent_seismicity` → empty Poll Log map / table.

**Fix:** near-miss logging runs when `assess_event` returns **no** candidate; Pacific filter applied; single fast-poll block; duplicate `_activate_fast_poll` removed.

**Contract:** `write_poll_log` appends `pending` (queue events not `scored`) alongside `total_queued` / `scored`.

---

## 10. DYFI poller (`dyfi_poller.py`)

- Writes **`dyfi_pings.json`** into the repo path set by **`REPO_DIR`** at top of file (default `C:\Users\Mike\Desktop\repo`). If repo lives elsewhere, **edit `REPO_DIR`** or the file will land in the wrong place.
- **Retention:** `LOOKBACK_HRS` / **`MAX_PING_AGE_HRS`** (24h) — pings older than max age are omitted on next run.
- **MIN_FELT** (e.g. 10): below that, no map ping — quiet map is often “not enough DYFI responses,” not a broken fetch.

---

## 11. Dashboard (`index.html` on GitHub Pages)

- Loads **`poll_log.json`**, **`running_log.json`**, **`event_queue.json`**, **`dyfi_pings.json`** from **raw** `main` URLs.
- **`renderDyfiPings`** must use **`window._mapSvg`** / **`window._mapProj`** after `initMap` completes.
- **Poll Log tab:** hero stats, sparkline, sticky scroll tables, optional **metadata rail** (wide screens); **near-miss** map colors: bright gold / orange for visibility.
- **`git pull` merge:** if Vim opens for merge message → **`Esc`**, **`:wq`**, **Enter**. Or `git config merge.autoEdit false` to skip editor.

---

## 12. `health_check.py`

- **23 sections** (includes DYFI checker / poller blocks). Section **numbers in script** may not be contiguous — trust the printed headers.
- **`PIPELINE_DIR`** / **`REPO_DIR`** are **hardcoded Windows paths** at top of file — update if machine layout changes.

---

## 13. USGS API gotcha

**Do not** pass FDSNWS datetime strings through `urllib.parse.urlencode` — colons become `%3A` and queries can return **empty** silently.

Prefer summary feeds (`4.5_week.geojson`, etc.) or build query URLs with **f-strings** so `:` stays literal.

---

## 14. Detector / scoring facts (unchanged core)

- **Station keys** in pairs / constraints: often **lowercase** in code; **`STATION_ZONE_CONSTRAINTS`** uses **UPPERCASE** — match conventions when patching.
- **`running_log.json`:** with zero scored live events, mtime stays old — **not** a health failure by itself.
- **Backtest:** historical DART/ionosonde often unavailable — many published confidences are **TEC-heavy**; live runs use full fusion when APIs respond.

---

## 15. Deploy scripts (when you use them)

- **Self-delete** stale copies from `Downloads` (`file.py`, `file (1).py`, …) at start of script.
- Prefer **base64** embedding for multi-line file drops (avoid triple-quoted embeds that break on quotes inside content).
- Verify embedded Python: `ast.parse(...)` before running.
- **Never** name deploy scripts `discord.py`, `notify.py`, etc. (§2).

---

## 16. Git / repo hygiene

- End sessions: remove stray `patch_*.py` from repo root if created.
- After `health_check.py` surgery, grep or read file to confirm new section exists before commit.
- **LF/CRLF warnings** on `git add` from Windows are usually harmless if files are UTF-8 text.

---

## 17. Session changelog (high level)

| Phase | Notes |
|-------|--------|
| V1–V2 | TEC coherence, Kp, fusion groundwork |
| V3 | Discord, backtest, CDDIS session auth |
| V4–V5 | More stations, HOLB zone, adaptive thresholds, map, near-miss concept |
| V6 | Fast poll, README expansion |
| **2026-05** | UTF-8 JSON in `usgs_listener`; **`pending`** on polls; **near-miss control-flow fix**; **`dyfi_poller`** 24h retention; **`index.html`** pipeline refresh, Events table, DYFI map hook, Poll Log redesign, brighter seismic rings, metadata rail; footer **emfproj@proton.me**; **README** sync (8-ch, 23 health sections) |

---

## 18. Quick reference — files dual-homed vs repo-only

**Typical sync:** pipeline folder has the runnable copy; **commit from `Desktop\repo`** after `Copy-Item`.

| Often edited in both | Repo / Pages mainly |
|----------------------|---------------------|
| `pipeline.py`, `usgs_listener.py`, `rinex_downloader.py`, `detector_runner.py`, `scorer.py`, `space_weather.py`, `ionosonde_checker.py`, `dyfi_poller.py`, `dyfi_checker.py`, `notify*.py` | `index.html`, `poll_log.json`, `running_log.json`, `event_queue.json`, `dyfi_pings.json`, `README.md` |

**Repo-only / docs:** `CLAUDE_CODE_RULES.md`, `scripts/` research utilities, figures.

---

*This file is operator guidance, not a scientific methods document. For frozen parameters and validation claims, use `README.md` and `detector_params.py` / comments in frozen code.*
