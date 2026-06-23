import importlib
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[1]


class CriticalRegressionTests(unittest.TestCase):
    def test_seen_ids_do_not_block_later_usgs_upgrade(self):
        usgs_listener = importlib.import_module("usgs_listener")
        feature = {
            "id": "upgrade-now-qualifies",
            "properties": {
                "mag": 6.7,
                "place": "Pacific test event",
                "type": "earthquake",
                "time": 1893456000000,
            },
            "geometry": {"coordinates": [150.0, 10.0, 20.0]},
        }
        candidate = {
            "usgs_id": feature["id"],
            "status": "queued",
            "magnitude": 6.7,
            "place": "Pacific test event",
            "zones": ["test"],
            "primary_anchor": "guam",
            "detection_window": {
                "tec_onset_window": [3.0, 5.0],
                "expected_lead_time_min": 120,
            },
        }
        queue = {"events": [], "seen_ids": [feature["id"]]}

        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[feature]), \
             mock.patch.object(usgs_listener, "assess_event", return_value=candidate), \
             mock.patch.object(usgs_listener, "in_pacific_zone", return_value=["test"]):
            new, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual([event["usgs_id"] for event in queue["events"]], [feature["id"]])
        self.assertEqual(queue["seen_ids"].count(feature["id"]), 1)

    def test_workflow_does_not_preconsume_candidates(self):
        workflow = (REPO / ".github" / "workflows" / "pipeline-push.yml").read_text(encoding="utf-8")

        self.assertIn("cancel-in-progress: true", workflow)
        self.assertNotIn("python usgs_listener.py --once", workflow)
        self.assertIn("python pipeline.py --once", workflow)

    def test_discord_failure_does_not_ack_pipeline_alert(self):
        queue = {"events": [{"usgs_id": "evt1", "status": "predicted"}]}
        usgs_stub = types.SimpleNamespace(
            load_queue=lambda: queue,
            check_feed=lambda q: (0, []),
            save_queue=lambda q: None,
            write_poll_log=lambda new, q, near_misses: None,
        )
        notify_discord_stub = types.SimpleNamespace(
            send_near_miss_alerts=lambda near_misses: True,
            send_retroactive_triggered=lambda info: True,
            send_detection_alert=lambda event: False,
            send_retroactive_completed=lambda event: False,
            send_retroactive_aborted=lambda event, detail: False,
            send_pipeline_error=lambda component, err: False,
        )
        stubs = {
            "usgs_listener": usgs_stub,
            "rinex_downloader": types.SimpleNamespace(main=lambda: []),
            "detector_runner": types.SimpleNamespace(main=lambda: None),
            "scorer": types.SimpleNamespace(main=lambda: None),
            "notify": types.SimpleNamespace(send_event_alert=lambda events: None),
            "notify_discord": notify_discord_stub,
            "dyfi_poller": types.SimpleNamespace(run=lambda: None),
        }

        with mock.patch.dict(sys.modules, stubs):
            spec = importlib.util.spec_from_file_location("pipeline_under_test", REPO / "pipeline.py")
            pipeline = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pipeline)
            pipeline.run_pipeline()

        self.assertNotIn("discord_alerted", queue["events"][0])

    def test_notify_discord_reports_missing_webhook_failure(self):
        notify_discord = importlib.import_module("notify_discord")
        event = {"magnitude": 7.0, "place": "Pacific", "quake_utc": "2026-01-01T00:00:00+00:00"}

        with mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}, clear=False):
            self.assertFalse(notify_discord.send_detection_alert(event))

    def test_retroactive_zero_file_download_preserves_prior_prediction(self):
        rinex_downloader = importlib.import_module("rinex_downloader")
        old_env = {k: os.environ.get(k) for k in ("EARTHDATA_USER", "EARTHDATA_PASS")}
        event = {
            "usgs_id": "retro-zero",
            "quake_utc": "2026-01-01T00:00:00+00:00",
            "magnitude": 7.1,
            "status": "scored",
            "rinex_downloaded": True,
            "detector_run": True,
            "scored": True,
            "prediction": {"detected": True},
            "score": {"hit": True},
            "rinex_dir": "rinex_live/retro-zero",
            "rinex_coverage": {"stations": ["guam"], "n_stations": 1},
            "retroactive_pending": True,
            "retro_trigger_reason": "new coverage",
        }

        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                os.environ["EARTHDATA_USER"] = "user"
                os.environ["EARTHDATA_PASS"] = "pass"
                event_dir = Path(event["rinex_dir"])
                event_dir.mkdir(parents=True)
                manifest = event_dir / "rinex_manifest.json"
                manifest.write_text(json.dumps({"total_files": 2, "days": []}), encoding="utf-8")
                Path("event_queue.json").write_text(json.dumps({"events": [event], "seen_ids": []}), encoding="utf-8")

                def fake_download(evt, auth):
                    evt["status"] = "rinex_failed"
                    evt.pop("prediction", None)
                    manifest.write_text(json.dumps({"total_files": 0, "days": []}), encoding="utf-8")
                    return 0, str(event_dir)

                with mock.patch.object(rinex_downloader, "refresh_rolling_cache", return_value={}), \
                     mock.patch.object(rinex_downloader, "download_event", side_effect=fake_download):
                    rinex_downloader.main(skip_retro_check=True)

                saved = json.loads(Path("event_queue.json").read_text(encoding="utf-8"))["events"][0]
                self.assertEqual(saved["status"], "scored")
                self.assertEqual(saved["prediction"], {"detected": True})
                self.assertEqual(saved["score"], {"hit": True})
                self.assertFalse(saved["retroactive_abort_alerted"])
                self.assertNotIn("retroactive_pending", saved)
                self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["total_files"], 2)
            finally:
                os.chdir(cwd)
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_detector_manifest_days_include_aliases_and_adjacent_days(self):
        heavy_stubs = {
            "numpy": types.SimpleNamespace(),
            "pandas": types.SimpleNamespace(),
            "matplotlib": types.SimpleNamespace(pyplot=types.SimpleNamespace()),
            "matplotlib.pyplot": types.SimpleNamespace(),
            "scipy": types.SimpleNamespace(signal=types.SimpleNamespace()),
            "scipy.signal": types.SimpleNamespace(butter=lambda *a, **k: None, filtfilt=lambda *a, **k: None),
            "space_weather": types.SimpleNamespace(get_space_weather_quality=lambda *a, **k: {}),
        }
        with mock.patch.dict(sys.modules, heavy_stubs):
            spec = importlib.util.spec_from_file_location("detector_under_test", REPO / "detector_runner.py")
            detector = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(detector)

        with tempfile.TemporaryDirectory() as tmp:
            rinex_dir = Path(tmp)
            (rinex_dir / "rinex_manifest.json").write_text(
                json.dumps(
                    {
                        "days": [
                            {"year": 2026, "doy": 1, "resolved": {"guam": "gvim"}},
                            {"year": 2026, "doy": 2, "resolved": {"guam": "gvim"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            days = detector._rinex_manifest_days(rinex_dir, detector.datetime(2026, 1, 1, tzinfo=detector.timezone.utc))

        self.assertEqual([day[1] for day in days], [1, 2])
        self.assertEqual(days[0][3]["guam"], "gvim")


if __name__ == "__main__":
    unittest.main()
