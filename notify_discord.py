"""
Discord webhook alerts for detector predictions, Pacific near-miss seismic,
and pipeline errors (same DISCORD_WEBHOOK_URL).

Set DISCORD_ALERTS_ENABLED=0 in GitHub Actions so only the Windows Task
Scheduler machine sends phone pushes (avoids duplicate / dead-webhook spam).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

STATE_FILE = Path(".discord_webhook_state.json")
WEBHOOK_COOLDOWN_SEC = 6 * 3600
ERROR_DEDUP_SEC = 3600


def _fmt_num(value, fmt=".3f", missing="—"):
    if value is None:
        return missing
    try:
        return format(value, fmt)
    except (TypeError, ValueError):
        return missing


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


def alerts_enabled() -> bool:
    """Phone/webhook alerts run on the Windows pipeline host by default, not CI."""
    flag = os.environ.get("DISCORD_ALERTS_ENABLED", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if os.environ.get("CI", "").strip().lower() == "true":
        return False
    return True


def _read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as e:
        log.warning("Could not persist Discord webhook state: %s", e)


def _webhook_suppressed() -> bool:
    until = float(_read_state().get("suppress_until", 0))
    if until <= time.time():
        return False
    log.warning(
        "Discord webhook suppressed until %s — regenerate URL in .env if still broken",
        time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(until)),
    )
    return True


def _trip_webhook_circuit(http_code: int) -> None:
    if http_code not in (401, 403, 404):
        return
    state = _read_state()
    state["suppress_until"] = time.time() + WEBHOOK_COOLDOWN_SEC
    state["last_failure_code"] = http_code
    state["last_failure_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_state(state)
    log.error(
        "Discord webhook returned HTTP %s — pausing posts for %dh. "
        "Regenerate webhook in Discord channel settings and update DISCORD_WEBHOOK_URL in .env",
        http_code,
        WEBHOOK_COOLDOWN_SEC // 3600,
    )


def _post_webhook(payload: dict) -> bool:
    if not alerts_enabled():
        log.debug("Discord alerts disabled for this runner — skipping post")
        return False
    if _webhook_suppressed():
        return False

    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url or "discord.com/api/webhooks/" not in url:
        log.warning("DISCORD_WEBHOOK_URL not set or malformed — skipping Discord post")
        return False

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
                return False
            state = _read_state()
            state.pop("suppress_until", None)
            _write_state(state)
            return True
    except urllib.error.HTTPError as e:
        log.error("Discord webhook failed: HTTP %s %s", e.code, e.reason)
        _trip_webhook_circuit(e.code)
    except Exception as e:
        log.error("Discord webhook failed: %s", e)
    return False


def _prediction_summary(evt) -> str:
    pred = evt.get("prediction")
    if not isinstance(pred, dict):
        return str(evt.get("result") or evt.get("status") or "predicted")[:200]

    detected = pred.get("detected", False)
    reason = pred.get("reason") or ("coherent_pairs" if detected else "—")
    conf = pred.get("combined_confidence")
    conf_s = _fmt_num(conf)
    stations = pred.get("stations_processed") or []
    st_s = ", ".join(stations).upper() if stations else "—"
    dart = pred.get("dart_status") or "n/a"
    lines = [
        f"**TEC signal:** {'yes' if detected else 'no'}",
        f"**Reason:** {reason}",
        f"**Confidence:** {conf_s}",
        f"**Stations:** {st_s}",
        f"**DART:** {dart}",
    ]
    if detected and pred.get("detection"):
        d = pred["detection"]
        pair = d.get("pair", "?")
        post_h = d.get("post_h")
        post_s = f"+{_fmt_num(post_h, '.1f')}h" if post_h is not None else "—"
        lines.append(f"**Best pair:** {pair} {post_s}")
    wf = pred.get("wave_forecast")
    if wf and wf.get("predicted_wave_m") is not None:
        lines.append(f"**Hilo forecast:** {_fmt_num(wf.get('predicted_wave_m'))} m")
    return "\n".join(lines)


def send_detection_alert(evt) -> bool:
    mag = evt.get("magnitude", "?")
    place = evt.get("place", "?")[:120]
    quake = evt.get("quake_utc", "?")
    usgs = evt.get("usgs_id", "")
    summary = _prediction_summary(evt)
    embed = {
        "title": "GPS Tsunami — detector complete",
        "description": summary,
        "fields": [
            {"name": "Mw / location", "value": f"{mag} — {place}", "inline": False},
            {"name": "Origin (UTC)", "value": str(quake)[:32], "inline": True},
            {"name": "USGS id", "value": str(usgs)[:48] or "—", "inline": True},
        ],
    }
    return _post_webhook({"embeds": [embed], "username": "GPS Tsunami"})


def send_retroactive_triggered(info: dict) -> bool:
    """CDDIS coverage improved — event queued for re-download and re-run."""
    usgs = info.get("usgs_id", "?")
    mag = info.get("magnitude", "?")
    place = (info.get("place") or "?")[:100]
    reason = (info.get("reason") or "new RINEX on CDDIS")[:500]
    prior = info.get("prior_status") or "?"
    prior_det = info.get("prior_detected")
    prior_det_s = (
        "yes" if prior_det is True else "no" if prior_det is False else "—"
    )
    stations = info.get("new_stations") or []
    st_s = ", ".join(str(s).upper() for s in stations[:12]) if stations else "—"
    if len(stations) > 12:
        st_s += f" (+{len(stations) - 12} more)"
    embed = {
        "title": "Retroactive re-run started",
        "description": (
            f"**Why:** {reason}\n\n"
            f"Pipeline reset this event and will re-download RINEX, re-run the detector, "
            f"and re-score if the event is 24h+ old.\n\n"
            f"**Before:** status `{prior}`, GPS TEC signal **{prior_det_s}**"
        ),
        "color": 0x00C8FF,
        "fields": [
            {"name": "Event", "value": f"Mw{mag} — {place}", "inline": False},
            {"name": "USGS id", "value": str(usgs), "inline": True},
            {"name": "CDDIS stations now", "value": st_s, "inline": True},
            {
                "name": "Run",
                "value": f"retro #{info.get('retro_run', '?')}",
                "inline": True,
            },
        ],
    }
    return _post_webhook({"embeds": [embed], "username": "GPS Tsunami"})


def send_retroactive_completed(evt: dict) -> bool:
    """Detector finished after a retroactive re-run — includes before/after summary."""
    usgs = evt.get("usgs_id", "?")
    mag = evt.get("magnitude", "?")
    place = (evt.get("place") or "?")[:100]
    reason = (evt.get("retro_trigger_reason") or "CDDIS coverage improved")[:400]
    prior_det = evt.get("retro_prior_detected")
    prior_det_s = (
        "yes" if prior_det is True else "no" if prior_det is False else "—"
    )
    pred = evt.get("prediction") if isinstance(evt.get("prediction"), dict) else {}
    new_det = pred.get("detected", False)
    new_det_s = "yes" if new_det else "no"
    changed = prior_det_s != "—" and (prior_det is True) != (new_det is True)
    summary = _prediction_summary(evt)
    embed = {
        "title": "Retroactive re-run complete",
        "description": (
            f"**Trigger:** {reason}\n\n"
            f"**GPS TEC signal:** {prior_det_s} → **{new_det_s}**"
            + (" _(changed)_" if changed else "")
            + f"\n\n{summary}"
        ),
        "color": 0x00FF9D if new_det else 0x6A9CC0,
        "fields": [
            {"name": "Event", "value": f"Mw{mag} — {place}", "inline": False},
            {"name": "USGS id", "value": str(usgs), "inline": True},
            {
                "name": "Status",
                "value": str(evt.get("status") or "predicted"),
                "inline": True,
            },
        ],
    }
    return _post_webhook({"embeds": [embed], "username": "GPS Tsunami"})


def send_retroactive_aborted(evt: dict, detail: str) -> bool:
    """Retro run could not download new RINEX."""
    usgs = evt.get("usgs_id", "?")
    place = (evt.get("place") or "?")[:80]
    embed = {
        "title": "Retroactive re-run — no new files",
        "description": (evt.get("retro_trigger_reason") or "CDDIS probe")[:300]
        + f"\n\n{detail[:500]}",
        "color": 0xFFA726,
        "fields": [
            {"name": "USGS id", "value": str(usgs), "inline": True},
            {"name": "Location", "value": place, "inline": True},
        ],
    }
    return _post_webhook({"embeds": [embed], "username": "GPS Tsunami"})


def send_pipeline_error(component: str, err: str) -> bool:
    """Post pipeline errors, but dedupe identical messages within ERROR_DEDUP_SEC."""
    key = hashlib.sha256(f"{component}:{err[:500]}".encode()).hexdigest()[:16]
    state = _read_state()
    last_errors: dict = state.get("last_errors", {})
    now = time.time()
    prev = last_errors.get(key, {})
    if prev and now - float(prev.get("ts", 0)) < ERROR_DEDUP_SEC:
        log.info("Skipping duplicate Discord pipeline error (sent %.0fm ago)", (now - prev["ts"]) / 60)
        return False

    text = f"**{component}** error:\n```\n{err[:1800]}\n```"
    ok = _post_webhook({"content": text[:2000], "username": "GPS Tsunami"})
    if ok:
        last_errors[key] = {"ts": now, "component": component}
        state["last_errors"] = last_errors
        _write_state(state)
    return ok


def send_near_miss_alerts(near_misses: list) -> bool:
    if not near_misses:
        return False
    chunks = []
    for nm in near_misses[:10]:
        mag = nm.get("mag", "?")
        place = (nm.get("place") or "?")[:90]
        reason = (nm.get("reason") or "?")[:120]
        delta = nm.get("delta")
        dstr = f"ΔMw vs 6.5 threshold: {_fmt_num(delta, '+.1f')}" if delta is not None else "ΔMw: —"
        ts = str(nm.get("ts", ""))[:22]
        dep = nm.get("depth")
        dline = f"Depth: {dep} km" if dep is not None else ""
        chunks.append(f"**Mw{mag}** — {place}\n{dstr} · {reason}\n`{ts}`" + (f"\n{dline}" if dline else ""))
    desc = "\n\n".join(chunks)
    if len(near_misses) > 10:
        desc += f"\n\n_+{len(near_misses) - 10} more in this cycle_"
    embed = {
        "title": "GPS Tsunami — Pacific near-miss (did not queue)",
        "description": desc[:4000],
        "color": 0xFFA726,
    }
    return _post_webhook({"embeds": [embed], "username": "GPS Tsunami"})
