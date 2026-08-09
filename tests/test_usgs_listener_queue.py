import time
import unittest
from unittest.mock import patch

import usgs_listener


def make_feature(usgs_id: str, mag: float) -> dict:
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "near the east coast of Honshu, Japan",
            "type": "earthquake",
            "time": int(time.time() * 1000),
        },
        "geometry": {
            "coordinates": [142.2, 38.9, 20.0],
        },
    }


class UsgsListenerQueueTests(unittest.TestCase):
    def test_seen_but_unqueued_event_can_be_queued_after_usgs_upgrade(self):
        queue = {"events": [], "seen_ids": ["upgrade-1"]}

        with (
            patch.object(
                usgs_listener,
                "fetch_feed",
                return_value=[make_feature("upgrade-1", 6.6)],
            ),
            patch.object(usgs_listener, "fetch_focal_mechanism", return_value=None),
            patch.object(usgs_listener, "_activate_fast_poll"),
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "upgrade-1")
        self.assertEqual(queue["seen_ids"].count("upgrade-1"), 1)

    def test_already_queued_event_is_not_queued_twice(self):
        queue = {
            "events": [{"usgs_id": "queued-1", "status": "queued"}],
            "seen_ids": ["queued-1"],
        }

        with (
            patch.object(
                usgs_listener,
                "fetch_feed",
                return_value=[make_feature("queued-1", 6.7)],
            ),
            patch.object(usgs_listener, "assess_event") as assess_event,
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        assess_event.assert_not_called()
        self.assertEqual(new_count, 0)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)
        self.assertEqual(queue["seen_ids"].count("queued-1"), 1)


if __name__ == "__main__":
    unittest.main()
