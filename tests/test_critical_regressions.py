import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

import detector_runner
import notify_discord
import pipeline
import retroactive_rinex
import rinex_downloader
import usgs_listener


class CriticalRegressionTests(unittest.TestCase):
    def test_discord_alert_not_acknowledged_when_delivery_fails(self):
        event = {
            "usgs_id": "evt-alert",
            "status": "predicted",
            "prediction": {"detected": True, "combined_confidence": 0.9},
            "magnitude": 7.1,
            "place": "Test quake",
            "quake_utc": "2026-06-14T00:00:00+00:00",
        }
        queue = {"events": [event], "seen_ids": []}
        saved = []

        with mock.patch.dict(os.environ, {}, clear=True), \
            mock.patch.object(pipeline.usgs_listener, "load_queue", return_value=queue), \
            mock.patch.object(pipeline.usgs_listener, "check_feed", return_value=(0, [])), \
            mock.patch.object(pipeline.usgs_listener, "write_poll_log"), \
            mock.patch.object(pipeline.usgs_listener, "save_queue", side_effect=lambda q: saved.append(json.loads(json.dumps(q)))), \
            mock.patch.object(pipeline.rinex_downloader, "main", return_value=[]), \
            mock.patch.object(pipeline.detector_runner, "main"), \
            mock.patch.object(pipeline.scorer, "main"), \
            mock.patch.object(pipeline.dyfi_poller, "run"):
            pipeline.run_pipeline()

        self.assertFalse(notify_discord.send_detection_alert(event))
        self.assertTrue(saved)
        self.assertNotIn("discord_alerted", saved[-1]["events"][0])

    def test_pipeline_once_exits_fast_poll_loop_in_ci(self):
        with tempfile.TemporaryDirectory() as td:
            prev_cwd = os.getcwd()
            os.chdir(td)
            try:
                Path("fast_poll.json").write_text(
                    json.dumps(
                        {
                            "active": True,
                            "expires_utc": "2999-01-01T00:00:00+00:00",
                            "trigger_mag": 6.4,
                            "trigger_place": "Test Pacific",
                            "poll_interval_sec": 120,
                        }
                    ),
                    encoding="utf-8",
                )
                with mock.patch.dict(os.environ, {"CI": "true"}), \
                    mock.patch.object(pipeline, "run_pipeline"), \
                    mock.patch.object(pipeline.time, "sleep", side_effect=AssertionError("CI --once must not sleep")):
                    pipeline.main(once=True)
            finally:
                os.chdir(prev_cwd)

    def test_seen_near_miss_can_queue_after_magnitude_upgrade(self):
        feature = {
            "id": "us-upgrade",
            "properties": {
                "mag": 6.7,
                "place": "near east coast of Honshu, Japan",
                "type": "earthquake",
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
            },
            "geometry": {"coordinates": [142.25, 38.9, 20.0]},
        }
        queue = {"events": [], "seen_ids": ["us-upgrade"]}

        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[feature]), \
            mock.patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False}):
            new_count, _near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "us-upgrade")

    def test_retroactive_zero_file_download_preserves_prior_result(self):
        with tempfile.TemporaryDirectory() as td:
            prev_cwd = os.getcwd()
            os.chdir(td)
            try:
                event_dir = Path("rinex_live") / "evt-retro"
                event_dir.mkdir(parents=True)
                manifest = event_dir / "rinex_manifest.json"
                manifest.write_text('{"total_files": 4, "days": []}', encoding="utf-8")
                event = {
                    "usgs_id": "evt-retro",
                    "quake_utc": "2026-06-13T00:00:00+00:00",
                    "magnitude": 7.0,
                    "place": "Test",
                    "lat": 0.0,
                    "lon": 160.0,
                    "status": "scored",
                    "rinex_downloaded": True,
                    "detector_run": True,
                    "scored": True,
                    "rinex_dir": str(event_dir),
                    "prediction": {"detected": True},
                    "score": {"ok": True},
                    "rinex_coverage": {"n_stations": 2, "stations": ["guam", "mkea"]},
                }
                retroactive_rinex.queue_retroactive_reprocess(
                    event,
                    "new stations on CDDIS: MKEA",
                    {"n_stations": 3, "stations": ["guam", "mkea", "kokb"]},
                )
                Path("event_queue.json").write_text(json.dumps({"events": [event], "seen_ids": []}), encoding="utf-8")
                Path("running_log.json").write_text(
                    json.dumps({"scored_events": [{"usgs_id": "evt-retro"}]}),
                    encoding="utf-8",
                )

                def fake_download(evt, _auth):
                    manifest.write_text('{"total_files": 0, "days": []}', encoding="utf-8")
                    evt["rinex_coverage"] = {"n_stations": 0, "stations": []}
                    return 0, str(event_dir)

                with mock.patch.object(rinex_downloader, "get_credentials", return_value=("u", "p")), \
                    mock.patch.object(rinex_downloader, "refresh_rolling_cache"), \
                    mock.patch.object(rinex_downloader, "download_event", side_effect=fake_download):
                    rinex_downloader.main(skip_retro_check=True)

                updated = json.loads(Path("event_queue.json").read_text(encoding="utf-8"))["events"][0]
                self.assertEqual(updated["status"], "scored")
                self.assertEqual(updated["prediction"], {"detected": True})
                self.assertEqual(updated["score"], {"ok": True})
                self.assertEqual(updated["rinex_coverage"]["n_stations"], 2)
                self.assertTrue(updated["retroactive_abort_pending"])
                self.assertEqual(manifest.read_text(encoding="utf-8"), '{"total_files": 4, "days": []}')
                running_log = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
                self.assertEqual(running_log["scored_events"], [{"usgs_id": "evt-retro"}])
            finally:
                os.chdir(prev_cwd)

    def test_detector_uses_manifest_aliases_and_adjacent_days(self):
        with tempfile.TemporaryDirectory() as td:
            rinex_dir = Path(td)
            quake_dt = datetime(2026, 6, 14, 23, 30, tzinfo=timezone.utc)
            next_day = datetime(2026, 6, 15, tzinfo=timezone.utc)
            next_doy = next_day.timetuple().tm_yday
            yr2 = str(next_day.year)[-2:]
            obs = rinex_dir / f"gvim{next_doy:03d}0.{yr2}o.gz"
            obs.write_bytes(b"dummy")
            manifest = {
                "days": [
                    {
                        "year": next_day.year,
                        "doy": next_doy,
                        "resolved": {"guam": "gvim"},
                        "files": 1,
                    }
                ]
            }
            days = detector_runner._rinex_days_from_manifest(manifest, quake_dt)
            series = pd.Series(
                [0.0, 1.0],
                index=pd.to_datetime(["2026-06-15T00:00:00Z", "2026-06-15T00:00:30Z"]),
            )

            with mock.patch.object(detector_runner, "decompress", side_effect=lambda p: p), \
                mock.patch.object(detector_runner, "compute_tec", return_value=series) as compute_tec:
                filt = detector_runner._compute_station_filter(rinex_dir, "guam", days, manifest)

            self.assertIsNotNone(filt)
            self.assertEqual(Path(compute_tec.call_args.args[0]).name, obs.name)


if __name__ == "__main__":
    unittest.main()
