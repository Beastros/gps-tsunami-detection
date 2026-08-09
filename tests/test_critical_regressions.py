import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import detector_runner
import pipeline
import rinex_downloader
import usgs_listener


def _feature(usgs_id="evt1", mag=6.4, depth=30.0):
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "near east coast of Honshu, Japan",
            "type": "earthquake",
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        "geometry": {"coordinates": [142.0, 38.5, depth]},
    }


class CriticalRegressionTests(unittest.TestCase):
    def test_usgs_upgrade_after_near_miss_can_queue(self):
        queue = {"events": [], "seen_ids": []}

        with (
            mock.patch.object(usgs_listener, "fetch_feed", return_value=[_feature(mag=6.4)]),
            mock.patch.object(usgs_listener, "_activate_fast_poll", return_value=None),
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual(queue["events"], [])
        self.assertNotIn("evt1", queue["seen_ids"])
        self.assertEqual(len(near_misses), 1)

        with (
            mock.patch.object(usgs_listener, "fetch_feed", return_value=[_feature(mag=6.6)]),
            mock.patch.object(
                usgs_listener,
                "fetch_focal_mechanism",
                return_value={"available": False, "fault_type": "unknown", "rake_score": 0.5},
            ),
            mock.patch.object(usgs_listener, "_activate_fast_poll", return_value=None),
        ):
            new_count, _ = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "evt1")

    def test_pipeline_does_not_ack_failed_discord_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                Path("event_queue.json").write_text(
                    json.dumps(
                        {
                            "events": [
                                {
                                    "usgs_id": "evt1",
                                    "status": "predicted",
                                    "prediction": {"detected": True},
                                }
                            ],
                            "seen_ids": ["evt1"],
                        }
                    ),
                    encoding="utf-8",
                )
                with (
                    mock.patch.object(pipeline.usgs_listener, "check_feed", return_value=(0, [])),
                    mock.patch.object(pipeline.notify_discord, "send_near_miss_alerts", return_value=True),
                    mock.patch.object(pipeline.rinex_downloader, "main", return_value=[]),
                    mock.patch.object(pipeline.detector_runner, "main", return_value=None),
                    mock.patch.object(pipeline.scorer, "main", return_value=None),
                    mock.patch.object(pipeline.dyfi_poller, "run", return_value=None),
                    mock.patch.object(pipeline.notify_discord, "send_detection_alert", return_value=False),
                ):
                    pipeline.run_pipeline()

                queue = json.loads(Path("event_queue.json").read_text(encoding="utf-8"))
                self.assertNotIn("discord_alerted", queue["events"][0])

                with (
                    mock.patch.object(pipeline.usgs_listener, "check_feed", return_value=(0, [])),
                    mock.patch.object(pipeline.notify_discord, "send_near_miss_alerts", return_value=True),
                    mock.patch.object(pipeline.rinex_downloader, "main", return_value=[]),
                    mock.patch.object(pipeline.detector_runner, "main", return_value=None),
                    mock.patch.object(pipeline.scorer, "main", return_value=None),
                    mock.patch.object(pipeline.dyfi_poller, "run", return_value=None),
                    mock.patch.object(pipeline.notify_discord, "send_detection_alert", return_value=True),
                ):
                    pipeline.run_pipeline()

                queue = json.loads(Path("event_queue.json").read_text(encoding="utf-8"))
                self.assertTrue(queue["events"][0]["discord_alerted"])
            finally:
                os.chdir(old_cwd)

    def test_pipeline_once_exits_in_ci_even_with_fast_poll(self):
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            old_ci = os.environ.get("CI")
            os.chdir(td)
            os.environ["CI"] = "true"
            try:
                expires = datetime.now(timezone.utc) + timedelta(hours=1)
                Path("fast_poll.json").write_text(
                    json.dumps(
                        {
                            "active": True,
                            "expires_utc": expires.isoformat(),
                            "poll_interval_sec": 120,
                        }
                    ),
                    encoding="utf-8",
                )
                calls = []

                def _run_once():
                    calls.append("run")

                with mock.patch.object(pipeline, "run_pipeline", side_effect=_run_once):
                    pipeline.main(once=True)

                self.assertEqual(calls, ["run"])
            finally:
                if old_ci is None:
                    os.environ.pop("CI", None)
                else:
                    os.environ["CI"] = old_ci
                os.chdir(old_cwd)

    def test_retroactive_zero_file_download_preserves_prior_score(self):
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                event = {
                    "usgs_id": "evt1",
                    "quake_utc": "2026-06-01T00:00:00+00:00",
                    "magnitude": 7.1,
                    "place": "Japan",
                    "status": "scored",
                    "rinex_downloaded": True,
                    "detector_run": True,
                    "scored": True,
                    "prediction": {"detected": True, "stations_processed": ["guam", "hnlc"]},
                    "score": {"outcome": "TRUE_POSITIVE"},
                    "rinex_dir": "rinex_live/evt1",
                    "rinex_coverage": {"stations": ["guam", "hnlc"], "n_stations": 2},
                }
                Path("rinex_live/evt1").mkdir(parents=True)
                old_manifest = {"total_files": 4, "days": []}
                Path("rinex_live/evt1/rinex_manifest.json").write_text(
                    json.dumps(old_manifest),
                    encoding="utf-8",
                )
                Path("running_log.json").write_text(
                    json.dumps({"scored_events": [{"usgs_id": "evt1"}], "summary": {"total_scored": 1}}),
                    encoding="utf-8",
                )

                event["retro_prior_state"] = rinex_downloader.snapshot_retro_prior_state(event)
                rinex_downloader.reset_event_for_reprocess(
                    event, preserve_existing_result=True
                )
                event["retroactive_pending"] = True
                queue = {"events": [event], "seen_ids": ["evt1"]}
                Path("event_queue.json").write_text(json.dumps(queue), encoding="utf-8")

                def _zero_download(evt, _auth):
                    Path("rinex_live/evt1/rinex_manifest.json").write_text(
                        json.dumps({"total_files": 0, "days": []}),
                        encoding="utf-8",
                    )
                    return 0, "rinex_live/evt1"

                with (
                    mock.patch.object(rinex_downloader, "get_credentials", return_value=("user", "pass")),
                    mock.patch.object(rinex_downloader, "refresh_rolling_cache", return_value={}),
                    mock.patch.object(rinex_downloader, "download_event", side_effect=_zero_download),
                ):
                    rinex_downloader.main(skip_retro_check=True)

                saved = json.loads(Path("event_queue.json").read_text(encoding="utf-8"))
                saved_event = saved["events"][0]
                self.assertEqual(saved_event["status"], "scored")
                self.assertTrue(saved_event["scored"])
                self.assertEqual(saved_event["prediction"]["detected"], True)
                self.assertEqual(saved_event["score"]["outcome"], "TRUE_POSITIVE")
                self.assertTrue(saved_event["retroactive_aborted"])
                self.assertEqual(
                    json.loads(Path("rinex_live/evt1/rinex_manifest.json").read_text(encoding="utf-8")),
                    old_manifest,
                )
                running_log = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
                self.assertEqual(running_log["scored_events"], [{"usgs_id": "evt1"}])
            finally:
                os.chdir(old_cwd)

    def test_detector_uses_manifest_aliases_on_adjacent_days(self):
        with tempfile.TemporaryDirectory() as td:
            rinex_dir = Path(td)
            quake_dt = datetime(2026, 6, 1, 23, 30, tzinfo=timezone.utc)
            next_dt = quake_dt + timedelta(days=1)
            next_doy = next_dt.timetuple().tm_yday
            yr2 = str(next_dt.year)[-2:]
            (rinex_dir / f"gvim{next_doy:03d}0.{yr2}o.Z").write_text("rinex", encoding="utf-8")
            manifest = {
                "days": [
                    {
                        "year": next_dt.year,
                        "doy": next_doy,
                        "resolved": {"guam": "gvim"},
                    }
                ]
            }
            (rinex_dir / "rinex_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            loaded = detector_runner._load_rinex_manifest(rinex_dir)
            event_days = detector_runner._event_days(quake_dt)
            calls = []

            def _fake_compute(path, _nav, _lat, _lon, _alt):
                calls.append(Path(path).name)
                return pd.Series(
                    [1.0],
                    index=[pd.Timestamp("2026-06-02T00:30:00Z")],
                )

            with (
                mock.patch.object(detector_runner, "decompress", side_effect=lambda p: p),
                mock.patch.object(detector_runner, "compute_tec", side_effect=_fake_compute),
            ):
                filt = detector_runner._load_station_filter(
                    rinex_dir, "guam", event_days, loaded
                )

            self.assertIsNotNone(filt)
            self.assertEqual(calls, [f"gvim{next_doy:03d}0.{yr2}o.Z"])


if __name__ == "__main__":
    unittest.main()
