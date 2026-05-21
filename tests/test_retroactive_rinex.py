import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import retroactive_rinex
import rinex_downloader


def _processed_event(**updates):
    event = {
        "usgs_id": "us-test",
        "quake_utc": "2026-05-15T11:22:01+00:00",
        "magnitude": 6.7,
        "place": "test event",
        "status": "scored",
        "rinex_downloaded": True,
        "detector_run": True,
        "scored": True,
        "prediction": {"detected": True, "combined_confidence": 0.91},
        "score": {"outcome": "TRUE_POSITIVE"},
        "discord_alerted": True,
        "rinex_dir": "rinex_live/us-test",
    }
    event.update(updates)
    return event


class RetroactiveRinexTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _write_queue(self, event):
        Path("event_queue.json").write_text(
            json.dumps({"events": [event]}), encoding="utf-8"
        )

    def _read_event(self):
        data = json.loads(Path("event_queue.json").read_text(encoding="utf-8"))
        return data["events"][0]

    def test_queue_retroactive_reprocess_preserves_current_result(self):
        event = _processed_event()
        Path("running_log.json").write_text(
            json.dumps({"scored_events": [{"usgs_id": "us-test"}], "summary": {}}),
            encoding="utf-8",
        )

        info = retroactive_rinex.queue_retroactive_reprocess(
            event,
            "new stations on CDDIS: GUAM",
            {"stations": ["guam"], "n_stations": 1},
        )

        self.assertEqual(info["usgs_id"], "us-test")
        self.assertTrue(event["retroactive_pending"])
        self.assertEqual(event["status"], "scored")
        self.assertTrue(event["rinex_downloaded"])
        self.assertTrue(event["detector_run"])
        self.assertTrue(event["scored"])
        self.assertEqual(event["prediction"]["combined_confidence"], 0.91)
        self.assertEqual(event["score"]["outcome"], "TRUE_POSITIVE")
        running_log = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
        self.assertEqual(running_log["scored_events"][0]["usgs_id"], "us-test")

    def test_retroactive_download_failure_preserves_current_result_for_abort_alert(self):
        event = _processed_event(
            retroactive_pending=True,
            retro_trigger_reason="new stations on CDDIS: GUAM",
        )
        self._write_queue(event)

        with patch.object(rinex_downloader, "get_credentials", return_value=("u", "p")), \
             patch.object(rinex_downloader, "refresh_rolling_cache", return_value={}), \
             patch.object(rinex_downloader, "download_event", return_value=(0, "rinex_live/us-test")):
            rinex_downloader.main(skip_retro_check=True)

        saved = self._read_event()
        self.assertEqual(saved["status"], "scored")
        self.assertTrue(saved["rinex_downloaded"])
        self.assertTrue(saved["detector_run"])
        self.assertTrue(saved["scored"])
        self.assertEqual(saved["prediction"]["combined_confidence"], 0.91)
        self.assertEqual(saved["score"]["outcome"], "TRUE_POSITIVE")
        self.assertTrue(saved["retroactive_pending"])
        self.assertTrue(saved["retroactive_download_failed"])
        self.assertEqual(saved["rinex_retries"], 1)

    def test_retroactive_download_success_resets_after_replacement_files_exist(self):
        event = _processed_event(
            retroactive_pending=True,
            retro_trigger_reason="new stations on CDDIS: GUAM",
            retro_prior_status="scored",
            retro_prior_prediction={"detected": True},
            retro_prior_detected=True,
        )
        self._write_queue(event)
        Path("running_log.json").write_text(
            json.dumps({"scored_events": [{"usgs_id": "us-test"}], "summary": {}}),
            encoding="utf-8",
        )

        with patch.object(rinex_downloader, "get_credentials", return_value=("u", "p")), \
             patch.object(rinex_downloader, "refresh_rolling_cache", return_value={}), \
             patch.object(rinex_downloader, "download_event", return_value=(2, "rinex_live/us-test")):
            rinex_downloader.main(skip_retro_check=True)

        saved = self._read_event()
        self.assertEqual(saved["status"], "rinex_ready")
        self.assertEqual(saved["rinex_dir"], "rinex_live/us-test")
        self.assertTrue(saved["rinex_downloaded"])
        self.assertFalse(saved["detector_run"])
        self.assertFalse(saved["scored"])
        self.assertNotIn("prediction", saved)
        self.assertNotIn("score", saved)
        self.assertNotIn("discord_alerted", saved)
        self.assertTrue(saved["retroactive_pending"])
        self.assertEqual(saved["retro_prior_status"], "scored")
        running_log = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
        self.assertEqual(running_log["scored_events"], [])


if __name__ == "__main__":
    unittest.main()
