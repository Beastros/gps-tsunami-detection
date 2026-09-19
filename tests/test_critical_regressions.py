import importlib
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def pacific_feature(usgs_id: str, mag: float) -> dict:
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "Vanuatu test region",
            "type": "earthquake",
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        "geometry": {"coordinates": [170.0, -10.0, 20.0]},
    }


class CriticalRegressionTests(unittest.TestCase):
    def test_seen_ids_do_not_block_later_qualifying_upgrade(self):
        import usgs_listener

        queue = {"events": [], "seen_ids": ["upgrade-event"]}
        with (
            patch.object(
                usgs_listener,
                "fetch_feed",
                return_value=[pacific_feature("upgrade-event", 6.8)],
            ),
            patch.object(usgs_listener, "fetch_focal_mechanism", return_value=None),
            patch.object(usgs_listener, "_activate_fast_poll"),
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "upgrade-event")
        self.assertEqual(queue["seen_ids"].count("upgrade-event"), 1)

    def test_queued_usgs_id_still_dedupes(self):
        import usgs_listener

        queue = {
            "events": [{"usgs_id": "already-queued", "status": "queued"}],
            "seen_ids": [],
        }
        with patch.object(
            usgs_listener,
            "fetch_feed",
            return_value=[pacific_feature("already-queued", 7.0)],
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)

    def _import_pipeline_with_stubs(self, discord_delivered: bool):
        module_names = [
            "pipeline",
            "usgs_listener",
            "rinex_downloader",
            "detector_runner",
            "scorer",
            "notify",
            "notify_discord",
            "dyfi_poller",
        ]
        original_modules = {name: sys.modules.get(name) for name in module_names}

        def restore_modules():
            for name, module in original_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.addCleanup(restore_modules)
        for name in module_names:
            sys.modules.pop(name, None)

        saved_queues = []
        event = {"usgs_id": "evt1", "status": "predicted"}

        usgs_listener = types.ModuleType("usgs_listener")
        usgs_listener.load_queue = lambda: {"events": [dict(event)], "seen_ids": []}
        usgs_listener.check_feed = lambda queue: (0, [])
        usgs_listener.save_queue = lambda queue: saved_queues.append(queue)
        usgs_listener.write_poll_log = lambda *args, **kwargs: None

        rinex_downloader = types.ModuleType("rinex_downloader")
        rinex_downloader.main = lambda: []

        detector_runner = types.ModuleType("detector_runner")
        detector_runner.main = lambda: None

        scorer = types.ModuleType("scorer")
        scorer.main = lambda: None

        notify = types.ModuleType("notify")
        notify.send_event_alert = lambda events: None

        notify_discord = types.ModuleType("notify_discord")
        notify_discord.send_near_miss_alerts = lambda near_misses: discord_delivered
        notify_discord.send_detection_alert = lambda evt: discord_delivered
        notify_discord.send_retroactive_completed = lambda evt: discord_delivered
        notify_discord.send_retroactive_aborted = lambda evt, detail: discord_delivered
        notify_discord.send_retroactive_triggered = lambda info: discord_delivered

        dyfi_poller = types.ModuleType("dyfi_poller")
        dyfi_poller.run = lambda: None

        sys.modules.update(
            {
                "usgs_listener": usgs_listener,
                "rinex_downloader": rinex_downloader,
                "detector_runner": detector_runner,
                "scorer": scorer,
                "notify": notify,
                "notify_discord": notify_discord,
                "dyfi_poller": dyfi_poller,
            },
        )

        return importlib.import_module("pipeline"), saved_queues

    def test_pipeline_does_not_ack_failed_discord_delivery(self):
        pipeline, saved_queues = self._import_pipeline_with_stubs(False)

        pipeline.run_pipeline()

        self.assertNotIn("discord_alerted", saved_queues[-1]["events"][0])

    def test_pipeline_acks_successful_discord_delivery(self):
        pipeline, saved_queues = self._import_pipeline_with_stubs(True)

        pipeline.run_pipeline()

        self.assertTrue(saved_queues[-1]["events"][0]["discord_alerted"])

    def test_ci_once_exits_instead_of_sleeping_during_fast_poll(self):
        pipeline, _ = self._import_pipeline_with_stubs(True)
        previous_cwd = os.getcwd()

        with tempfile.TemporaryDirectory() as td:
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
                            "trigger_mag": 7.1,
                            "trigger_place": "Vanuatu test region",
                        },
                    ),
                    encoding="utf-8",
                )
                with (
                    patch.dict(os.environ, {"CI": "true"}),
                    patch.object(pipeline, "run_pipeline") as run_pipeline,
                    patch.object(pipeline.time, "sleep") as sleep,
                ):
                    pipeline.main(once=True)
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(run_pipeline.call_count, 1)
        sleep.assert_not_called()

    def test_scheduled_runners_let_pipeline_own_usgs_polling(self):
        workflow = (ROOT / ".github" / "workflows" / "pipeline-push.yml").read_text(
            encoding="utf-8",
        )
        windows_runner = (ROOT / "run_and_push.bat").read_text(encoding="utf-8")

        self.assertNotIn("python usgs_listener.py --once", workflow)
        self.assertIn("cancel-in-progress: true", workflow)
        self.assertNotIn("usgs_listener.py --once", windows_runner)
        self.assertNotIn("git reset --hard origin/main", windows_runner)

    def test_outbreak_ingest_rejects_non_http_urls(self):
        stub_names = ["feedparser", "httpx", "yaml"]
        original_modules = {name: sys.modules.get(name) for name in stub_names}

        def restore_modules():
            for name, module in original_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.addCleanup(restore_modules)
        for name in stub_names:
            sys.modules.setdefault(name, types.ModuleType(name))

        spec = importlib.util.spec_from_file_location(
            "outbreak_ingest_run",
            ROOT / "outbreak-dashboard" / "ingest" / "run.py",
        )
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        self.assertIsNone(module.normalize_url("javascript:alert(1)"))
        self.assertIsNone(module.normalize_url("data:text/html,<script></script>"))
        self.assertEqual(
            module.normalize_url("https://example.com/a?utm_source=x&keep=1#frag"),
            "https://example.com/a?keep=1",
        )
        merged = module.merge_items(
            [{"url": "javascript:alert(1)", "title": "bad"}],
            [{"url": "https://example.com/good", "title": "ok"}],
        )
        self.assertEqual([item["url"] for item in merged], ["https://example.com/good"])


if __name__ == "__main__":
    unittest.main()
