import copy
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def chdir(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def load_module_from_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CriticalPipelineRegressionTests(unittest.TestCase):
    def test_seen_ids_do_not_block_later_usgs_upgrade(self):
        import usgs_listener

        feature = {
            "id": "us7000upgrade",
            "properties": {
                "mag": 6.7,
                "place": "near the Kuril Islands",
                "type": "earthquake",
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
            },
            "geometry": {"coordinates": [150.0, 45.0, 25.0]},
        }
        candidate = {
            "usgs_id": "us7000upgrade",
            "status": "queued",
            "magnitude": 6.7,
            "place": "near the Kuril Islands",
            "zones": ["Japan/Kuril"],
            "primary_anchor": "guam",
            "detection_window": {},
        }
        queue = {"seen_ids": ["us7000upgrade"], "events": []}

        with (
            mock.patch.object(usgs_listener, "fetch_feed", return_value=[feature]),
            mock.patch.object(usgs_listener, "assess_event", return_value=candidate),
            mock.patch.object(usgs_listener, "in_pacific_zone", return_value=["Japan/Kuril"]),
            mock.patch.object(usgs_listener, "_activate_fast_poll"),
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(queue["events"][0]["usgs_id"], "us7000upgrade")

    def _load_pipeline_with_stubs(self, queues, notify_discord=None):
        notify_discord = notify_discord or types.SimpleNamespace(
            send_detection_alert=lambda event: True,
            send_retroactive_completed=lambda event: True,
            send_retroactive_aborted=lambda event, detail: True,
            send_retroactive_triggered=lambda info: True,
            send_near_miss_alerts=lambda near_misses: True,
            send_pipeline_error=lambda component, err: True,
        )
        saved_queues = []
        queue_sequence = list(queues)

        def load_queue():
            if queue_sequence:
                return queue_sequence.pop(0)
            return queues[-1]

        def save_queue(queue):
            saved_queues.append(copy.deepcopy(queue))

        stubs = {
            "usgs_listener": types.SimpleNamespace(
                load_queue=load_queue,
                check_feed=lambda queue: (0, []),
                save_queue=save_queue,
                write_poll_log=lambda new, queue, near_misses: None,
            ),
            "rinex_downloader": types.SimpleNamespace(main=lambda: []),
            "detector_runner": types.SimpleNamespace(main=lambda: None),
            "scorer": types.SimpleNamespace(main=lambda: None),
            "notify": types.SimpleNamespace(send_event_alert=lambda events: None),
            "notify_discord": notify_discord,
            "dyfi_poller": types.SimpleNamespace(run=lambda: None),
        }
        with mock.patch.dict(sys.modules, stubs):
            module_name = f"_pipeline_under_test_{id(saved_queues)}"
            module = load_module_from_path(module_name, ROOT / "pipeline.py")
        return module, saved_queues

    def test_pipeline_ci_once_ignores_active_fast_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            with chdir(tmp):
                expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                Path("fast_poll.json").write_text(
                    json.dumps(
                        {
                            "active": True,
                            "expires_utc": expires,
                            "trigger_mag": 6.1,
                            "trigger_place": "Pacific",
                            "poll_interval_sec": 120,
                        },
                    ),
                    encoding="utf-8",
                )
                module, _saved = self._load_pipeline_with_stubs(
                    [{"seen_ids": [], "events": []}, {"events": []}],
                )
                calls = []
                module.run_pipeline = lambda: calls.append("cycle")

                with (
                    mock.patch.dict(os.environ, {"CI": "true"}, clear=False),
                    mock.patch.object(module.time, "sleep", side_effect=AssertionError),
                ):
                    module.main(once=True)

        self.assertEqual(calls, ["cycle"])

    def test_pipeline_does_not_ack_failed_detection_discord_send(self):
        event = {"usgs_id": "us7000alert", "status": "predicted"}
        notify_discord = types.SimpleNamespace(
            send_detection_alert=lambda event: False,
            send_retroactive_completed=lambda event: False,
            send_retroactive_aborted=lambda event, detail: False,
            send_retroactive_triggered=lambda info: False,
            send_near_miss_alerts=lambda near_misses: False,
            send_pipeline_error=lambda component, err: False,
        )
        module, _saved = self._load_pipeline_with_stubs(
            [{"seen_ids": [], "events": []}, {"events": [event]}],
            notify_discord,
        )

        module.run_pipeline()

        self.assertNotIn("discord_alerted", event)

    def test_pipeline_keeps_retro_pending_until_abort_alert_delivers(self):
        event = {
            "usgs_id": "us7000retro",
            "status": "rinex_failed",
            "retroactive_pending": True,
            "retro_trigger_reason": "CDDIS coverage improved",
        }
        notify_discord = types.SimpleNamespace(
            send_detection_alert=lambda event: False,
            send_retroactive_completed=lambda event: False,
            send_retroactive_aborted=lambda event, detail: False,
            send_retroactive_triggered=lambda info: False,
            send_near_miss_alerts=lambda near_misses: False,
            send_pipeline_error=lambda component, err: False,
        )
        module, _saved = self._load_pipeline_with_stubs(
            [{"seen_ids": [], "events": []}, {"events": [event]}],
            notify_discord,
        )

        module.run_pipeline()

        self.assertTrue(event["retroactive_pending"])

    def test_scheduled_workflow_lets_pipeline_own_polling(self):
        workflow = (ROOT / ".github" / "workflows" / "pipeline-push.yml").read_text(
            encoding="utf-8",
        )

        self.assertIn("cancel-in-progress: true", workflow)
        self.assertNotIn("python usgs_listener.py --once", workflow)
        self.assertNotIn("python dyfi_poller.py", workflow)
        self.assertIn("python pipeline.py --once", workflow)

    def test_outbreak_ingest_rejects_unsafe_news_urls(self):
        stubs = {
            "feedparser": types.SimpleNamespace(parse=lambda raw: types.SimpleNamespace(entries=[])),
            "httpx": types.SimpleNamespace(Client=object),
            "yaml": types.SimpleNamespace(safe_load=lambda raw: {}),
        }
        with mock.patch.dict(sys.modules, stubs):
            ingest = load_module_from_path(
                "_outbreak_ingest_under_test",
                ROOT / "outbreak-dashboard" / "ingest" / "run.py",
            )

        self.assertEqual(ingest.normalize_url("javascript:alert(1)"), "")
        self.assertEqual(ingest.normalize_url("data:text/html,<h1>x</h1>"), "")
        self.assertEqual(ingest.normalize_url("//evil.example/path"), "")
        self.assertEqual(
            ingest.normalize_url("https://example.com/a?utm_source=x&keep=1#frag"),
            "https://example.com/a?keep=1",
        )

        merged = ingest.merge_items(
            [
                {"url": "javascript:alert(1)", "title": "hantavirus fake"},
                {"url": "https://example.com/ok", "title": "hantavirus update"},
            ],
            [],
        )
        self.assertEqual([item["url"] for item in merged], ["https://example.com/ok"])


if __name__ == "__main__":
    unittest.main()
