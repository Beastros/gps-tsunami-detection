import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

import detector_runner
import pipeline
import retroactive_rinex
import rinex_downloader
import usgs_listener


def _feature(event_id, mag):
    return {
        "id": event_id,
        "properties": {
            "mag": mag,
            "place": "near Honshu, Japan",
            "type": "earthquake",
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        "geometry": {"coordinates": [142.0, 38.0, 20.0]},
    }


class CriticalRegressionTests(unittest.TestCase):
    def test_seen_id_does_not_block_later_magnitude_upgrade(self):
        queue = {"events": [], "seen_ids": ["us-upgrade"]}
        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[_feature("us-upgrade", 6.6)]), \
             mock.patch.object(usgs_listener, "fetch_focal_mechanism", return_value=None), \
             mock.patch.object(usgs_listener, "_activate_fast_poll"):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(queue["events"][0]["usgs_id"], "us-upgrade")

    def test_failed_discord_detection_alert_is_not_acknowledged(self):
        queue = {
            "events": [
                {
                    "usgs_id": "us-alert",
                    "status": "predicted",
                    "prediction": {"detected": True},
                }
            ],
            "seen_ids": [],
        }
        saved = []

        with mock.patch.object(pipeline.usgs_listener, "load_queue", return_value=queue), \
             mock.patch.object(pipeline.usgs_listener, "check_feed", return_value=(0, [])), \
             mock.patch.object(pipeline.usgs_listener, "write_poll_log"), \
             mock.patch.object(pipeline.usgs_listener, "save_queue", side_effect=lambda q: saved.append(json.loads(json.dumps(q)))), \
             mock.patch.object(pipeline.rinex_downloader, "main", return_value=[]), \
             mock.patch.object(pipeline.detector_runner, "main"), \
             mock.patch.object(pipeline.scorer, "main"), \
             mock.patch.object(pipeline.dyfi_poller, "run"), \
             mock.patch.object(pipeline.notify_discord, "send_detection_alert", return_value=False):
            pipeline.run_pipeline()

        self.assertTrue(saved)
        self.assertNotIn("discord_alerted", queue["events"][0])

    def test_ci_once_exits_without_fast_poll_loop(self):
        state = {
            "active": True,
            "expires_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "poll_interval_sec": 120,
            "trigger_mag": 6.2,
            "trigger_place": "Pacific",
        }
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            old_ci = os.environ.get("CI")
            os.chdir(td)
            os.environ["CI"] = "true"
            Path("fast_poll.json").write_text(json.dumps(state), encoding="utf-8")
            calls = []
            try:
                with mock.patch.object(pipeline, "run_pipeline", side_effect=lambda: calls.append(1)):
                    pipeline.main(once=True)
            finally:
                if old_ci is None:
                    os.environ.pop("CI", None)
                else:
                    os.environ["CI"] = old_ci
                os.chdir(old_cwd)

        self.assertEqual(len(calls), 1)

    def test_retroactive_queue_preserves_existing_result_until_download(self):
        event = {
            "usgs_id": "us-retro",
            "status": "scored",
            "prediction": {"detected": True},
            "score": {"classification": "TRUE_POSITIVE"},
            "scored": True,
            "detector_run": True,
            "rinex_downloaded": True,
        }

        retroactive_rinex.queue_retroactive_reprocess(
            event,
            "new station coverage",
            {"stations": ["guam"], "n_stations": 1},
        )

        self.assertEqual(event["status"], "scored")
        self.assertEqual(event["prediction"], {"detected": True})
        self.assertEqual(event["score"], {"classification": "TRUE_POSITIVE"})
        self.assertTrue(event["scored"])
        self.assertTrue(event["retroactive_pending"])

    def test_retroactive_zero_file_download_restores_manifest_and_state(self):
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                event_dir = Path("rinex_live/us-retro")
                event_dir.mkdir(parents=True)
                manifest = {"usgs_id": "us-retro", "total_files": 4}
                (event_dir / "rinex_manifest.json").write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
                queue = {
                    "events": [
                        {
                            "usgs_id": "us-retro",
                            "status": "scored",
                            "prediction": {"detected": True},
                            "score": {"classification": "TRUE_POSITIVE"},
                            "scored": True,
                            "detector_run": True,
                            "rinex_downloaded": True,
                            "rinex_dir": str(event_dir),
                            "rinex_coverage": {"n_stations": 2},
                            "retroactive_pending": True,
                        }
                    ],
                    "seen_ids": [],
                }

                def fake_download(event, auth):
                    (event_dir / "rinex_manifest.json").write_text(
                        json.dumps({"usgs_id": "us-retro", "total_files": 0}),
                        encoding="utf-8",
                    )
                    event["rinex_coverage"] = {"n_stations": 0}
                    return 0, str(event_dir)

                with mock.patch.object(rinex_downloader, "get_credentials", return_value=("u", "p")), \
                     mock.patch.object(rinex_downloader, "refresh_rolling_cache"), \
                     mock.patch.object(rinex_downloader, "load_queue", return_value=queue), \
                     mock.patch.object(rinex_downloader, "save_queue"), \
                     mock.patch.object(rinex_downloader, "download_event", side_effect=fake_download):
                    rinex_downloader.main(skip_retro_check=True)

                event = queue["events"][0]
                self.assertEqual(event["status"], "scored")
                self.assertEqual(event["prediction"], {"detected": True})
                self.assertEqual(event["score"], {"classification": "TRUE_POSITIVE"})
                self.assertEqual(event["rinex_coverage"], {"n_stations": 2})
                self.assertTrue(event["retroactive_abort_pending"])
                self.assertNotIn("retroactive_pending", event)
                restored = json.loads((event_dir / "rinex_manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(restored, manifest)
            finally:
                os.chdir(old_cwd)

    def test_detector_uses_manifest_alias_on_adjacent_day(self):
        with tempfile.TemporaryDirectory() as td:
            event_dir = Path(td) / "rinex_live" / "us-detector"
            event_dir.mkdir(parents=True)
            manifest = {
                "usgs_id": "us-detector",
                "days": [
                    {
                        "year": 2025,
                        "doy": 2,
                        "resolved": {"guam": "gvim"},
                        "files": 1,
                    }
                ],
            }
            (event_dir / "rinex_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (event_dir / "gvim0020.25o.gz").write_text("obs", encoding="utf-8")
            event = {
                "usgs_id": "us-detector",
                "rinex_dir": str(event_dir),
                "quake_utc": "2025-01-01T23:30:00+00:00",
                "lat": 38.0,
                "lon": 142.0,
                "magnitude": 7.1,
                "place": "near Honshu, Japan",
            }
            processed = []

            def fake_decompress(path):
                return Path(str(path).removesuffix(".gz").removesuffix(".Z"))

            def fake_compute_tec(path, nav, lat, lon, alt):
                processed.append(Path(path).name)
                idx = pd.date_range("2025-01-02T00:00:00Z", periods=2, freq="30s")
                return pd.Series([0.0, 0.1], index=idx)

            with mock.patch.object(detector_runner, "decompress", side_effect=fake_decompress), \
                 mock.patch.object(detector_runner, "compute_tec", side_effect=fake_compute_tec), \
                 mock.patch.object(detector_runner, "compute_tec_for_constellation", return_value=None):
                prediction = detector_runner.run_event(event)

            self.assertEqual(prediction["reason"], "insufficient_stations")
            self.assertIn("gvim0020.25o", processed)


if __name__ == "__main__":
    unittest.main()
