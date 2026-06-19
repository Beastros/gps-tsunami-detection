import unittest
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import notify_discord
import usgs_listener


ROOT = Path(__file__).resolve().parents[1]


def _feature(event_id, magnitude, *, lat=52.69, lon=160.86, depth=10.0):
    return {
        "id": event_id,
        "properties": {
            "mag": magnitude,
            "place": "Test Pacific earthquake",
            "type": "earthquake",
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        "geometry": {"coordinates": [lon, lat, depth]},
    }


class UsgsListenerDedupTests(unittest.TestCase):
    @mock.patch.object(usgs_listener, "_activate_fast_poll")
    @mock.patch.object(usgs_listener, "assess_event")
    @mock.patch.object(usgs_listener, "fetch_feed")
    def test_seen_near_miss_can_later_queue_after_upgrade(
        self, fetch_feed, assess_event, _activate_fast_poll
    ):
        candidate = {
            "usgs_id": "upgraded-event",
            "magnitude": 6.7,
            "place": "Test Pacific earthquake",
            "zones": ["Japan/Kuril"],
            "primary_anchor": "guam",
            "detection_window": {},
            "status": "queued",
        }
        fetch_feed.return_value = [_feature("upgraded-event", 6.7)]
        assess_event.return_value = candidate
        queue = {"events": [], "seen_ids": ["upgraded-event"]}

        new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(queue["events"], [candidate])
        self.assertEqual(queue["seen_ids"], ["upgraded-event"])

    @mock.patch.object(usgs_listener, "_activate_fast_poll")
    @mock.patch.object(usgs_listener, "fetch_feed")
    def test_seen_near_miss_is_not_reported_again(self, fetch_feed, _activate_fast_poll):
        fetch_feed.return_value = [_feature("repeat-near-miss", 6.0)]
        queue = {"events": [], "seen_ids": ["repeat-near-miss"]}

        new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual(near_misses, [])
        self.assertEqual(queue["seen_ids"], ["repeat-near-miss"])


class ScheduledEntrypointTests(unittest.TestCase):
    def test_github_actions_uses_pipeline_as_only_usgs_poller(self):
        workflow = (ROOT / ".github/workflows/pipeline-push.yml").read_text(encoding="utf-8")

        self.assertNotIn("usgs_listener.py --once", workflow)
        self.assertEqual(workflow.count("python pipeline.py --once"), 1)

    def test_windows_runner_preserves_state_and_avoids_usgs_pre_poll(self):
        runner = (ROOT / "run_and_push.bat").read_text(encoding="utf-8")

        self.assertNotIn("usgs_listener.py --once", runner)
        self.assertIn("git pull --rebase origin main", runner)
        self.assertNotIn("git reset --hard origin/main", runner)

    def test_ci_once_exits_instead_of_fast_poll_sleep_loop(self):
        pipeline = (ROOT / "pipeline.py").read_text(encoding="utf-8")

        self.assertIn('os.environ.get("CI", "").lower() == "true"', pipeline)
        self.assertIn("CI --once exits after this cycle", pipeline)

    def test_discord_alerts_are_acknowledged_only_after_delivery(self):
        pipeline = (ROOT / "pipeline.py").read_text(encoding="utf-8")

        self.assertIn("if delivered:", pipeline)
        self.assertIn("will retry next cycle", pipeline)


class DiscordWebhookTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}, clear=False)
    def test_missing_discord_webhook_reports_not_delivered(self):
        self.assertFalse(notify_discord._post_webhook({"content": "test"}))

    @mock.patch.dict(
        os.environ,
        {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/token"},
        clear=False,
    )
    @mock.patch("notify_discord.urllib.request.urlopen")
    def test_successful_discord_webhook_reports_delivered(self, urlopen):
        response = mock.Mock()
        response.status = 204
        urlopen.return_value.__enter__.return_value = response

        self.assertTrue(notify_discord._post_webhook({"content": "test"}))


if __name__ == "__main__":
    unittest.main()
