import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

import detector_runner
import notify_discord
import pipeline
import retroactive_rinex
import rinex_downloader
import usgs_listener


def _usgs_feature(usgs_id, mag):
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "Japan test event",
            "type": "earthquake",
            "time": int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000),
        },
        "geometry": {"coordinates": [142.0, 39.0, 20.0]},
    }


class CriticalRegressionTests(unittest.TestCase):
    def test_seen_id_does_not_block_later_magnitude_upgrade(self):
        queue = {"events": [], "seen_ids": []}

        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[_usgs_feature("upgrade1", 6.1)]):
            new, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new, 0)
        self.assertIn("upgrade1", queue["seen_ids"])
        self.assertEqual(len(queue["events"]), 0)
        self.assertEqual(len(near_misses), 1)

        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[_usgs_feature("upgrade1", 6.7)]), \
             mock.patch.object(usgs_listener, "fetch_focal_mechanism", return_value=None):
            new, _ = usgs_listener.check_feed(queue)

        self.assertEqual(new, 1)
        self.assertEqual([e["usgs_id"] for e in queue["events"]], ["upgrade1"])
        self.assertEqual(queue["seen_ids"].count("upgrade1"), 1)

        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[_usgs_feature("upgrade1", 7.0)]), \
             mock.patch.object(usgs_listener, "fetch_focal_mechanism", return_value=None):
            new, _ = usgs_listener.check_feed(queue)

        self.assertEqual(new, 0, "already queued events must still be deduped")
        self.assertEqual(len(queue["events"]), 1)

    def test_retroactive_download_failure_restores_prior_scored_state(self):
        event = {
            "usgs_id": "retro1",
            "quake_utc": "2026-05-31T00:00:00+00:00",
            "magnitude": 7.1,
            "place": "Retro test",
            "lat": 39.0,
            "lon": 142.0,
            "primary_anchor": "guam",
            "status": "scored",
            "rinex_downloaded": True,
            "detector_run": True,
            "scored": True,
            "prediction": {"detected": True, "combined_confidence": 0.62},
            "score": {"usgs_id": "retro1", "outcome": "TRUE_POSITIVE"},
            "discord_alerted": True,
        }
        queue = {"events": [event], "seen_ids": ["retro1"]}

        with tempfile.TemporaryDirectory() as td:
            cwd = os.getcwd()
            os.chdir(td)
            try:
                Path("running_log.json").write_text(
                    json.dumps(
                        {
                            "scored_events": [
                                {"usgs_id": "retro1", "outcome": "TRUE_POSITIVE"}
                            ],
                            "summary": {"total_scored": 1},
                        }
                    ),
                    encoding="utf-8",
                )

                retroactive_rinex.queue_retroactive_reprocess(
                    event,
                    "new stations on CDDIS: GVIM",
                    {"stations": ["guam"], "n_stations": 1},
                )

                self.assertEqual(event["status"], "scored")
                self.assertTrue(event["scored"])
                self.assertEqual(event["prediction"]["combined_confidence"], 0.62)
                self.assertEqual(
                    json.loads(Path("running_log.json").read_text(encoding="utf-8"))[
                        "scored_events"
                    ][0]["usgs_id"],
                    "retro1",
                )

                saved = []

                with mock.patch.object(rinex_downloader, "get_credentials", return_value=("u", "p")), \
                     mock.patch.object(rinex_downloader, "refresh_rolling_cache", return_value={}), \
                     mock.patch.object(rinex_downloader, "load_queue", return_value=queue), \
                     mock.patch.object(rinex_downloader, "save_queue", side_effect=lambda q: saved.append(json.loads(json.dumps(q)))), \
                     mock.patch.object(rinex_downloader, "download_event", return_value=(0, "rinex_live/retro1")):
                    rinex_downloader.main(skip_retro_check=True)

                self.assertTrue(saved)
                restored = queue["events"][0]
                self.assertEqual(restored["status"], "scored")
                self.assertTrue(restored["scored"])
                self.assertTrue(restored["rinex_downloaded"])
                self.assertTrue(restored["detector_run"])
                self.assertTrue(restored["discord_alerted"])
                self.assertEqual(restored["prediction"]["combined_confidence"], 0.62)
                self.assertEqual(restored["score"]["outcome"], "TRUE_POSITIVE")
                self.assertNotIn("retroactive_pending", restored)
                self.assertTrue(restored["retroactive_aborted"])
                self.assertEqual(
                    json.loads(Path("running_log.json").read_text(encoding="utf-8"))[
                        "scored_events"
                    ][0]["usgs_id"],
                    "retro1",
                )
            finally:
                os.chdir(cwd)

    def test_detector_uses_manifest_alias_and_next_day(self):
        with tempfile.TemporaryDirectory() as td:
            rinex_dir = Path(td)
            quake = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)
            next_day = quake + timedelta(days=1)
            manifest = {
                "days": [
                    {
                        "year": next_day.year,
                        "doy": next_day.timetuple().tm_yday,
                        "resolved": {"guam": "gvim"},
                        "files": 1,
                    }
                ]
            }
            (rinex_dir / "rinex_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            obs = rinex_dir / f"gvim{next_day.timetuple().tm_yday:03d}0.26o.Z"
            obs.write_bytes(b"rinex")

            days = detector_runner._event_rinex_days(quake)
            self.assertIn(
                (next_day.year, next_day.timetuple().tm_yday, "26"),
                days,
            )
            resolved = detector_runner._rinex_obs_path(
                rinex_dir,
                "guam",
                next_day.timetuple().tm_yday,
                "26",
                year=next_day.year,
            )
            self.assertEqual(resolved, obs)

    def test_discord_delivery_status_controls_alert_ack(self):
        event = {"usgs_id": "alert1", "status": "predicted"}
        queue = {"events": [event]}

        with mock.patch.object(pipeline.notify_discord, "send_detection_alert", return_value=False):
            pipeline.send_pending_discord_alerts(queue)
        self.assertNotIn("discord_alerted", event)

        with mock.patch.object(pipeline.notify_discord, "send_detection_alert", return_value=True):
            pipeline.send_pending_discord_alerts(queue)
        self.assertTrue(event["discord_alerted"])

    def test_post_webhook_returns_false_on_missing_or_http_failure(self):
        with mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}, clear=False):
            self.assertFalse(notify_discord._post_webhook({"content": "x"}))

        with mock.patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test"},
            clear=False,
        ):
            response = mock.Mock()
            response.__enter__ = mock.Mock(return_value=mock.Mock(status=500))
            response.__exit__ = mock.Mock(return_value=False)
            with mock.patch.object(notify_discord.urllib.request, "urlopen", return_value=response):
                self.assertFalse(notify_discord._post_webhook({"content": "x"}))

    def test_pipeline_once_exits_in_ci_when_fast_poll_active(self):
        with tempfile.TemporaryDirectory() as td:
            cwd = os.getcwd()
            os.chdir(td)
            try:
                Path("fast_poll.json").write_text(
                    json.dumps(
                        {
                            "active": True,
                            "expires_utc": (
                                datetime.now(timezone.utc) + timedelta(hours=1)
                            ).isoformat(),
                            "poll_interval_sec": 120,
                            "trigger_mag": 6.4,
                            "trigger_place": "Pacific",
                        }
                    ),
                    encoding="utf-8",
                )
                with mock.patch.dict(os.environ, {"CI": "true"}, clear=False), \
                     mock.patch.object(pipeline, "run_pipeline", return_value=None) as run_pipeline, \
                     mock.patch.object(pipeline.time, "sleep", side_effect=AssertionError("must not sleep")):
                    pipeline.main(once=True)

                self.assertEqual(run_pipeline.call_count, 1)
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
