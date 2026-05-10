"""
Twitch chat alerts via IRC (TLS) — near-miss seismic and manual connectivity tests.

Near-misses (Pacific Mw5.5+ that did not queue) are rare enough that one chat line
per pipeline cycle is acceptable; each USGS event is only logged once because
usgs_listener marks ids in seen_ids on first sighting.

.env (never commit):
  TWITCH_IRC_NICK=your_bot_or_streamer_username
  TWITCH_IRC_TOKEN=oauth:xxxxxxxx   # from https://twitchapps.com/tmi/ (chat scope)
  TWITCH_IRC_CHANNEL=yourchannel    # lowercase, no # prefix

Test without waiting for a real near-miss:
  python notify_twitch.py --test
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import ssl
import sys
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697
MAX_MSG_LEN = 450  # under Twitch IRC limit; room for prefix


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


def _irc_config():
    _load_env()
    nick = os.environ.get("TWITCH_IRC_NICK", "").strip()
    token = os.environ.get("TWITCH_IRC_TOKEN", "").strip()
    channel = os.environ.get("TWITCH_IRC_CHANNEL", "").strip().lower().lstrip("#")
    if token and not token.startswith("oauth:"):
        token = "oauth:" + token
    return nick, token, channel


def _sanitize_irc_line(s: str) -> str:
    return " ".join(s.replace("\r", " ").replace("\n", " ").split()).strip()


def send_chat_message(text: str) -> bool:
    """
    Connect to Twitch IRC, send one PRIVMSG, disconnect.
    Returns True if message was sent, False if skipped (missing config).
    """
    nick, token, channel = _irc_config()
    if not nick or not token or not channel:
        log.warning(
            "Twitch IRC: set TWITCH_IRC_NICK, TWITCH_IRC_TOKEN (oauth:...), TWITCH_IRC_CHANNEL"
        )
        return False

    msg = _sanitize_irc_line(text)
    if len(msg) > MAX_MSG_LEN:
        msg = msg[: MAX_MSG_LEN - 3] + "..."

    ctx = ssl.create_default_context()
    sock = ctx.wrap_socket(socket.socket(socket.AF_INET, socket.SOCK_STREAM), server_hostname=IRC_HOST)
    sock.settimeout(12.0)
    try:
        sock.connect((IRC_HOST, IRC_PORT))
        sock.sendall(b"CAP REQ :twitch.tv/tags\r\n")
        sock.sendall(f"PASS {token}\r\n".encode("utf-8"))
        sock.sendall(f"NICK {nick}\r\n".encode("utf-8"))
        sock.sendall(f"JOIN #{channel}\r\n".encode("utf-8"))

        buf = b""
        deadline = time.monotonic() + 8.0
        joined = False
        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            except socket.timeout:
                break
            if b"JOIN #" + channel.encode() in buf or b" 366 " in buf:
                joined = True
                break
            if b"Login authentication failed" in buf or b"Improperly formatted auth" in buf:
                log.error("Twitch IRC: authentication failed — check TWITCH_IRC_TOKEN / NICK")
                return False

        if not joined and b" 001 " not in buf:
            log.warning("Twitch IRC: did not confirm JOIN in time; sending anyway")

        time.sleep(0.4)
        sock.sendall(f"PRIVMSG #{channel} :{msg}\r\n".encode("utf-8"))
        time.sleep(0.2)
        sock.sendall(b"QUIT\r\n")
        log.info("Twitch IRC: message sent to #%s", channel)
        return True
    except Exception as e:
        log.error("Twitch IRC send failed: %s", e)
        raise
    finally:
        try:
            sock.close()
        except Exception:
            pass


def send_near_miss_alerts(near_misses: list) -> None:
    """Format near_miss rows from usgs_listener and post one chat line."""
    if not near_misses:
        return
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    parts = []
    for nm in near_misses[:4]:
        mag = nm.get("mag", "?")
        place = (nm.get("place") or "?")[:40]
        reason = (nm.get("reason") or "?")[:60]
        parts.append(f"Mw{mag} {place} ({reason})")
    extra = ""
    if len(near_misses) > 4:
        extra = f" +{len(near_misses) - 4} more"
    line = f"[GPS-Tsunami near-miss {now}] " + " | ".join(parts) + extra
    try:
        send_chat_message(line)
    except Exception:
        log.exception("Twitch near-miss alert failed")


def send_test_message() -> bool:
    """Explicit connectivity check for operators."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return send_chat_message(f"[GPS-Tsunami TEST] IRC connectivity OK — {ts}")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Twitch IRC alerts for GPS Tsunami pipeline")
    p.add_argument("--test", action="store_true", help="Send a test message to the configured channel")
    args = p.parse_args()
    if args.test:
        ok = send_test_message()
        sys.exit(0 if ok else 2)
    p.print_help()


if __name__ == "__main__":
    main()
