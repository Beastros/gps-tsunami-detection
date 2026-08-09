import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import detector_runner
import pipeline
import retroactive_rinex
import rinex_downloader
import usgs_listener


def _feature(usgs_id="us-upgrade", mag=7.1):
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "near east coast of Honshu, Japan",
            "type": "earthquake",
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        "geometry": {"coordinates": [142.0, 38.0, 20.0]},
    }


class CriticalRegressionTests(unittest.TestCase):
    def test_seen_id_does_not_block_later_qualifying_usgs_upgrade(self):
        queue = {"events": [], "seen_ids": ["us-upgrade"]}
        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[_feature()]), \
             mock.patch.object(usgs_listener, "fetch_focal_mechanism", return_value=None):
            new_count, _near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "us-upgrade")

    def test_failed_discord_detection_alert_is_not_acknowledged(self):
        queue = {
            "events": [
                {
                    "usgs_id": "evt-alert",
                    "status": "predicted",
                    "prediction": {"detected": True, "combined_confidence": 0.8},
                }
            ],
            "seen_ids": [],
        }
        saved = []

        with mock.patch.object(pipeline.usgs_listener, "load_queue", side_effect=[copy.deepcopy(queue), copy.deepcopy(queue)]), \
             mock.patch.object(pipeline.usgs_listener, "check_feed", return_value=(0, [])), \
             mock.patch.object(pipeline.usgs_listener, "write_poll_log"), \
             mock.patch.object(pipeline.usgs_listener, "save_queue", side_effect=lambda q: saved.append(copy.deepcopy(q))), \
             mock.patch.object(pipeline.rinex_downloader, "main", return_value=[]), \
             mock.patch.object(pipeline.detector_runner, "main"), \
             mock.patch.object(pipeline.scorer, "main"), \
             mock.patch.object(pipeline.dyfi_poller, "run"), \
             mock.patch.object(pipeline.notify_discord, "send_detection_alert", return_value=False):
            pipeline.run_pipeline()

        self.assertFalse(saved[-1]["events"][0].get("discord_alerted"))

    def test_pipeline_once_exits_fast_poll_in_ci(self):
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                expires = datetime.now(timezone.utc) + timedelta(hours=1)
                Path("fast_poll.json").write_text(
                    json.dumps({"active": True, "expires_utc": expires.isoformat()}),
                    encoding="utf-8",
                )
                with mock.patch.dict(os.environ, {"CI": "true"}), \
                     mock.patch.object(pipeline, "run_pipeline"), \
                     mock.patch.object(pipeline.time, "sleep", side_effect=AssertionError("slept in CI")):
                    pipeline.main(once=True)
            finally:
                os.chdir(old_cwd)

    def test_retroactive_queue_preserves_existing_prediction_score_and_log(self):
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                running_log = {"scored_events": [{"usgs_id": "evt-retro"}], "summary": {}}
                Path("running_log.json").write_text(json.dumps(running_log), encoding="utf-8")
                event = {
                    "usgs_id": "evt-retro",
                    "place": "Japan",
                    "magnitude": 7.0,
                    "quake_utc": datetime.now(timezone.utc).isoformat(),
                    "status": "scored",
                    "prediction": {"detected": True},
                    "score": {"outcome": "TRUE_POSITIVE"},
                    "scored": True,
                    "rinex_downloaded": True,
                    "rinex_coverage": {"stations": ["guam"], "n_stations": 1},
                }

                retroactive_rinex.queue_retroactive_reprocess(
                    event,
                    "new stations on CDDIS: GGV",
                    {"stations": ["guam", "ggv"], "n_stations": 2},
                )

                self.assertEqual(event["status"], "scored")
                self.assertEqual(event["prediction"], {"detected": True})
                self.assertEqual(event["score"], {"outcome": "TRUE_POSITIVE"})
                self.assertTrue(event["scored"])
                self.assertTrue(event["retroactive_pending"])
                self.assertEqual(
                    json.loads(Path("running_log.json").read_text(encoding="utf-8")),
                    running_log,
                )
            finally:
                os.chdir(old_cwd)

    def test_retroactive_zero_file_download_restores_prior_state_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                event_dir = Path("rinex_live") / "evt-zero"
                event_dir.mkdir(parents=True)
                old_manifest = {"total_files": 4, "days": [{"resolved": {"guam": "gvim"}}]}
                (event_dir / "rinex_manifest.json").write_text(
                    json.dumps(old_manifest), encoding="utf-8"
                )
                event = {
                    "usgs_id": "evt-zero",
                    "quake_utc": datetime.now(timezone.utc).isoformat(),
                    "status": "scored",
                    "prediction": {"detected": False},
                    "score": {"outcome": "TRUE_NEGATIVE"},
                    "scored": True,
                    "rinex_downloaded": True,
                    "rinex_dir": str(event_dir),
                    "rinex_coverage": {"stations": ["guam"], "n_stations": 1},
                    "retroactive_pending": True,
                }
                queue = {"events": [event], "seen_ids": []}

                def zero_download(evt, _auth):
                    evt["rinex_coverage"] = {"stations": [], "n_stations": 0}
                    (event_dir / "rinex_manifest.json").write_text(
                        json.dumps({"total_files": 0, "days": []}), encoding="utf-8"
                    )
                    return 0, str(event_dir)

                with mock.patch.object(rinex_downloader, "get_credentials", return_value=("u", "p")), \
                     mock.patch.object(rinex_downloader, "refresh_rolling_cache"), \
                     mock.patch.object(rinex_downloader, "load_queue", return_value=queue), \
                     mock.patch.object(rinex_downloader, "save_queue"), \
                     mock.patch.object(rinex_downloader, "download_event", side_effect=zero_download):
                    rinex_downloader.main(skip_retro_check=True)

                self.assertEqual(event["status"], "scored")
                self.assertEqual(event["prediction"], {"detected": False})
                self.assertEqual(event["score"], {"outcome": "TRUE_NEGATIVE"})
                self.assertEqual(event["rinex_coverage"], {"stations": ["guam"], "n_stations": 1})
                self.assertTrue(event["retroactive_abort_pending"])
                self.assertNotIn("retroactive_pending", event)
                self.assertEqual(
                    json.loads((event_dir / "rinex_manifest.json").read_text(encoding="utf-8")),
                    old_manifest,
                )
            finally:
                os.chdir(old_cwd)

    def test_detector_rinex_lookup_uses_manifest_alias_on_adjacent_day(self):
        with tempfile.TemporaryDirectory() as td:
            rinex_dir = Path(td)
            manifest = {
                "days": [
                    {"year": 2026, "doy": 167, "resolved": {"guam": "gvim"}, "files": 2}
                ]
            }
            target = rinex_dir / "gvim1670.26o.gz"
            target.write_bytes(b"placeholder")

            found = detector_runner._rinex_obs_path(
                rinex_dir,
                "guam",
                [(166, "26"), (167, "26")],
                manifest=manifest,
            )

        self.assertEqual(found, target)


if __name__ == "__main__":
    unittest.main()
