"""
Gmail SMTP alerts for new queued USGS candidates.
Loads .env manually (BOM-safe) — see backtest.py / project docs.
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

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


def send_event_alert(events):
    """
    Email one summary for new candidate event(s) just queued.
    events: list of dicts from usgs_listener (status queued).
    """
    if not events:
        return
    addr = os.environ.get("NOTIFY_EMAIL", "").strip()
    pwd = os.environ.get("NOTIFY_APP_PASSWORD", "").replace(" ", "").strip()
    if not addr or not pwd:
        log.warning("NOTIFY_EMAIL / NOTIFY_APP_PASSWORD not set — skipping email alert")
        return

    lines = []
    for ev in events:
        mag = ev.get("magnitude", "?")
        place = ev.get("place", "?")
        quake = ev.get("quake_utc", "?")
        anchor = ev.get("primary_anchor", "?")
        lines.append(f"  Mw{mag}  {place}  {quake}  anchor={anchor}")

    body = (
        "GPS Tsunami pipeline — new USGS candidate(s) queued:\n\n"
        + "\n".join(lines)
        + "\n\n(Detector will run when RINEX is ready.)\n"
    )

    msg = EmailMessage()
    msg["Subject"] = f"GPS Tsunami: {len(events)} new candidate(s)"
    msg["From"] = addr
    msg["To"] = addr
    msg.set_content(body)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as smtp:
            smtp.login(addr, pwd)
            smtp.send_message(msg)
        log.info("Email alert sent (%s new candidate(s))", len(events))
    except Exception as e:
        log.error("Email alert failed: %s", e)
