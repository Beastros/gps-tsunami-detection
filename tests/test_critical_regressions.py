import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CriticalRegressionTests(unittest.TestCase):
    def test_seen_id_does_not_block_later_qualifying_upgrade(self):
        import usgs_listener

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        def feature(mag):
            return {
                "id": "us-upgrade",
                "properties": {
                    "mag": mag,
                    "place": "Japan region",
                    "type": "earthquake",
                    "time": now_ms,
                },
                "geometry": {"coordinates": [142.0, 38.0, 30.0]},
            }

        def assess(feat):
            mag = feat["properties"]["mag"]
            if mag < usgs_listener.MW_THRESHOLD:
                return None
            return {
                "usgs_id": feat["id"],
                "magnitude": mag,
                "place": feat["properties"]["place"],
                "status": "queued",
            }

        queue = {"events": [], "seen_ids": []}
        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[feature(6.4)]), \
             mock.patch.object(usgs_listener, "assess_event", side_effect=assess), \
             mock.patch.object(usgs_listener, "_activate_fast_poll"):
            new, _near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new, 0)
        self.assertEqual(queue["seen_ids"], ["us-upgrade"])
        self.assertEqual(queue["events"], [])

        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[feature(6.7)]), \
             mock.patch.object(usgs_listener, "assess_event", side_effect=assess), \
             mock.patch.object(usgs_listener, "_activate_fast_poll"):
            new, _near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new, 1)
        self.assertEqual([event["usgs_id"] for event in queue["events"]], ["us-upgrade"])
        self.assertEqual(queue["seen_ids"], ["us-upgrade"])

    def test_webhook_helpers_report_delivery_failure(self):
        import notify_discord

        with mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}, clear=False):
            self.assertFalse(notify_discord.send_detection_alert({"usgs_id": "x"}))

    def test_retroactive_queueing_preserves_existing_prediction(self):
        import retroactive_rinex

        event = {
            "usgs_id": "us-retro",
            "status": "predicted",
            "prediction": {"detected": True},
            "score": {"ok": True},
            "scored": True,
        }

        retroactive_rinex.queue_retroactive_reprocess(
            event,
            "new stations available",
            {"stations": ["guam"], "fingerprint": {"n_stations": 1}},
        )

        self.assertTrue(event["retroactive_pending"])
        self.assertEqual(event["status"], "predicted")
        self.assertEqual(event["prediction"], {"detected": True})
        self.assertEqual(event["score"], {"ok": True})
        self.assertTrue(event["scored"])

    def test_detector_uses_manifest_aliases_and_adjacent_days(self):
        try:
            import detector_runner
        except ImportError as exc:
            self.skipTest(f"detector dependencies unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            rinex_dir = Path(tmp)
            manifest = {
                "days": [
                    {
                        "year": 2026,
                        "doy": 2,
                        "resolved": {"guam": "gvim"},
                        "files": 2,
                    },
                ],
            }
            (rinex_dir / "rinex_manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            alias_obs = rinex_dir / "gvim0020.26o.Z"
            alias_obs.write_bytes(b"rinex")

            loaded = detector_runner._load_rinex_manifest(rinex_dir)
            days = detector_runner._event_rinex_days(
                datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc),
            )
            self.assertIn((2026, 2, "26"), days)
            codes = detector_runner._station_codes_for_day(loaded, "guam", 2026, 2)
            self.assertEqual(codes, ["guam", "gvim"])
            self.assertEqual(
                detector_runner._rinex_obs_path(rinex_dir, codes, 2, "26"),
                alias_obs,
            )

    def test_outbreak_ingest_rejects_unsafe_urls(self):
        try:
            ingest = _load_module(
                ROOT / "outbreak-dashboard" / "ingest" / "run.py",
                "outbreak_ingest_run",
            )
        except ImportError as exc:
            self.skipTest(f"outbreak ingest dependencies unavailable: {exc}")

        self.assertFalse(ingest.is_safe_http_url("javascript:alert(1)"))
        self.assertFalse(ingest.is_safe_http_url("data:text/html,hi"))
        self.assertTrue(ingest.is_safe_http_url("https://example.org/report"))

        merged = ingest.merge_items(
            [{"id": "bad", "url": "javascript:alert(1)", "title": "bad"}],
            [{"id": "good", "url": "https://example.org/a?utm_source=x", "title": "good"}],
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["url"], "https://example.org/a")


if __name__ == "__main__":
    unittest.main()
