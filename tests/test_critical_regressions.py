import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CriticalRegressionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self._patches = []

    def tearDown(self):
        for obj, name, old in reversed(self._patches):
            setattr(obj, name, old)
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def patch_attr(self, obj, name, value):
        self._patches.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def test_seen_id_does_not_block_later_usgs_upgrade(self):
        import usgs_listener

        quake_ms = int(datetime(2026, 6, 4, tzinfo=timezone.utc).timestamp() * 1000)
        feature = {
            "id": "upgrade-me",
            "properties": {
                "mag": 6.6,
                "place": "near the east coast of Honshu, Japan",
                "type": "earthquake",
                "time": quake_ms,
            },
            "geometry": {"coordinates": [142.2, 38.9, 35.0]},
        }
        queue = {"events": [], "seen_ids": ["upgrade-me"]}

        self.patch_attr(usgs_listener, "fetch_feed", lambda: [feature])
        self.patch_attr(usgs_listener, "fetch_focal_mechanism", lambda _eid: None)

        new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(queue["events"][0]["usgs_id"], "upgrade-me")

    def test_pipeline_once_exits_even_when_fast_poll_is_active(self):
        import pipeline

        calls = {"runs": 0}

        def fake_run_pipeline():
            calls["runs"] += 1

        def fail_sleep(_seconds):
            raise AssertionError("--once mode must not sleep for fast-poll")

        Path("fast_poll.json").write_text(
            json.dumps(
                {
                    "active": True,
                    "expires_utc": "2999-01-01T00:00:00+00:00",
                    "poll_interval_sec": 120,
                }
            ),
            encoding="utf-8",
        )
        self.patch_attr(pipeline, "run_pipeline", fake_run_pipeline)
        self.patch_attr(pipeline.time, "sleep", fail_sleep)

        pipeline.main(once=True)

        self.assertEqual(calls["runs"], 1)

    def test_pipeline_marks_discord_alerted_only_after_delivery_success(self):
        import pipeline

        queue = {"events": [{"usgs_id": "evt1", "status": "predicted"}]}
        saved = []

        self.patch_attr(pipeline.usgs_listener, "load_queue", lambda: queue)
        self.patch_attr(pipeline.usgs_listener, "check_feed", lambda _queue: (0, []))
        self.patch_attr(
            pipeline.usgs_listener,
            "save_queue",
            lambda q: saved.append(copy.deepcopy(q)),
        )
        self.patch_attr(pipeline.usgs_listener, "write_poll_log", lambda *_args: None)
        self.patch_attr(pipeline.rinex_downloader, "main", lambda: [])
        self.patch_attr(pipeline.detector_runner, "main", lambda: None)
        self.patch_attr(pipeline.scorer, "main", lambda: None)
        self.patch_attr(pipeline.dyfi_poller, "run", lambda: None)
        self.patch_attr(pipeline.notify_discord, "send_detection_alert", lambda _evt: False)

        pipeline.run_pipeline()
        self.assertNotIn("discord_alerted", queue["events"][0])

        self.patch_attr(pipeline.notify_discord, "send_detection_alert", lambda _evt: True)
        pipeline.run_pipeline()
        self.assertTrue(queue["events"][0]["discord_alerted"])

    def test_retroactive_queue_preserves_existing_scored_result_until_download(self):
        import retroactive_rinex

        event = {
            "usgs_id": "retro1",
            "status": "scored",
            "rinex_downloaded": True,
            "detector_run": True,
            "scored": True,
            "prediction": {"detected": True},
            "score": {"classification": "TRUE_POSITIVE"},
        }

        retroactive_rinex.queue_retroactive_reprocess(
            event,
            "new stations on CDDIS: GUAM",
            {"stations": ["guam"], "n_stations": 1},
        )

        self.assertEqual(event["status"], "scored")
        self.assertTrue(event["rinex_downloaded"])
        self.assertTrue(event["detector_run"])
        self.assertTrue(event["scored"])
        self.assertEqual(event["prediction"], {"detected": True})
        self.assertEqual(event["score"], {"classification": "TRUE_POSITIVE"})
        self.assertTrue(event["retroactive_pending"])

    def test_retroactive_zero_file_download_preserves_existing_result_and_log(self):
        import rinex_downloader

        event_dir = Path("rinex_live/retro2")
        event_dir.mkdir(parents=True)
        old_manifest = {"total_files": 4, "days": [{"resolved": {"guam": "guam"}}]}
        (event_dir / "rinex_manifest.json").write_text(
            json.dumps(old_manifest), encoding="utf-8"
        )
        old_coverage = {"n_stations": 1, "stations": ["guam"]}
        event = {
            "usgs_id": "retro2",
            "quake_utc": "2026-06-01T00:00:00+00:00",
            "magnitude": 6.8,
            "status": "scored",
            "rinex_downloaded": True,
            "rinex_dir": str(event_dir),
            "detector_run": True,
            "scored": True,
            "prediction": {"detected": False},
            "score": {"classification": "TRUE_NEGATIVE"},
            "rinex_coverage": old_coverage,
            "retroactive_pending": True,
            "retro_trigger_reason": "new stations on CDDIS: TSKB",
        }
        queue = {"events": [event]}
        running_log = {"scored_events": [{"usgs_id": "retro2"}], "summary": {"total": 1}}
        Path("running_log.json").write_text(json.dumps(running_log), encoding="utf-8")

        self.patch_attr(rinex_downloader, "get_credentials", lambda: ("user", "pass"))
        self.patch_attr(rinex_downloader, "refresh_rolling_cache", lambda _auth: None)
        self.patch_attr(rinex_downloader, "load_queue", lambda: queue)

        def fake_download_event(evt, _auth):
            evt["rinex_coverage"] = {"n_stations": 0, "stations": []}
            (event_dir / "rinex_manifest.json").write_text(
                json.dumps({"total_files": 0, "days": []}), encoding="utf-8"
            )
            return 0, str(event_dir)

        self.patch_attr(rinex_downloader, "download_event", fake_download_event)

        rinex_downloader.main(skip_retro_check=True)

        self.assertEqual(event["status"], "scored")
        self.assertTrue(event["rinex_downloaded"])
        self.assertTrue(event["detector_run"])
        self.assertTrue(event["scored"])
        self.assertEqual(event["prediction"], {"detected": False})
        self.assertEqual(event["score"], {"classification": "TRUE_NEGATIVE"})
        self.assertEqual(event["rinex_coverage"], old_coverage)
        self.assertNotIn("retroactive_pending", event)
        self.assertIn("retroactive_abort_reason", event)
        self.assertEqual(
            json.loads((event_dir / "rinex_manifest.json").read_text(encoding="utf-8")),
            old_manifest,
        )
        self.assertEqual(
            json.loads(Path("running_log.json").read_text(encoding="utf-8")),
            running_log,
        )


if __name__ == "__main__":
    unittest.main()
