"""
Automated RINEX Downloader
===========================
Reads event_queue.json, finds events ready for RINEX download,
and pulls the appropriate files from NASA CDDIS.

Run after usgs_listener.py has populated the queue:
  python rinex_downloader.py

Or point at a specific event:
  python rinex_downloader.py --event <usgs_id>

Requires NASA Earthdata credentials in environment:
  set EARTHDATA_USER=mthhorn
  set EARTHDATA_PASS=yourpassword

Or in a .env file (never commit this):
  EARTHDATA_USER=mthhorn
  EARTHDATA_PASS=yourpassword
"""

import json
import os
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:
    print("pip install requests")
    raise

EVENT_QUEUE_FILE = "event_queue.json"
RINEX_BASE_DIR   = "rinex_live"
LOG_FILE         = "downloader.log"
CDDIS_BASE       = "https://cddis.nasa.gov/archive/gps/data/daily"

# Stations to attempt per corridor
CORRIDOR_STATIONS = {
    "guam": ["guam", "kwj1", "noum", "holb", "mkea", "kokb", "hnlc"],
    "chat": ["chat", "auck", "mkea", "kokb", "hnlc"],
    "thti": ["thti", "thtg", "auck", "noum", "mkea", "kokb"],
    None:   ["mkea", "kokb", "hnlc", "guam"],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

def load_queue():
    if not Path(EVENT_QUEUE_FILE).exists():
        log.error(f"{EVENT_QUEUE_FILE} not found — run usgs_listener.py first")
        return None
    return json.loads(Path(EVENT_QUEUE_FILE).read_text())

def save_queue(q):
    Path(EVENT_QUEUE_FILE).write_text(json.dumps(q, indent=2))

def get_credentials():
    user = os.environ.get("EARTHDATA_USER")
    pwd  = os.environ.get("EARTHDATA_PASS")
    if not user or not pwd:
        # Try .env file — check script dir AND cwd
        script_dir = Path(__file__).parent
        for env_file in [Path(".env"), script_dir / ".env"]:
            if env_file.exists():
                log.info(f"Loading credentials from {env_file.resolve()}")
                for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                    line = line.strip()
                    if line.startswith("EARTHDATA_USER="):
                        user = line.split("=",1)[1].strip()
                    if line.startswith("EARTHDATA_PASS="):
                        pwd = line.split("=",1)[1].strip()
                if user and pwd:
                    break
    if not user or not pwd:
        log.error("No Earthdata credentials found.")
        log.error("Set EARTHDATA_USER and EARTHDATA_PASS environment variables")
        log.error("Or create a .env file with those keys")
        return None, None
    return user, pwd

def quake_to_doy(quake_utc_str):
    """Convert UTC string to year, day-of-year, 2-digit year."""
    dt = datetime.fromisoformat(quake_utc_str.replace("Z", "+00:00"))
    doy = dt.timetuple().tm_yday
    yr2 = str(dt.year)[-2:]
    return dt.year, doy, yr2, dt

def build_cddis_url(year, doy, yr2, station, ftype="o"):
    """Build CDDIS URL for a station/day observation or nav file."""
    fname = f"{station}{doy:03d}0.{yr2}{ftype}.Z"
    return f"{CDDIS_BASE}/{year}/{doy:03d}/{yr2}{ftype}/{fname}", fname

def download_file(url, dest_path, auth):
    """Download a single file from CDDIS. Returns True on success."""
    if dest_path.exists():
        log.info(f"  {dest_path.name} already exists, skipping")
        return True
    try:
        import requests as _req
        class _S(_req.Session):
            def rebuild_auth(self, pr, r):
                if self.auth: pr.prepare_auth(self.auth, pr.url)
        _sess = _S()
        _sess.auth = auth
        r = _sess.get(url, timeout=60, stream=True)
        if r.status_code == 404:
            log.debug(f"  404: {dest_path.name}")
            return False
        r.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
        size_kb = dest_path.stat().st_size / 1024
        log.info(f"  ✓ {dest_path.name}  ({size_kb:.0f} KB)")
        return True
    except Exception as e:
        log.warning(f"  ✗ {dest_path.name}: {e}")
        return False

def download_event(event, auth):
    """Download all RINEX files for a single event. Returns file count."""
    year, doy, yr2, quake_dt = quake_to_doy(event["quake_utc"])
    anchor = event.get("primary_anchor")
    stations = CORRIDOR_STATIONS.get(anchor, CORRIDOR_STATIONS[None])

    event_dir = Path(RINEX_BASE_DIR) / event["usgs_id"]
    event_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"\nDownloading RINEX for {event['usgs_id']}")
    log.info(f"  {event['place']}  Mw{event['magnitude']}  {event['quake_utc'][:16]}")
    log.info(f"  Year={year} DOY={doy} stations={stations}")

    downloaded = 0
    for sid in stations:
        for ftype in ["o", "n"]:
            url, fname = build_cddis_url(year, doy, yr2, sid, ftype)
            dest = event_dir / fname
            if download_file(url, dest, auth):
                downloaded += 1
            time.sleep(0.5)  # be polite to CDDIS

    # For late-UTC events, also grab next day's files
    quake_hour = quake_dt.hour
    if quake_hour >= 18:  # detection window crosses midnight UTC
        next_dt = quake_dt + timedelta(days=1)
        next_doy = next_dt.timetuple().tm_yday
        next_yr2 = str(next_dt.year)[-2:]
        log.info(f"  Late UTC event — also downloading day {next_doy} files")
        for sid in stations[:3]:  # key stations only for next day
            for ftype in ["o", "n"]:
                url, fname = build_cddis_url(next_dt.year, next_doy, next_yr2, sid, ftype)
                dest = event_dir / fname
                if download_file(url, dest, auth):
                    downloaded += 1
                time.sleep(0.5)

    log.info(f"  Downloaded {downloaded} files to {event_dir}")
    return downloaded, str(event_dir)

def is_ready_to_download(event):
    """
    Check if enough time has passed post-quake to expect RINEX availability.
    CDDIS typically has files within 1-2 hours of day end.
    We wait until TEC onset window start + 30 min, minimum 3h post-quake.
    """
    if event.get("rinex_downloaded"):
        return False
    if event.get("status") not in ["queued", "pending_rinex"]:
        return False

    quake_time = datetime.fromisoformat(event["quake_utc"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    hours_since = (now - quake_time).total_seconds() / 3600

    window = event.get("detection_window") or {}
    download_after_h = window.get("rinex_download_after_h", 3.0)
    min_wait_h = max(download_after_h, 3.0)

    return hours_since >= min_wait_h

def main(event_id=None):
    log.info("="*55)
    log.info("GPS Tsunami Detector — RINEX Downloader")
    log.info("="*55)

    user, pwd = get_credentials()
    if not user:
        return
    auth = HTTPBasicAuth(user, pwd)

    queue = load_queue()
    if not queue:
        return

    events = queue["events"]
    if event_id:
        events = [e for e in events if e["usgs_id"] == event_id]
        if not events:
            log.error(f"Event {event_id} not found in queue")
            return

    ready = [e for e in events if is_ready_to_download(e)]
    log.info(f"Queue: {len(events)} events, {len(ready)} ready for download")

    if not ready:
        log.info("No events ready for download yet")
        for e in events:
            quake_time = datetime.fromisoformat(e["quake_utc"].replace("Z", "+00:00"))
            hours_since = (datetime.now(timezone.utc) - quake_time).total_seconds()/3600
            w = e.get("detection_window") or {}
            wait = w.get("rinex_download_after_h", 3.0)
            log.info(f"  {e['usgs_id']}  {hours_since:.1f}h elapsed, "
                     f"need {wait:.1f}h  status={e['status']}")
        return

    for event in ready:
        count, event_dir = download_event(event, auth)
        if count > 0:
            event["rinex_downloaded"] = True
            event["rinex_dir"] = event_dir
            event["rinex_download_utc"] = datetime.now(timezone.utc).isoformat()
            event["status"] = "rinex_ready"
            save_queue(queue)
            log.info(f"Updated queue: {event['usgs_id']} → rinex_ready")
        else:
            log.warning(f"No files downloaded for {event['usgs_id']}")
            event["status"] = "rinex_failed"
            save_queue(queue)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", help="Process specific USGS event ID")
    args = parser.parse_args()
    main(event_id=args.event)
