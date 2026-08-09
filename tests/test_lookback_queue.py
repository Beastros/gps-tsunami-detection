"""Regression: LOOKBACK must not permanently burn week-feed candidates."""

from __future__ import annotations

import importlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import usgs_listener  # noqa: E402


def _reload():
    return importlib.reload(usgs_listener)


def _feature(usgs_id: str, mag: float, lon: float, lat: float, depth: float, age_h: float):
    origin = datetime.now(timezone.utc) - timedelta(hours=age_h)
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "36h-old Pacific test event",
            "type": "earthquake",
            "time": int(origin.timestamp() * 1000),
        },
        "geometry": {"coordinates": [lon, lat, depth]},
    }


class LookbackQueueTests(unittest.TestCase):
    def test_lookback_covers_full_week_feed(self):
        mod = _reload()
        self.assertGreaterEqual(mod.LOOKBACK_HOURS, 24 * 7)

    def test_late_first_seen_candidate_still_queues(self):
        """
        Trigger: first successful poll is 36h after a Mw6.7 Japan/Kuril event.
        With LOOKBACK_HOURS=24 the ID was appended to seen_ids then skipped,
        so the candidate was permanently lost despite still being in the week feed.
        """
        mod = _reload()
        feat = _feature(
            "us_test_lookback_36h",
            mag=6.7,
            lon=142.25,
            lat=38.91,
            depth=20.0,
            age_h=36.0,
        )
        queue = {"events": [], "seen_ids": []}

        with patch.object(mod, "fetch_feed", return_value=[feat]), patch.object(
            mod,
            "fetch_focal_mechanism",
            return_value={"available": False},
        ):
            new_count, _near = mod.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(len(queue["events"]), 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "us_test_lookback_36h")
        self.assertIn("Japan/Kuril", queue["events"][0]["zones"])
        self.assertIn("us_test_lookback_36h", queue["seen_ids"])

    def test_old_24h_lookback_would_have_burned_event(self):
        """Document the failure mode of the previous 24h constant."""
        mod = _reload()
        feat = _feature(
            "us_test_lookback_burn",
            mag=6.7,
            lon=142.25,
            lat=38.91,
            depth=20.0,
            age_h=36.0,
        )
        queue = {"events": [], "seen_ids": []}

        with patch.object(mod, "LOOKBACK_HOURS", 24), patch.object(
            mod, "fetch_feed", return_value=[feat]
        ), patch.object(
            mod,
            "fetch_focal_mechanism",
            return_value={"available": False},
        ):
            new_count, _near = mod.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual(queue["events"], [])
        # ID was still recorded — permanent suppression on later polls via seen_ids
        self.assertIn("us_test_lookback_burn", queue["seen_ids"])


if __name__ == "__main__":
    unittest.main()
