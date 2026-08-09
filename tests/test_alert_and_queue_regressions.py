import importlib
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock
from datetime import datetime, timezone


REPO_ROOT = Path(__file__).resolve().parents[1]


def _feature(usgs_id="upgraded", mag=6.6):
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "Test event near Japan",
            "type": "earthquake",
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        "geometry": {"coordinates": [140.0, 40.0, 12.0]},
    }


class UsgsSeenIdRegressionTests(unittest.TestCase):
    def test_seen_id_does_not_block_unqueued_upgrade(self):
        import usgs_listener

        queue = {"events": [], "seen_ids": ["upgraded"]}
        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[_feature()]), \
             mock.patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False}), \
             mock.patch.object(usgs_listener, "_activate_fast_poll"):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "upgraded")

    def test_already_queued_event_is_still_deduped(self):
        import usgs_listener

        queue = {"events": [{"usgs_id": "queued"}], "seen_ids": []}
        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[_feature("queued")]), \
             mock.patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False}), \
             mock.patch.object(usgs_listener, "_activate_fast_poll"):
            new_count, _ = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual(len(queue["events"]), 1)
        self.assertIn("queued", queue["seen_ids"])


class DiscordAckRegressionTests(unittest.TestCase):
    def test_discord_send_reports_malformed_webhook_failure(self):
        import notify_discord

        with mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}):
            self.assertFalse(notify_discord.send_detection_alert({"usgs_id": "x"}))

    def test_pipeline_does_not_ack_failed_discord_delivery(self):
        queue = {"events": [{"usgs_id": "x", "status": "predicted"}]}
        pipeline = self._import_pipeline_with_stubs(
            queue,
            send_detection_alert=lambda evt: False,
        )

        pipeline.run_pipeline()

        self.assertNotIn("discord_alerted", queue["events"][0])

    def test_pipeline_once_exits_in_ci_when_fast_poll_is_active(self):
        queue = {"events": []}
        pipeline = self._import_pipeline_with_stubs(queue)
        calls = []
        pipeline.run_pipeline = lambda: calls.append("cycle")

        fast_poll = REPO_ROOT / "fast_poll.json"
        previous_fast_poll = fast_poll.read_bytes() if fast_poll.exists() else None
        fast_poll.write_text(
            json.dumps(
                {
                    "active": True,
                    "expires_utc": "2999-01-01T00:00:00+00:00",
                    "poll_interval_sec": 999,
                }
            ),
            encoding="utf-8",
        )
        try:
            with mock.patch.dict(os.environ, {"CI": "true"}), \
                 mock.patch.object(pipeline.time, "sleep", side_effect=AssertionError("slept in CI")):
                pipeline.main(once=True)
        finally:
            if previous_fast_poll is None:
                fast_poll.unlink(missing_ok=True)
            else:
                fast_poll.write_bytes(previous_fast_poll)

        self.assertEqual(calls, ["cycle"])

    def _import_pipeline_with_stubs(self, queue, send_detection_alert=None):
        fake_usgs = types.ModuleType("usgs_listener")
        fake_usgs.load_queue = lambda: queue
        fake_usgs.check_feed = lambda q: (0, [])
        fake_usgs.save_queue = lambda q: None
        fake_usgs.write_poll_log = lambda new, q, near_misses: None

        fake_rinex = types.ModuleType("rinex_downloader")
        fake_rinex.main = lambda: []

        fake_detector = types.ModuleType("detector_runner")
        fake_detector.main = lambda: None

        fake_scorer = types.ModuleType("scorer")
        fake_scorer.main = lambda: None

        fake_notify = types.ModuleType("notify")
        fake_notify.send_event_alert = lambda events: None

        fake_notify_discord = types.ModuleType("notify_discord")
        fake_notify_discord.send_detection_alert = send_detection_alert or (lambda evt: True)
        fake_notify_discord.send_retroactive_triggered = lambda info: True
        fake_notify_discord.send_retroactive_completed = lambda evt: True
        fake_notify_discord.send_retroactive_aborted = lambda evt, detail: True
        fake_notify_discord.send_near_miss_alerts = lambda near_misses: True
        fake_notify_discord.send_pipeline_error = lambda component, err: True

        fake_dyfi = types.ModuleType("dyfi_poller")
        fake_dyfi.run = lambda: None

        modules = {
            "usgs_listener": fake_usgs,
            "rinex_downloader": fake_rinex,
            "detector_runner": fake_detector,
            "scorer": fake_scorer,
            "notify": fake_notify,
            "notify_discord": fake_notify_discord,
            "dyfi_poller": fake_dyfi,
        }
        sys.modules.pop("pipeline", None)
        with mock.patch.dict(sys.modules, modules):
            return importlib.import_module("pipeline")


class WorkflowRegressionTests(unittest.TestCase):
    def test_scheduled_workflow_does_not_preconsume_usgs_listener(self):
        workflow = (REPO_ROOT / ".github/workflows/pipeline-push.yml").read_text(encoding="utf-8")

        self.assertIn("cancel-in-progress: true", workflow)
        self.assertNotIn("python usgs_listener.py --once", workflow)
        self.assertIn("python pipeline.py --once", workflow)


if __name__ == "__main__":
    unittest.main()
