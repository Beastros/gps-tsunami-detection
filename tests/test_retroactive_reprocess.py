import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import retroactive_rinex
import scorer


@contextmanager
def temp_cwd():
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            yield Path(tmp)
        finally:
            os.chdir(previous)


def scored_event():
    return {
        "usgs_id": "us-test-1",
        "quake_utc": "2026-05-18T00:00:00+00:00",
        "magnitude": 7.1,
        "place": "Test Trench",
        "status": "scored",
        "scored": True,
        "scored_utc": "2026-05-19T01:00:00+00:00",
        "detector_run": True,
        "detector_run_utc": "2026-05-18T04:00:00+00:00",
        "rinex_downloaded": True,
        "rinex_dir": "rinex_live/us-test-1",
        "rinex_download_utc": "2026-05-18T03:30:00+00:00",
        "prediction": {"detected": True, "combined_confidence": 0.82},
        "score": {
            "usgs_id": "us-test-1",
            "outcome": "TRUE_POSITIVE",
            "combined_confidence": 0.82,
            "any_gauge_tsunami": True,
        },
        "discord_alerted": True,
    }


class RetroactiveReprocessTests(unittest.TestCase):
    def test_failed_retroactive_attempt_restores_prior_scored_result(self):
        with temp_cwd():
            old_score = {
                "usgs_id": "us-test-1",
                "outcome": "TRUE_POSITIVE",
                "combined_confidence": 0.82,
                "any_gauge_tsunami": True,
            }
            Path("running_log.json").write_text(
                json.dumps({"scored_events": [old_score], "summary": {"total_scored": 1}}),
                encoding="utf-8",
            )
            event = scored_event()

            retroactive_rinex.queue_retroactive_reprocess(
                event,
                "new stations on CDDIS: TEST",
                {"stations": ["test"], "n_stations": 1},
            )

            self.assertEqual(event["status"], "queued")
            self.assertFalse(event["scored"])
            self.assertNotIn("prediction", event)
            self.assertNotIn("score", event)
            self.assertTrue(event["retroactive_pending"])

            log_data = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
            self.assertEqual(log_data["scored_events"], [old_score])

            retroactive_rinex.restore_prior_result(
                event,
                "Retroactive RINEX download returned 0 files",
            )

            self.assertEqual(event["status"], "scored")
            self.assertTrue(event["scored"])
            self.assertTrue(event["detector_run"])
            self.assertTrue(event["rinex_downloaded"])
            self.assertEqual(event["prediction"]["combined_confidence"], 0.82)
            self.assertEqual(event["score"], old_score)
            self.assertNotIn("retroactive_pending", event)
            self.assertEqual(
                event["retroactive_abort_reason"],
                "Retroactive RINEX download returned 0 files",
            )

    def test_retroactive_rescore_replaces_prior_running_log_entry(self):
        with temp_cwd():
            old_score = {
                "usgs_id": "us-test-1",
                "outcome": "FALSE_POSITIVE",
                "combined_confidence": 0.2,
                "any_gauge_tsunami": False,
            }
            other_score = {
                "usgs_id": "us-other",
                "outcome": "TRUE_NEGATIVE",
                "combined_confidence": 0.1,
                "any_gauge_tsunami": False,
            }
            event = scored_event()
            event.update(
                {
                    "status": "predicted",
                    "scored": False,
                    "retroactive_trigger": True,
                    "retro_trigger_reason": "new stations on CDDIS: TEST",
                    "retroactive_pending": True,
                    "prediction": {"detected": False, "combined_confidence": 0.05},
                }
            )
            event.pop("score", None)
            Path("event_queue.json").write_text(
                json.dumps({"events": [event], "seen_ids": ["us-test-1"]}),
                encoding="utf-8",
            )
            Path("running_log.json").write_text(
                json.dumps({"scored_events": [old_score, other_score], "summary": {}}),
                encoding="utf-8",
            )
            new_score = {
                "usgs_id": "us-test-1",
                "outcome": "TRUE_NEGATIVE",
                "combined_confidence": 0.05,
                "any_gauge_tsunami": False,
            }

            with mock.patch.object(
                scorer,
                "fetch_all_gauges",
                return_value={"hilo": {"tsunami": None, "primary": True}},
            ), mock.patch.object(scorer, "score_event", return_value=new_score):
                scorer.main()

            queue = json.loads(Path("event_queue.json").read_text(encoding="utf-8"))
            updated_event = queue["events"][0]
            self.assertEqual(updated_event["status"], "scored")
            self.assertEqual(updated_event["score"], new_score)
            self.assertNotIn("retroactive_pending", updated_event)
            self.assertIn("retroactive_completed_utc", updated_event)

            log_data = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
            scored_ids = [item["usgs_id"] for item in log_data["scored_events"]]
            self.assertEqual(scored_ids, ["us-other", "us-test-1"])
            self.assertEqual(log_data["scored_events"][-1], new_score)


if __name__ == "__main__":
    unittest.main()
