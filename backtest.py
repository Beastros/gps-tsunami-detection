import json, logging, argparse, sys, os, csv, io
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("backtest.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# Load .env manually to avoid BOM/parse issues
def load_env(path=".env"):
    try:
        raw = open(path, "rb").read().lstrip(b"\xef\xbb\xbf").decode("utf-8")
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass

load_env()

EARTHDATA_USER = os.getenv("EARTHDATA_USER", "")
EARTHDATA_PASS = os.getenv("EARTHDATA_PASS", "")

BUILTIN_EVENTS_CSV = """\
usgs_id,quake_utc,lat,lon,mw,depth_km,known_outcome,notes
official20110311054624120_30,2011-03-11T05:46:24Z,38.30,142.37,9.1,32,TSUNAMI,Tohoku - KOKB-GUAM in V1
official20100227063411530_30,2010-02-27T06:34:11Z,-35.85,-72.72,8.8,35,TSUNAMI,Chile - 108 min lead V1
usp000f1s0,2006-11-15T11:14:14Z,46.59,153.27,8.3,33,TSUNAMI,Kuril - MKEA-GUAM V1
usp000jrsf,2012-10-28T03:04:08Z,52.79,-132.10,7.7,17,TSUNAMI,Haida Gwaii - HNLC-GUAM V1
usp000fjta,2009-09-29T17:48:10Z,-15.49,-172.10,8.1,18,ABSTAIN,Samoa - no anchor geometry V1
usp000jadn,2012-04-11T08:38:36Z,2.33,93.06,8.6,20,NO_TSUNAMI,Sumatra strike-slip - ShakeMap should gate
usp000jhe9,2013-05-24T05:44:48Z,54.87,153.28,8.3,609,NO_TSUNAMI,Okhotsk deep 609km - depth gate
usp000hvtm,2011-10-21T17:57:16Z,-28.98,-176.24,7.4,26,NO_TSUNAMI,Kermadec Mw7.4 - below sensitivity
usp000hpgz,2011-03-09T02:45:20Z,38.44,142.84,7.2,32,NO_TSUNAMI,Tohoku foreshock Mw7.2 - below threshold
us2007aqbk,2007-04-01T20:39:56Z,-8.481,156.978,8.1,10,TSUNAMI,Solomon Islands 2007 - thrust shallow - 52 killed 12m runup
us2007gbcv,2007-08-15T23:40:57Z,-13.354,-76.509,8.0,30,TSUNAMI,Peru Pisco 2007 - thrust - 10m local runup CHAT corridor
usp000hjkp,2010-10-25T14:42:22Z,-3.484,100.114,7.7,20,TSUNAMI,Mentawai 2010 - tsunami earthquake - 450 killed 9m runup Indian Ocean
us7000gc8r,2022-01-15T04:14:45Z,-20.546,-175.390,5.8,0,TSUNAMI,Tonga volcanic 2022 - MKEA-THTG detected V1 - volcanic AGW source
"""

# tsunamigenic_index: computed from rake + depth per usgs_listener.py logic
# primary_anchor: drives corridor station selection in rinex_downloader.py
BACKTEST_METADATA = {
    "official20110311054624120_30": {"tsunamigenic_index": 1.0,  "primary_anchor": "guam"},
    "official20100227063411530_30": {"tsunamigenic_index": 1.0,  "primary_anchor": "guam"},
    "usp000f1s0":                   {"tsunamigenic_index": 1.0,  "primary_anchor": "guam"},
    "usp000jrsf":                   {"tsunamigenic_index": 1.0,  "primary_anchor": "guam"},
    "usp000fjta":                   {"tsunamigenic_index": 0.4,  "primary_anchor": None},
    "usp000jadn":                   {"tsunamigenic_index": 0.05, "primary_anchor": None},
    "usp000jhe9":                   {"tsunamigenic_index": 0.4,  "primary_anchor": "guam"},
    "usp000hvtm":                   {"tsunamigenic_index": 1.0,  "primary_anchor": "guam"},
    "usp000hpgz":                   {"tsunamigenic_index": 1.0,  "primary_anchor": "guam"},
    "us2007aqbk":                   {"tsunamigenic_index": 1.0,  "primary_anchor": "guam"},
    "us2007gbcv":                   {"tsunamigenic_index": 0.7,  "primary_anchor": "chat"},
    "usp000hjkp":                   {"tsunamigenic_index": 1.0,  "primary_anchor": None},
    "us7000gc8r":                   {"tsunamigenic_index": None,  "primary_anchor": "thti"},  # volcanic -- no rake angle
}

def build_event_dict(row):
    uid  = row["usgs_id"]
    meta = BACKTEST_METADATA.get(uid, {})
    return {
        "usgs_id":            uid,
        "quake_utc":          row["quake_utc"],
        "lat":                float(row["lat"]),
        "lon":                float(row["lon"]),
        "magnitude":          float(row["mw"]),
        "depth_km":           float(row.get("depth_km", 50)),
        "place":              row.get("notes", uid),
        "status":             "rinex_ready",
        "rinex_dir":          "rinex_live/" + uid,
        "tsunamigenic_index": meta.get("tsunamigenic_index"),
        "primary_anchor":     meta.get("primary_anchor"),
        "zones":              [],
    }

def score_against_known(prediction, known_outcome, event):
    detected    = prediction.get("detected", False)
    confidence  = prediction.get("combined_confidence", 0.0) or 0.0
    dart_status = prediction.get("dart_status", "no_buoys")
    iono        = prediction.get("ionosonde_confirmed", False)
    dtec        = prediction.get("dtec_corroborates", False)
    const_label = (prediction.get("constellation_agreement") or {}).get("agreement_label", "unknown")
    reason      = prediction.get("reason", "")

    if known_outcome == "TSUNAMI":
        if detected:                                                                bt_outcome = "TRUE_POSITIVE"
        elif reason in ("insufficient_stations","no_anchor","no_coherent_pairs"):  bt_outcome = "GEOMETRY_LIMITED_MISS"
        else:                                                                       bt_outcome = "FALSE_NEGATIVE"
    elif known_outcome == "NO_TSUNAMI":
        bt_outcome = "TRUE_NEGATIVE" if (not detected or confidence < 0.35) else "FALSE_POSITIVE"
    elif known_outcome == "ABSTAIN":
        bt_outcome = "CORRECT_ABSTENTION" if not detected else "UNEXPECTED_DETECTION"
    else:
        bt_outcome = "UNKNOWN"

    correct = bt_outcome in ("TRUE_POSITIVE","TRUE_NEGATIVE","CORRECT_ABSTENTION","GEOMETRY_LIMITED_MISS")
    return {
        "usgs_id": event["usgs_id"], "place": event.get("place",""),
        "mw": event["magnitude"], "quake_utc": event["quake_utc"],
        "known_outcome": known_outcome, "bt_outcome": bt_outcome, "correct": correct,
        "detected": detected, "confidence": round(confidence,3),
        "dart_status": dart_status, "iono_confirmed": iono,
        "dtec_corroborates": dtec, "const_label": const_label, "reason": reason,
        "prediction": prediction,
    }

def run_backtest(events_csv_str=None, single_id=None):
    try:
        import detector_runner, rinex_downloader
    except ImportError as e:
        log.error("Import failed: " + str(e) + " -- run from pipeline folder")
        sys.exit(1)

    if not EARTHDATA_USER or not EARTHDATA_PASS:
        log.error("EARTHDATA_USER or EARTHDATA_PASS missing")
        log.error("USER=" + repr(EARTHDATA_USER) + " PASS=" + ("SET" if EARTHDATA_PASS else "EMPTY"))
        sys.exit(1)

    log.info("Credentials loaded: USER=" + EARTHDATA_USER + " PASS=SET")
    auth = (EARTHDATA_USER, EARTHDATA_PASS)
    csv_str = events_csv_str or BUILTIN_EVENTS_CSV
    rows = list(csv.DictReader(io.StringIO(csv_str.strip())))
    if single_id:
        rows = [r for r in rows if r["usgs_id"] == single_id]
        if not rows:
            log.error("Event not found: " + single_id); sys.exit(1)

    log.info("=" * 60)
    log.info("GPS Tsunami V2 Backtester  --  " + str(len(rows)) + " event(s)")
    log.info("=" * 60)

    results, skipped = [], []

    for row in rows:
        usgs_id, known_outcome = row["usgs_id"], row["known_outcome"].strip()
        log.info("-" * 55)
        log.info("EVENT: " + usgs_id + "  Mw" + row["mw"] + "  " + row["quake_utc"][:10])
        log.info("  Known: " + known_outcome + "  -- " + row.get("notes",""))

        event = build_event_dict(row)
        Path(event["rinex_dir"]).mkdir(parents=True, exist_ok=True)

        log.info("  [1/2] Downloading RINEX...")
        try:
            rinex_downloader.download_event(event, auth)
            gz = list((Path("rinex_live") / usgs_id).glob("*.Z"))
            if not gz:
                log.warning("  No RINEX files -- skipping")
                skipped.append({"usgs_id": usgs_id, "reason": "no_rinex"}); continue
            log.info("  " + str(len(gz)) + " file(s) downloaded")
        except Exception as e:
            log.warning("  RINEX failed: " + str(e))
            skipped.append({"usgs_id": usgs_id, "reason": str(e)}); continue

        log.info("  [2/2] Running V2 detector...")
        try:
            prediction = detector_runner.run_event(event, kp_override=0.0)
            prediction["space_weather_score"] = 0.0
        except Exception as e:
            log.error("  Detector failed: " + str(e))
            import traceback; traceback.print_exc()
            skipped.append({"usgs_id": usgs_id, "reason": "detector: " + str(e)}); continue

        result = score_against_known(prediction, known_outcome, event)
        results.append(result)
        icon = "OK " if result["correct"] else "ERR"
        log.info("  [" + icon + "] " + result["bt_outcome"] +
                 "  conf=" + str(result["confidence"]) +
                 "  dart=" + result["dart_status"])

    if not results:
        log.warning("No results."); return

    tp = sum(1 for r in results if r["bt_outcome"] == "TRUE_POSITIVE")
    tn = sum(1 for r in results if r["bt_outcome"] in ("TRUE_NEGATIVE","CORRECT_ABSTENTION"))
    fp = sum(1 for r in results if r["bt_outcome"] == "FALSE_POSITIVE")
    fn = sum(1 for r in results if r["bt_outcome"] == "FALSE_NEGATIVE")
    gl = sum(1 for r in results if r["bt_outcome"] == "GEOMETRY_LIMITED_MISS")
    tpr = round(tp/(tp+fn),3) if (tp+fn)>0 else None
    fpr = round(fp/(fp+tn),3) if (fp+tn)>0 else None

    buckets = {"0.0-0.2":[],"0.2-0.4":[],"0.4-0.6":[],"0.6-0.8":[],"0.8-1.0":[]}
    for r in results:
        c, actual = r["confidence"], r["known_outcome"]=="TSUNAMI"
        if c<0.2: buckets["0.0-0.2"].append(actual)
        elif c<0.4: buckets["0.2-0.4"].append(actual)
        elif c<0.6: buckets["0.4-0.6"].append(actual)
        elif c<0.8: buckets["0.6-0.8"].append(actual)
        else: buckets["0.8-1.0"].append(actual)

    out = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "n_events": len(results), "n_skipped": len(skipped),
        "summary": {
            "tp":tp,"tn":tn,"fp":fp,"fn":fn,"geometry_limited":gl,
            "tpr":tpr,"fpr":fpr,
            "calibration":{
                n:{"n":len(v),"hit_rate":round(sum(v)/len(v),3) if v else None}
                for n,v in buckets.items() if v
            },
        },
        "results": results, "skipped": skipped,
    }
    Path("backtest_results.json").write_text(json.dumps(out,indent=2), encoding="utf-8")

    lines = ["="*60, "GPS TSUNAMI V2 -- BACKTEST RESULTS",
             "Run: "+out["run_utc"][:19]+" UTC",
             "Processed: "+str(len(results))+"  Skipped: "+str(len(skipped)),
             "="*60, "", "PER-EVENT RESULTS", "-"*60]
    for r in results:
        icon = "OK " if r["correct"] else "ERR"
        lines += [
            "["+icon+"] "+r["bt_outcome"].ljust(28)+" conf="+str(r["confidence"])+"  Mw"+str(r["mw"])+"  "+r["quake_utc"][:10],
            "       "+r["place"][:55],
            "       dart="+r["dart_status"]+"  iono="+str(r["iono_confirmed"])+"  const="+r["const_label"],
            ""
        ]
    lines += ["", "SUMMARY", "-"*60,
              "  TP="+str(tp)+" TN="+str(tn)+" FP="+str(fp)+" FN="+str(fn)+" GL="+str(gl)]
    if tpr is not None:
        lines.append("  TPR="+str(tpr)+"  FPR="+str(fpr))
    lines += ["", "CALIBRATION", "-"*60, "  Bucket     N   Hit%"]
    for n,v in buckets.items():
        if v:
            hr = sum(v)/len(v)
            lines.append("  "+n+"    "+str(len(v))+"   "+str(round(hr*100))+"%   "+"#"*round(hr*20))
    if skipped:
        lines += ["", "SKIPPED", "-"*60] + ["  "+s["usgs_id"]+": "+s["reason"] for s in skipped]
    lines.append("="*60)

    report = "\n".join(lines)
    Path("backtest_summary.txt").write_text(report, encoding="utf-8")
    log.info("\n" + report)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default=None)
    p.add_argument("--event", default=None)
    args = p.parse_args()
    csv_str = Path(args.csv).read_text() if args.csv else None
    run_backtest(events_csv_str=csv_str, single_id=args.event)


