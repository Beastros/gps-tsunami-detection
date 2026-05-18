import unittest
from unittest import mock

import retroactive_rinex


class RetroactiveRinexRollbackTest(unittest.TestCase):
    def test_failed_retroactive_run_restores_prior_scored_result(self):
        event = {
            "usgs_id": "us-test",
            "status": "scored",
            "prediction": {"detected": False, "reason": "no_coherent_pairs"},
            "score": {"usgs_id": "us-test", "outcome": "FALSE_NEGATIVE"},
            "scored": True,
            "scored_utc": "2026-05-17T01:27:30+00:00",
            "detector_run": True,
            "detector_run_utc": "2026-05-17T01:27:29+00:00",
            "rinex_downloaded": True,
            "rinex_dir": "rinex_live/us-test",
            "rinex_download_utc": "2026-05-17T01:27:26+00:00",
        }

        with mock.patch("rinex_downloader._clear_running_log_score") as clear_score:
            retroactive_rinex.queue_retroactive_reprocess(
                event,
                "new stations on CDDIS: HNLC",
                {"stations": ["hnlc"], "n_stations": 1, "days": []},
            )

        clear_score.assert_not_called()
        self.assertEqual(event["status"], "queued")
        self.assertTrue(event["retroactive_pending"])
        self.assertFalse(event["scored"])
        self.assertNotIn("prediction", event)
        self.assertNotIn("score", event)

        retroactive_rinex.restore_prior_result(event, "download returned 0 files")

        self.assertEqual(event["status"], "scored")
        self.assertTrue(event["scored"])
        self.assertTrue(event["detector_run"])
        self.assertTrue(event["rinex_downloaded"])
        self.assertEqual(event["prediction"]["reason"], "no_coherent_pairs")
        self.assertEqual(event["score"]["outcome"], "FALSE_NEGATIVE")
        self.assertEqual(event["rinex_dir"], "rinex_live/us-test")
        self.assertNotIn("retroactive_pending", event)
        self.assertEqual(event["retroactive_abort_reason"], "download returned 0 files")


if __name__ == "__main__":
    unittest.main()
