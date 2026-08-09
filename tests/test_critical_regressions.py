import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pipeline
import retroactive_rinex
import rinex_downloader


class TempCwd:
    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.getcwd()
        os.chdir(self._tmp.name)
        return Path(self._tmp.name)

    def __exit__(self, exc_type, exc, tb):
        os.chdir(self._old)
        self._tmp.cleanup()


def scored_event():
    return {
        "usgs_id": "us-test",
        "status": "scored",
        "quake_utc": "2026-05-28T00:00:00+00:00",
        "place": "Test Pacific quake",
        "magnitude": 7.1,
        "rinex_downloaded": True,
        "detector_run": True,
        "scored": True,
        "prediction": {"detected": True, "combined_confidence": 0.91},
        "score": {"outcome": "TRUE_POSITIVE"},
        "discord_alerted": True,
    }


class RetroactiveReprocessRegressionTests(unittest.TestCase):
    def test_retroactive_queue_and_failed_download_preserve_prior_result(self):
        with TempCwd():
            Path("running_log.json").write_text(
                json.dumps(
                    {
                        "scored_events": [
                            {"usgs_id": "us-test", "outcome": "TRUE_POSITIVE"}
                        ],
                        "summary": {"total_scored": 1},
                    }
                ),
                encoding="utf-8",
            )
            event = scored_event()

            retroactive_rinex.queue_retroactive_reprocess(
                event,
                "new stations on CDDIS: TEST",
                {"stations": ["test"], "n_stations": 1},
            )

            self.assertEqual(event["status"], "scored")
            self.assertTrue(event["detector_run"])
            self.assertEqual(event["prediction"]["detected"], True)
            self.assertEqual(event["score"]["outcome"], "TRUE_POSITIVE")
            self.assertTrue(event["retroactive_pending"])
            logged = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
            self.assertEqual(logged["scored_events"][0]["usgs_id"], "us-test")

            rinex_downloader._mark_retroactive_download_failed(
                event, "Download returned 0 files"
            )

            self.assertEqual(event["status"], "scored")
            self.assertEqual(event["prediction"]["detected"], True)
            self.assertEqual(event["score"]["outcome"], "TRUE_POSITIVE")
            self.assertNotIn("retroactive_pending", event)
            self.assertTrue(event["retroactive_download_failed"])
            logged = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
            self.assertEqual(len(logged["scored_events"]), 1)

    def test_successful_reprocess_clears_prior_result_after_files_exist(self):
        with TempCwd():
            Path("running_log.json").write_text(
                json.dumps(
                    {
                        "scored_events": [
                            {"usgs_id": "us-test", "outcome": "TRUE_POSITIVE"}
                        ],
                        "summary": {"total_scored": 1},
                    }
                ),
                encoding="utf-8",
            )
            event = scored_event()
            retroactive_rinex.queue_retroactive_reprocess(
                event,
                "new stations on CDDIS: TEST",
                {"stations": ["test"], "n_stations": 1},
            )

            rinex_downloader._prepare_successful_reprocess(event)

            self.assertEqual(event["status"], "queued")
            self.assertFalse(event["detector_run"])
            self.assertFalse(event["scored"])
            self.assertNotIn("prediction", event)
            self.assertNotIn("score", event)
            self.assertTrue(event["retroactive_pending"])
            logged = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
            self.assertEqual(logged["scored_events"], [])


class PipelineRegressionTests(unittest.TestCase):
    def test_ci_once_exits_even_when_fast_poll_is_active(self):
        with TempCwd():
            expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            Path("fast_poll.json").write_text(
                json.dumps(
                    {
                        "active": True,
                        "expires_utc": expires,
                        "poll_interval_sec": 1,
                        "trigger_mag": 6.4,
                        "trigger_place": "Test",
                    }
                ),
                encoding="utf-8",
            )
            calls = []
            with mock.patch.dict(os.environ, {"CI": "true"}, clear=False):
                with mock.patch.object(pipeline, "run_pipeline", side_effect=lambda: calls.append(1)):
                    pipeline.main(once=True)

            self.assertEqual(calls, [1])

    def test_failed_discord_detection_alert_is_not_marked_sent(self):
        first_queue = {"events": [], "seen_ids": []}
        detection_queue = {
            "events": [
                {
                    "usgs_id": "us-test",
                    "status": "predicted",
                    "discord_alerted": False,
                }
            ],
            "seen_ids": [],
        }

        with mock.patch.object(
            pipeline.usgs_listener,
            "load_queue",
            side_effect=[first_queue, detection_queue],
        ), mock.patch.object(
            pipeline.usgs_listener, "check_feed", return_value=(0, [])
        ), mock.patch.object(
            pipeline.usgs_listener, "save_queue"
        ), mock.patch.object(
            pipeline.usgs_listener, "write_poll_log"
        ), mock.patch.object(
            pipeline.rinex_downloader, "main", return_value=[]
        ), mock.patch.object(
            pipeline.detector_runner, "main"
        ), mock.patch.object(
            pipeline.scorer, "main"
        ), mock.patch.object(
            pipeline.dyfi_poller, "run"
        ), mock.patch.object(
            pipeline.notify_discord, "send_detection_alert", return_value=False
        ):
            pipeline.run_pipeline()

        self.assertFalse(detection_queue["events"][0].get("discord_alerted"))


if __name__ == "__main__":
    unittest.main()
