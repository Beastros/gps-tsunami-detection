import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import detector_runner
import pipeline
import retroactive_rinex
import rinex_downloader
import usgs_listener


@contextmanager
def chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def usgs_feature(usgs_id="upgrade-event", mag=6.4):
    quake_ms = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000)
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "Kuril Islands",
            "type": "earthquake",
            "time": quake_ms,
        },
        "geometry": {"coordinates": [150.0, 45.0, 20.0]},
    }


class CriticalRegressionTests(unittest.TestCase):
    def test_seen_id_does_not_drop_later_qualifying_usgs_upgrade(self):
        queue = {"events": [], "seen_ids": []}

        with patch.object(usgs_listener, "fetch_feed", return_value=[usgs_feature(mag=6.4)]), patch.object(
            usgs_listener, "_activate_fast_poll", lambda *args, **kwargs: None
        ):
            first_new, _ = usgs_listener.check_feed(queue)

        self.assertEqual(first_new, 0)
        self.assertEqual(queue["seen_ids"], ["upgrade-event"])
        self.assertEqual(queue["events"], [])

        with patch.object(usgs_listener, "fetch_feed", return_value=[usgs_feature(mag=7.1)]), patch.object(
            usgs_listener,
            "fetch_focal_mechanism",
            return_value={
                "available": False,
                "fault_type": "unknown",
                "rake_deg": None,
                "rake_score": 0.5,
            },
        ), patch.object(usgs_listener, "_activate_fast_poll", lambda *args, **kwargs: None):
            second_new, _ = usgs_listener.check_feed(queue)

        self.assertEqual(second_new, 1)
        self.assertEqual(len(queue["events"]), 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "upgrade-event")
        self.assertEqual(queue["events"][0]["magnitude"], 7.1)

    def test_pipeline_does_not_ack_discord_alert_when_delivery_fails(self):
        queue_state = {
            "events": [
                {
                    "usgs_id": "alert-event",
                    "status": "predicted",
                    "prediction": {"detected": True},
                }
            ],
            "seen_ids": [],
        }
        saved = {}

        with patch.object(pipeline.usgs_listener, "load_queue", return_value=queue_state), patch.object(
            pipeline.usgs_listener, "check_feed", return_value=(0, [])
        ), patch.object(pipeline.usgs_listener, "write_poll_log", lambda *args, **kwargs: None), patch.object(
            pipeline.rinex_downloader, "main", return_value=[]
        ), patch.object(
            pipeline.detector_runner, "main", lambda: None
        ), patch.object(
            pipeline.scorer, "main", lambda: None
        ), patch.object(
            pipeline.dyfi_poller, "run", lambda: None
        ), patch.object(
            pipeline.notify_discord, "send_detection_alert", return_value=False
        ), patch.object(
            pipeline.usgs_listener, "save_queue", side_effect=lambda q: saved.update(q)
        ):
            pipeline.run_pipeline()

        self.assertNotIn("discord_alerted", saved["events"][0])

    def test_ci_once_exits_even_when_fast_poll_is_active(self):
        with tempfile.TemporaryDirectory() as td, chdir(td):
            Path("fast_poll.json").write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                        "poll_interval_sec": 120,
                        "trigger_mag": 6.6,
                        "trigger_place": "Kuril Islands",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(pipeline, "run_pipeline", lambda: None), patch.object(
                pipeline.time, "sleep", side_effect=AssertionError("CI --once must not sleep")
            ), patch.dict(os.environ, {"CI": "true"}):
                pipeline.main(once=True)

    def test_retroactive_queue_preserves_existing_result_until_download_success(self):
        with tempfile.TemporaryDirectory() as td, chdir(td):
            Path("running_log.json").write_text(
                json.dumps(
                    {
                        "scored_events": [{"usgs_id": "retro-event", "classification": "TRUE_POSITIVE"}],
                        "summary": {},
                    }
                ),
                encoding="utf-8",
            )
            event = {
                "usgs_id": "retro-event",
                "status": "scored",
                "prediction": {"detected": True},
                "score": {"classification": "TRUE_POSITIVE"},
                "scored": True,
                "rinex_downloaded": True,
                "detector_run": True,
                "quake_utc": datetime.now(timezone.utc).isoformat(),
            }

            retroactive_rinex.queue_retroactive_reprocess(
                event, "new stations on CDDIS: GUAM", {"stations": ["guam"]}
            )

            running_log = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
            self.assertEqual(event["status"], "queued")
            self.assertEqual(event["prediction"], {"detected": True})
            self.assertEqual(event["score"], {"classification": "TRUE_POSITIVE"})
            self.assertTrue(event["scored"])
            self.assertEqual(len(running_log["scored_events"]), 1)

    def test_retroactive_zero_file_download_restores_prior_result_and_manifest(self):
        prior_manifest = {"usgs_id": "retro-event", "total_files": 4, "days": []}
        event = {
            "usgs_id": "retro-event",
            "status": "queued",
            "prediction": {"detected": True},
            "score": {"classification": "TRUE_POSITIVE"},
            "scored": True,
            "rinex_downloaded": False,
            "detector_run": False,
            "quake_utc": datetime.now(timezone.utc).isoformat(),
            "retroactive_pending": True,
            "retro_prior_status": "scored",
            "retro_prior_prediction": {"detected": True},
            "retro_prior_score": {"classification": "TRUE_POSITIVE"},
            "retro_prior_scored": True,
            "retro_prior_detector_run": True,
            "retro_prior_rinex_downloaded": True,
            "rinex_coverage": {"stations": ["guam"], "n_stations": 1},
        }
        queue = {"events": [event], "seen_ids": []}

        with tempfile.TemporaryDirectory() as td, chdir(td):
            manifest_path = Path("rinex_live/retro-event/rinex_manifest.json")
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps(prior_manifest), encoding="utf-8")

            def fake_download(evt, auth):
                manifest_path.write_text(
                    json.dumps({"usgs_id": evt["usgs_id"], "total_files": 0, "days": []}),
                    encoding="utf-8",
                )
                evt["rinex_coverage"] = {"stations": ["new"], "n_stations": 1}
                return 0, str(manifest_path.parent)

            saved = {}
            with patch.object(rinex_downloader, "get_credentials", return_value=("user", "pass")), patch.object(
                rinex_downloader, "refresh_rolling_cache", lambda auth: None
            ), patch.object(rinex_downloader, "load_queue", return_value=queue), patch.object(
                rinex_downloader, "save_queue", side_effect=lambda q: saved.update(q)
            ), patch.object(
                rinex_downloader, "download_event", side_effect=fake_download
            ):
                rinex_downloader.main(skip_retro_check=True)

            restored = saved["events"][0]
            self.assertEqual(restored["status"], "scored")
            self.assertEqual(restored["prediction"], {"detected": True})
            self.assertEqual(restored["score"], {"classification": "TRUE_POSITIVE"})
            self.assertTrue(restored["scored"])
            self.assertTrue(restored["detector_run"])
            self.assertTrue(restored["rinex_downloaded"])
            self.assertTrue(restored["retroactive_aborted"])
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), prior_manifest)

    def test_detector_resolves_manifest_alias_on_adjacent_day(self):
        with tempfile.TemporaryDirectory() as td:
            rinex_dir = Path(td)
            quake_dt = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
            day2 = quake_dt + timedelta(days=1)
            doy2 = day2.timetuple().tm_yday
            yr2 = str(day2.year)[-2:]
            alias_obs = rinex_dir / f"gvim{doy2:03d}0.{yr2}o.Z"
            alias_obs.write_text("placeholder", encoding="utf-8")
            manifest = {
                "days": [
                    {
                        "year": day2.year,
                        "doy": doy2,
                        "resolved": {"guam": "gvim"},
                        "files": 1,
                    }
                ]
            }

            obs, _nav = detector_runner._rinex_paths_for_station(
                rinex_dir, "guam", quake_dt, manifest
            )

            self.assertEqual(obs, alias_obs)


if __name__ == "__main__":
    unittest.main()
