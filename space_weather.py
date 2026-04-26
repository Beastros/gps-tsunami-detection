import requests, logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_KP_URL     = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
_PLASMA_URL = "https://services.swpc.noaa.gov/products/solar-wind/plasma-7-day.json"
_MAG_URL    = "https://services.swpc.noaa.gov/products/solar-wind/mag-7-day.json"
_XRAY_URL   = "https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json"

_KP_MODERATE  = 4.0
_KP_SEVERE    = 6.0
_BZ_SOUTH_NT  = -10.0
_SW_SPEED_KMS = 600.0
_XRAY_M_CLASS = 1e-5
_W_KP_MODERATE = 0.4
_W_KP_SEVERE   = 0.6
_W_BZ          = 0.3
_W_SPEED       = 0.2
_W_XRAY        = 0.2
_GATE_THRESHOLD = 0.5
_TIMEOUT = 10


def _fetch(url):
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("space_weather: fetch failed %s - %s", url, e)
        return None


def _get_kp():
    # Returns list-of-dicts, key "Kp"
    data = _fetch(_KP_URL)
    if not data:
        return None
    for row in reversed(data):
        try:
            v = row.get("Kp")
            if v is not None:
                return float(v)
        except (TypeError, ValueError, AttributeError):
            continue
    return None


def _get_sw_speed():
    # Returns list-of-lists, speed at index 2
    data = _fetch(_PLASMA_URL)
    if not data:
        return None
    for row in reversed(data):
        try:
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            v = row[2]
            if v not in (None, "", "speed"):
                return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _get_imf_bz():
    # Returns list-of-lists, bz_gsm at index 3
    data = _fetch(_MAG_URL)
    if not data:
        return None
    for row in reversed(data):
        try:
            if not isinstance(row, (list, tuple)) or len(row) < 4:
                continue
            v = row[3]
            if v not in (None, "", "bz_gsm"):
                return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _get_xray():
    # Returns list-of-dicts, long channel "0.1-0.8nm"
    data = _fetch(_XRAY_URL)
    if not isinstance(data, list):
        return None
    for entry in reversed(data):
        try:
            if entry.get("energy") == "0.1-0.8nm":
                return float(entry["flux"])
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return None


def get_space_weather_quality():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kp        = _get_kp()
    sw_speed  = _get_sw_speed()
    imf_bz    = _get_imf_bz()
    xray_flux = _get_xray()

    score = 0.0
    flags = []

    if kp is not None:
        if kp >= _KP_SEVERE:
            score += _W_KP_SEVERE
            flags.append("Kp=%.1f >= %.0f (strong storm +%.1f)" % (kp, _KP_SEVERE, _W_KP_SEVERE))
        elif kp >= _KP_MODERATE:
            score += _W_KP_MODERATE
            flags.append("Kp=%.1f >= %.0f (active +%.1f)" % (kp, _KP_MODERATE, _W_KP_MODERATE))
    else:
        log.warning("space_weather: Kp unavailable")

    if imf_bz is not None:
        if imf_bz < _BZ_SOUTH_NT:
            score += _W_BZ
            flags.append("IMF Bz=%.1f nT southward (+%.1f)" % (imf_bz, _W_BZ))
    else:
        log.warning("space_weather: IMF Bz unavailable")

    if sw_speed is not None:
        if sw_speed > _SW_SPEED_KMS:
            score += _W_SPEED
            flags.append("SW speed=%.0f km/s (+%.1f)" % (sw_speed, _W_SPEED))
    else:
        log.warning("space_weather: solar wind speed unavailable")

    if xray_flux is not None:
        if xray_flux >= _XRAY_M_CLASS:
            cls = "X" if xray_flux >= 1e-4 else "M"
            score += _W_XRAY
            flags.append("GOES X-ray %.2e W/m2 (%s-class +%.1f)" % (xray_flux, cls, _W_XRAY))
    else:
        log.warning("space_weather: GOES X-ray unavailable")

    score = min(round(score, 2), 1.0)
    gated = score >= _GATE_THRESHOLD

    result = {
        "space_weather_score": score,
        "space_weather_gated": gated,
        "space_weather_flags": flags,
        "space_weather_raw": {
            "kp": kp, "sw_speed": sw_speed,
            "imf_bz": imf_bz, "xray_flux": xray_flux,
        },
        "space_weather_time": now,
    }

    if gated:
        log.warning("space_weather: GATED (%.2f) - %s", score, "; ".join(flags))
    else:
        log.info("space_weather: CLEAR (%.2f) kp=%s bz=%s sw=%s xray=%s", score,
                 "%.1f" % kp if kp is not None else "n/a",
                 "%.1f" % imf_bz if imf_bz is not None else "n/a",
                 "%.0f" % sw_speed if sw_speed is not None else "n/a",
                 "%.1e" % xray_flux if xray_flux is not None else "n/a")
    return result


if __name__ == "__main__":
    import json, logging as _l
    _l.basicConfig(level=_l.INFO, format="%(levelname)s %(message)s")
    r = get_space_weather_quality()
    print(json.dumps(r, indent=2))
    print("  Score : %.2f" % r["space_weather_score"])
    print("  Gated : %s"   % r["space_weather_gated"])
    for f in r["space_weather_flags"]:
        print("  Flag  : %s" % f)
    if not r["space_weather_flags"]:
        print("  Flags : none - ionosphere clean")
