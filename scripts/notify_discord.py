"""
Discord webhook alerts for detector predictions and pipeline errors.
"""
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


def _load_env(path=".env"):
    try:
        raw = open(path, "rb").read().lstrip(b"\xef\xbb\xbf").decode("utf-8")
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_env()


def _post_webhook(payload: dict):
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url or "discord.com/api/webhooks/" not in url:
        log.warning("DISCORD_WEBHOOK_URL not set or malformed — skipping Discord post")
        return
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "gps-tsunami-pipeline",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status not in (200, 204):
                log.warning("Discord webhook HTTP %s", r.status)
    except urllib.error.HTTPError as e:
        log.error("Discord webhook failed: HTTP %s %s", e.code, e.reason)
    except Exception as e:
        log.error("Discord webhook failed: %s", e)


def send_detection_alert(evt):
    """Posted when an event first reaches status predicted."""
    mag = evt.get("magnitude", "?")
    place = evt.get("place", "?")[:120]
    quake = evt.get("quake_utc", "?")
    result = evt.get("result") or evt.get("prediction") or "predicted"
    usgs = evt.get("usgs_id", "")

    embed = {
        "title": "GPS Tsunami — detector prediction",
        "color": 0x5865F2,
        "fields": [
            {"name": "Mw / location", "value": f"{mag} — {place}", "inline": False},
            {"name": "Origin (UTC)", "value": str(quake)[:32], "inline": True},
            {"name": "USGS id", "value": str(usgs)[:48] or "—", "inline": True},
            {"name": "Status", "value": str(result)[:200], "inline": False},
        ],
    }
    _post_webhook({"embeds": [embed], "username": "GPS Tsunami"})


def send_pipeline_error(component: str, err: str):
    """Pipeline cycle exception or fatal stage error."""
    text = f"**{component}** error:\n```{err[:1800]}```"
    _post_webhook({"content": text[:2000], "username": "GPS Tsunami"})
