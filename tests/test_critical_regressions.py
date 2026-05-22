import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import detector_runner
import pipeline
import usgs_listener
from retroactive_rinex import queue_retroactive_reprocess
from rinex_downloader import clear_event_outputs_for_replacement


def _feature(usgs_id, mag, *, lon=142.25, lat=38.913, depth=20.0):
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "test event near Japan",
            "type": "earthquake",
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        "geometry": {"coordinates": [lon, lat, depth]},
    }


class CriticalRegressionTests(unittest.TestCase):
    def test_seen_near_miss_can_queue_after_magnitude_upgrade(self):
        queue = {"events": [], "seen_ids": ["upgrade-event"]}

        with (
            patch.object(usgs_listener, "fetch_feed", return_value=[_feature("upgrade-event", 6.7)]),
            patch.object(usgs_listener, "fetch_focal_mechanism", return_value=None),
            patch.object(usgs_listener, "_activate_fast_poll"),
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "upgrade-event")
        self.assertEqual(queue["seen_ids"].count("upgrade-event"), 1)

    def test_detector_uses_manifest_aliases_and_next_day_rinex(self):
        quake_dt = datetime(2026, 5, 16, 11, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            rinex_dir = Path(td)
            manifest = {
                "days": [
                    {"year": 2026, "doy": 136, "resolved": {"guam": "gvim"}},
                    {"year": 2026, "doy": 137, "resolved": {"guam": "guam"}},
                ]
            }
            (rinex_dir / "rinex_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (rinex_dir / "gvim1360.26o.gz").write_bytes(b"obs day 0")
            (rinex_dir / "guam1370.26o.gz").write_bytes(b"obs day 1")

            seen_files = []

            def fake_compute(obs_path, _nav, _lat, _lon, _alt):
                seen_files.append(Path(obs_path).name)
                idx = pd.DatetimeIndex(
                    [pd.Timestamp("2026-05-16T00:00:00Z") + pd.Timedelta(days=len(seen_files) - 1)]
                )
                return pd.Series([float(len(seen_files))], index=idx)

            with (
                patch.object(detector_runner, "decompress", side_effect=lambda p: p),
                patch.object(detector_runner, "compute_tec", side_effect=fake_compute),
            ):
                filt = detector_runner._load_station_filter(
                    rinex_dir,
                    "guam",
                    quake_dt,
                    detector_runner._load_rinex_manifest(rinex_dir),
                )

        self.assertEqual(seen_files, ["gvim1360.26o.gz", "guam1370.26o.gz"])
        self.assertEqual(list(filt.values), [1.0, 2.0])

    def test_retroactive_queue_preserves_existing_outputs_until_replacement(self):
        event = {
            "usgs_id": "existing-event",
            "status": "scored",
            "rinex_downloaded": True,
            "detector_run": True,
            "scored": True,
            "prediction": {"detected": False, "reason": "no_coherent_pairs"},
            "score": {"outcome": "TRUE_NEGATIVE"},
        }

        queue_retroactive_reprocess(
            event,
            "new stations on CDDIS: GUAM",
            {"stations": ["guam"], "n_stations": 1, "days": []},
        )

        self.assertEqual(event["status"], "scored")
        self.assertTrue(event["scored"])
        self.assertEqual(event["prediction"]["reason"], "no_coherent_pairs")
        self.assertEqual(event["score"]["outcome"], "TRUE_NEGATIVE")
        self.assertFalse(event["rinex_downloaded"])
        self.assertFalse(event["detector_run"])
        self.assertTrue(event["retroactive_pending"])

        clear_event_outputs_for_replacement(event)

        self.assertFalse(event["scored"])
        self.assertNotIn("prediction", event)
        self.assertNotIn("score", event)

    def test_pipeline_once_exits_in_ci_even_when_fast_poll_file_exists(self):
        with tempfile.TemporaryDirectory() as td:
            fast_poll = Path(td) / "fast_poll.json"
            fast_poll.write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_utc": "2999-01-01T00:00:00+00:00",
                        "poll_interval_sec": 120,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(pipeline, "run_pipeline") as run_pipeline,
                patch.object(pipeline, "Path", side_effect=lambda p=".": fast_poll if p == "fast_poll.json" else Path(p)),
                patch.dict(os.environ, {"CI": "true"}),
            ):
                pipeline.main(once=True)

        run_pipeline.assert_called_once()


if __name__ == "__main__":
    unittest.main()
