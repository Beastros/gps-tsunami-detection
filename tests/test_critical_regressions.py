import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import notify_discord
import pipeline
import retroactive_rinex
import rinex_downloader


@contextmanager
def temp_cwd():
    old = Path.cwd()
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        try:
            yield Path(td)
        finally:
            os.chdir(old)


@contextmanager
def patched_attr(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


@contextmanager
def patched_env(**values):
    old = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class CriticalRegressionTests(unittest.TestCase):
    def test_ci_once_exits_even_when_fast_poll_active(self):
        state = {
            "active": True,
            "expires_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "poll_interval_sec": 3600,
            "trigger_mag": 6.2,
            "trigger_place": "Pacific test",
        }

        calls = {"run": 0}

        def fake_run_pipeline():
            calls["run"] += 1

        def forbidden_sleep(_seconds):
            raise AssertionError("CI --once should not sleep/re-run for fast poll")

        with temp_cwd():
            Path("fast_poll.json").write_text(json.dumps(state), encoding="utf-8")
            with patched_env(CI="true"), patched_attr(pipeline, "run_pipeline", fake_run_pipeline), patched_attr(
                pipeline.time, "sleep", forbidden_sleep
            ):
                pipeline.main(once=True)

        self.assertEqual(calls["run"], 1)

    def test_discord_alerts_are_acknowledged_only_after_delivery(self):
        queue = {
            "events": [
                {
                    "usgs_id": "us-test",
                    "status": "predicted",
                    "prediction": {"detected": True},
                }
            ]
        }

        with patched_attr(notify_discord, "send_detection_alert", lambda _evt: False):
            pipeline._send_pending_discord_alerts(queue)
        self.assertNotIn("discord_alerted", queue["events"][0])

        with patched_attr(notify_discord, "send_detection_alert", lambda _evt: True):
            pipeline._send_pending_discord_alerts(queue)
        self.assertTrue(queue["events"][0]["discord_alerted"])

    def test_discord_webhook_reports_delivery_success(self):
        self.assertFalse(notify_discord._post_webhook({"content": "test"}))

        class Response:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(_req, timeout):
            self.assertEqual(timeout, 20)
            return Response()

        with patched_env(DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/abc/def"), patched_attr(
            notify_discord.urllib.request, "urlopen", fake_urlopen
        ):
            self.assertTrue(notify_discord._post_webhook({"content": "test"}))

    def test_retroactive_download_failure_preserves_existing_score(self):
        event = {
            "usgs_id": "us-retro",
            "status": "scored",
            "place": "Pacific test",
            "magnitude": 7.1,
            "quake_utc": "2026-05-28T00:00:00+00:00",
            "prediction": {"detected": True},
            "score": {"usgs_id": "us-retro", "outcome": "TRUE_POSITIVE"},
            "scored": True,
            "detector_run": True,
            "rinex_downloaded": True,
            "rinex_dir": "rinex_live/us-retro",
        }
        retroactive_rinex.queue_retroactive_reprocess(
            event,
            "new stations on CDDIS: TEST",
            {"stations": ["test"], "n_stations": 1},
        )
        self.assertEqual(event["status"], "scored")
        self.assertEqual(event["prediction"], {"detected": True})
        self.assertEqual(event["score"]["outcome"], "TRUE_POSITIVE")

        running_log = {
            "scored_events": [{"usgs_id": "us-retro", "outcome": "TRUE_POSITIVE"}],
            "summary": {"total_scored": 1},
        }

        with temp_cwd():
            Path("event_queue.json").write_text(
                json.dumps({"events": [event]}, indent=2), encoding="utf-8"
            )
            Path("running_log.json").write_text(json.dumps(running_log), encoding="utf-8")

            with patched_attr(rinex_downloader, "get_credentials", lambda: ("user", "pass")), patched_attr(
                rinex_downloader, "refresh_rolling_cache", lambda _auth: None
            ), patched_attr(
                rinex_downloader, "download_event", lambda _event, _auth: (0, "rinex_live/us-retro")
            ):
                rinex_downloader.main(skip_retro_check=True)

            saved = json.loads(Path("event_queue.json").read_text(encoding="utf-8"))
            saved_event = saved["events"][0]
            self.assertEqual(saved_event["status"], "scored")
            self.assertEqual(saved_event["prediction"], {"detected": True})
            self.assertEqual(saved_event["score"]["outcome"], "TRUE_POSITIVE")
            self.assertTrue(saved_event["retroactive_pending"])
            self.assertIn("retroactive_abort_reason", saved_event)

            saved_log = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_log["scored_events"], running_log["scored_events"])


if __name__ == "__main__":
    unittest.main()
