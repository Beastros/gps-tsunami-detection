import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import detector_runner
import pipeline
import rinex_downloader
import usgs_listener
from retroactive_rinex import queue_retroactive_reprocess


def _feature(usgs_id, mag):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "near Japan",
            "type": "earthquake",
            "time": now_ms,
        },
        "geometry": {"coordinates": [142.0, 38.0, 20.0]},
    }


class CriticalRegressionTests(unittest.TestCase):
    def test_seen_near_miss_can_later_queue_after_magnitude_upgrade(self):
        queue = {"events": [], "seen_ids": ["us-upgrade"]}

        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[_feature("us-upgrade", 7.1)]), \
             mock.patch.object(usgs_listener, "fetch_focal_mechanism", return_value=None), \
             mock.patch.object(usgs_listener, "_activate_fast_poll"):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "us-upgrade")

    def test_retro_download_failure_preserves_existing_result(self):
        event = {
            "usgs_id": "us-retro",
            "quake_utc": "2026-05-25T00:00:00+00:00",
            "status": "scored",
            "prediction": {"detected": True},
            "score": {"tsunami_confirmed": True},
            "scored": True,
            "detector_run": True,
            "rinex_downloaded": True,
        }
        queue_retroactive_reprocess(event, "new stations on CDDIS: GUAM", {"stations": ["guam"]})

        saved = {}

        def save_queue(q):
            saved["queue"] = q

        with mock.patch.object(rinex_downloader, "get_credentials", return_value=("user", "pass")), \
             mock.patch.object(rinex_downloader, "refresh_rolling_cache"), \
             mock.patch.object(rinex_downloader, "load_queue", return_value={"events": [event]}), \
             mock.patch.object(rinex_downloader, "save_queue", side_effect=save_queue), \
             mock.patch.object(rinex_downloader, "download_event", return_value=(0, "rinex_live/us-retro")):
            rinex_downloader.main(skip_retro_check=True)

        updated = saved["queue"]["events"][0]
        self.assertEqual(updated["status"], "scored")
        self.assertEqual(updated["prediction"], {"detected": True})
        self.assertEqual(updated["score"], {"tsunami_confirmed": True})
        self.assertTrue(updated["scored"])
        self.assertTrue(updated["detector_run"])
        self.assertNotIn("retroactive_pending", updated)

    def test_detector_uses_manifest_aliases_and_adjacent_days(self):
        quake_dt = datetime(2026, 5, 26, 23, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            rinex_dir = Path(tmp)
            manifest = {
                "days": [
                    {"year": 2026, "doy": 146, "resolved": {"guam": "gvim"}, "files": 2},
                    {"year": 2026, "doy": 147, "resolved": {"guam": "gvim"}, "files": 2},
                ]
            }
            (rinex_dir / "rinex_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            day0 = rinex_dir / "gvim1460.26o.gz"
            day1 = rinex_dir / "gvim1470.26o.gz"
            day0.write_bytes(b"rinex")
            day1.write_bytes(b"rinex")

            paths = detector_runner._rinex_station_paths(rinex_dir, "guam", quake_dt)

        self.assertEqual([p[0].name for p in paths], ["gvim1460.26o.gz", "gvim1470.26o.gz"])

    def test_pipeline_once_exits_in_ci_even_when_fast_poll_active(self):
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        state = {
            "active": True,
            "expires_utc": expires,
            "poll_interval_sec": 120,
            "trigger_mag": 7.0,
            "trigger_place": "near Japan",
        }
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                Path("fast_poll.json").write_text(json.dumps(state), encoding="utf-8")
                calls = []
                with mock.patch.dict(os.environ, {"CI": "true"}), \
                     mock.patch.object(pipeline, "run_pipeline", side_effect=lambda: calls.append("run")), \
                     mock.patch.object(pipeline.time, "sleep", side_effect=AssertionError("sleep called")):
                    pipeline.main(once=True)
            finally:
                os.chdir(old_cwd)

        self.assertEqual(calls, ["run"])


if __name__ == "__main__":
    unittest.main()
