"""
check_recent.py  --  GPS Tsunami Detection: Recent Activity Funnel Check
Uses the USGS pre-built real-time GeoJSON feed (same source as your pipeline)
and filters to the last 2 days, showing how events move through the filters.
"""

import os, json, datetime, urllib.request

# ── self-delete old Downloads copies ─────────────────────────────────────────
DOWNLOADS = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")
for name in ["check_recent.py", "check_recent (1).py", "check_recent (2).py"]:
    p = os.path.join(DOWNLOADS, name)
    if os.path.exists(p):
        os.remove(p)

# ── Pacific zone polygons (mirrored from usgs_listener.py) ───────────────────
# Tonga-Kermadec extended west to -180 to catch antimeridian events
PACIFIC_ZONES = {
    "Cascadia":        dict(lat=(40, 52),   lon=(-130, -120)),
    "Alaska-Aleutian": dict(lat=(48, 72),   lon=(-180, -130)),
    "Kamchatka":       dict(lat=(46, 62),   lon=(155, 175)),
    "Japan":           dict(lat=(30, 46),   lon=(130, 148)),
    "Izu-Bonin":       dict(lat=(22, 35),   lon=(138, 148)),
    "Mariana":         dict(lat=(10, 25),   lon=(140, 150)),
    "Philippines":     dict(lat=(4,  22),   lon=(120, 140)),
    "Sulawesi":        dict(lat=(-5, 5),    lon=(120, 130)),
    "Banda Sea":       dict(lat=(-12, -3),  lon=(122, 135)),
    "New Guinea":      dict(lat=(-12, 0),   lon=(130, 150)),
    "Solomon Islands": dict(lat=(-14, -4),  lon=(152, 168)),
    "Vanuatu":         dict(lat=(-22, -12), lon=(165, 172)),
    "Tonga-Kermadec":  dict(lat=(-36, -14), lon=(-180, -172)),  # fixed: was -178
    "New Zealand":     dict(lat=(-48, -34), lon=(165, 180)),
    "Peru-Chile":      dict(lat=(-60, -15), lon=(-80, -65)),
    "Central America": dict(lat=(5,  20),   lon=(-100, -82)),
    "Mexico":          dict(lat=(14, 24),   lon=(-107, -95)),
}

def get_pacific_zone(lat, lon):
    for zone, b in PACIFIC_ZONES.items():
        if b["lat"][0] <= lat <= b["lat"][1]:
            lo, hi = b["lon"]
            if lo < 0 and hi > 0:
                if lon >= lo or lon <= hi:
                    return zone
            elif lo <= lon <= hi:
                return zone
    return None

# ── fetch USGS pre-built feed: Mw4.5+ past 7 days (filter to 2 days below) ──
URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"

print(f"\nFetching USGS Mw4.5+ weekly feed ...\n")

with urllib.request.urlopen(URL, timeout=30) as r:
    data = json.loads(r.read())

all_events = data.get("features", [])
print(f"  Total in weekly feed: {len(all_events)}")

now       = datetime.datetime.now(datetime.timezone.utc)
cutoff_ms = (now - datetime.timedelta(days=2)).timestamp() * 1000
events    = [f for f in all_events if f["properties"]["time"] >= cutoff_ms]
print(f"  Last 2 days: {len(events)}\n")

MAG_THRESHOLD = 6.5
MAG_FASTPOLL  = 6.0
DEPTH_LIMIT   = 100.0

results = {
    "qualified":      [],
    "fast_poll_only": [],
    "too_deep":       [],   # Pacific, mag OK, but depth > 100km
    "below_mag":      [],   # Pacific, shallow enough, but mag < 6.0
    "non_pacific":    [],
}

for feat in events:
    props   = feat["properties"]
    geo     = feat["geometry"]["coordinates"]
    lon, lat, depth = geo[0], geo[1], (geo[2] or 0)
    mag     = props.get("mag") or 0
    place   = props.get("place", "")
    t       = datetime.datetime.fromtimestamp(
                  props["time"] / 1000, tz=datetime.timezone.utc
              ).strftime("%Y-%m-%d %H:%M")
    usgs_id = feat["id"]
    zone    = get_pacific_zone(lat, lon)

    row = dict(time=t, mag=mag, depth=depth, lat=lat, lon=lon,
               place=place, zone=zone, usgs_id=usgs_id)

    if zone is None:
        results["non_pacific"].append(row)
    elif depth > DEPTH_LIMIT and mag < MAG_FASTPOLL:
        # deep AND below mag threshold -- show under too_deep (depth is why it matters)
        results["too_deep"].append(row)
    elif depth > DEPTH_LIMIT:
        # deep but would otherwise have been interesting -- show under too_deep
        results["too_deep"].append(row)
    elif mag < MAG_FASTPOLL:
        results["below_mag"].append(row)
    elif mag < MAG_THRESHOLD:
        results["fast_poll_only"].append(row)
    else:
        results["qualified"].append(row)

SEP = "-" * 72

def print_section(title, rows, note=""):
    print(f"\n{'='*72}")
    print(f"  {title}  ({len(rows)} events){('  -- ' + note) if note else ''}")
    print(SEP)
    if not rows:
        print("  (none)")
        return
    for r in rows:
        print(f"  {r['time']} UTC  Mw{r['mag']:.1f}  depth={r['depth']:.0f}km  "
              f"zone={r['zone'] or 'n/a'}  {r['place']}")
        print(f"    {r['usgs_id']}  lat={r['lat']:.2f} lon={r['lon']:.2f}")

print_section("FULLY QUALIFIED -- pipeline should have processed",
              results["qualified"],
              "check these against your event_queue.json")
print_section("FAST POLL TRIGGER ONLY (Mw6.0-6.4)",
              results["fast_poll_only"],
              "triggers fast_poll.json but no full TEC run")
print_section("PACIFIC but TOO DEEP (>100km)",
              results["too_deep"],
              "correctly filtered -- shown regardless of magnitude")
print_section("PACIFIC, below Mw6.0, shallow (background seismicity)",
              results["below_mag"])
print_section("NON-PACIFIC -- correctly ignored",
              results["non_pacific"])

print(f"\n{'='*72}")
print("  SUMMARY")
print(SEP)
print(f"  Fully qualified (should be in your log) : {len(results['qualified'])}")
print(f"  Fast poll triggers (Mw6.0-6.4)          : {len(results['fast_poll_only'])}")
print(f"  Killed by depth gate                    : {len(results['too_deep'])}")
print(f"  Below fast-poll threshold (shallow)     : {len(results['below_mag'])}")
print(f"  Non-Pacific (ignored)                   : {len(results['non_pacific'])}")
print()
print("  NOTE: Strike-slip filter runs live via ShakeMap -- this script")
print("  cannot replicate it, so qualified count may be 1-2 high.")
print()
