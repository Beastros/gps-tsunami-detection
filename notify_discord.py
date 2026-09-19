"""
Discord webhook alerts for detector predictions, Pacific near-miss seismic,
and pipeline errors (same DISCORD_WEBHOOK_URL).
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


def _post_webhook(payload: dict) -> bool:
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
            return True
    except urllib.error.HTTPError as e:
        log.error("Discord webhook failed: HTTP %s %s", e.code, e.reason)
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
    conf_s = f"{conf:.3f}" if conf is not None else "—"
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
        post_s = f"+{post_h:.1f}h" if post_h is not None else "—"
        lines.append(f"**Best pair:** {pair} {post_s}")
    wf = pred.get("wave_forecast")
    if wf and wf.get("predicted_wave_m") is not None:
        lines.append(f"**Hilo forecast:** {wf['predicted_wave_m']:.3f} m")
    return "\n".join(lines)


def send_detection_alert(evt):
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


def send_retroactive_triggered(info: dict):
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


def send_retroactive_completed(evt: dict):
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


def send_retroactive_aborted(evt: dict, detail: str):
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


def send_pipeline_error(component: str, err: str):
    text = f"**{component}** error:\n```{err[:1800]}```"
    return _post_webhook({"content": text[:2000], "username": "GPS Tsunami"})


def send_near_miss_alerts(near_misses: list):
    if not near_misses:
        return
    chunks = []
    for nm in near_misses[:10]:
        mag = nm.get("mag", "?")
        place = (nm.get("place") or "?")[:90]
        reason = (nm.get("reason") or "?")[:120]
        delta = nm.get("delta")
        dstr = f"ΔMw vs 6.5 threshold: {delta:+.1f}" if delta is not None else "ΔMw: —"
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
