import copy
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


class UsgsListenerQueueTests(unittest.TestCase):
    def _feature(self, *, event_id="upgrade-id", mag=6.6):
        return {
            "id": event_id,
            "properties": {
                "mag": mag,
                "place": "near the east coast of Honshu, Japan",
                "type": "earthquake",
                "time": 1781967600000,
            },
            "geometry": {
                "coordinates": [142.25, 38.913, 43.6],
            },
        }

    def test_seen_but_unqueued_event_can_queue_after_usgs_upgrade(self):
        import usgs_listener

        queue = {"events": [], "seen_ids": ["upgrade-id"]}
        with (
            mock.patch.object(usgs_listener, "fetch_feed", return_value=[self._feature()]),
            mock.patch.object(
                usgs_listener,
                "fetch_focal_mechanism",
                return_value={"available": False, "fault_type": "unknown"},
            ),
            mock.patch.object(usgs_listener, "_activate_fast_poll"),
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(queue["events"][0]["usgs_id"], "upgrade-id")
        self.assertEqual(queue["seen_ids"].count("upgrade-id"), 1)

    def test_already_queued_event_is_still_deduped(self):
        import usgs_listener

        queue = {
            "events": [{"usgs_id": "upgrade-id", "status": "queued"}],
            "seen_ids": ["upgrade-id"],
        }
        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[self._feature(mag=7.0)]):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)


class PipelineAlertAckTests(unittest.TestCase):
    def _import_pipeline_with_stubs(self, queue, discord_result):
        sys.modules.pop("pipeline", None)
        saved_queues = []

        usgs_listener = types.SimpleNamespace(
            load_queue=lambda: queue,
            check_feed=lambda q: (0, []),
            save_queue=lambda q: saved_queues.append(copy.deepcopy(q)),
            write_poll_log=lambda *args, **kwargs: None,
        )
        notify_discord = types.SimpleNamespace(
            send_near_miss_alerts=lambda near_misses: True,
            send_retroactive_triggered=lambda info: True,
            send_retroactive_completed=lambda evt: discord_result,
            send_retroactive_aborted=lambda evt, detail: discord_result,
            send_detection_alert=lambda evt: discord_result,
            send_pipeline_error=lambda component, err: True,
        )
        stubs = {
            "usgs_listener": usgs_listener,
            "rinex_downloader": types.SimpleNamespace(main=lambda: []),
            "detector_runner": types.SimpleNamespace(main=lambda: None),
            "scorer": types.SimpleNamespace(main=lambda: None),
            "notify": types.SimpleNamespace(send_event_alert=lambda events: None),
            "notify_discord": notify_discord,
            "dyfi_poller": types.SimpleNamespace(run=lambda: None),
        }

        prior_modules = {name: sys.modules.get(name) for name in stubs}
        sys.modules.update(stubs)
        try:
            pipeline = importlib.import_module("pipeline")
        finally:
            for name, prior in prior_modules.items():
                if prior is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = prior

        return pipeline, saved_queues

    def test_failed_discord_delivery_does_not_ack_detection(self):
        queue = {"events": [{"usgs_id": "pred-id", "status": "predicted"}]}
        pipeline, saved_queues = self._import_pipeline_with_stubs(queue, False)

        pipeline.run_pipeline()

        self.assertNotIn("discord_alerted", queue["events"][0])
        self.assertFalse(saved_queues[-1]["events"][0].get("discord_alerted"))

    def test_successful_discord_delivery_acks_detection(self):
        queue = {"events": [{"usgs_id": "pred-id", "status": "predicted"}]}
        pipeline, saved_queues = self._import_pipeline_with_stubs(queue, True)

        pipeline.run_pipeline()

        self.assertTrue(queue["events"][0]["discord_alerted"])
        self.assertTrue(saved_queues[-1]["events"][0]["discord_alerted"])

    def test_ci_once_exits_in_fast_poll_mode(self):
        queue = {"events": []}
        pipeline, _ = self._import_pipeline_with_stubs(queue, True)

        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
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
                with mock.patch.dict(os.environ, {"CI": "true"}):
                    pipeline.main(once=True)
            finally:
                os.chdir(old_cwd)


class DiscordWebhookTests(unittest.TestCase):
    def test_detection_alert_reports_malformed_webhook_failure(self):
        import notify_discord

        with mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}, clear=False):
            self.assertFalse(notify_discord.send_detection_alert({"usgs_id": "pred-id"}))


class WorkflowRegressionTests(unittest.TestCase):
    def test_pipeline_workflow_does_not_preconsume_usgs_feed(self):
        workflow = Path(".github/workflows/pipeline-push.yml").read_text(encoding="utf-8")

        self.assertNotIn("python usgs_listener.py --once", workflow)
        self.assertIn("cancel-in-progress: true", workflow)


if __name__ == "__main__":
    unittest.main()
