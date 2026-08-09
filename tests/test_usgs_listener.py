import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import usgs_listener


def make_feature(mag):
    return {
        "id": "upgrade-test",
        "properties": {
            "mag": mag,
            "place": "test event near Japan",
            "type": "earthquake",
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        "geometry": {
            "coordinates": [142.25, 38.9, 20.0],
        },
    }


class CheckFeedUpgradeTests(unittest.TestCase):
    def test_seen_near_miss_is_requeued_after_magnitude_upgrade(self):
        queue = {"events": [], "seen_ids": []}

        with patch.object(usgs_listener, "fetch_feed", return_value=[make_feature(6.4)]), \
             patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False}), \
             patch.object(usgs_listener, "_activate_fast_poll"):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual([m["reason"] for m in near_misses], ["below threshold"])
        self.assertEqual(queue["seen_ids"], ["upgrade-test"])

        with patch.object(usgs_listener, "fetch_feed", return_value=[make_feature(6.7)]), \
             patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False}), \
             patch.object(usgs_listener, "_activate_fast_poll"):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)
        self.assertEqual(queue["events"][0]["usgs_id"], "upgrade-test")
        self.assertEqual(queue["events"][0]["magnitude"], 6.7)
        self.assertEqual(queue["seen_ids"], ["upgrade-test"])

        with patch.object(usgs_listener, "fetch_feed", return_value=[make_feature(6.7)]), \
             patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False}), \
             patch.object(usgs_listener, "_activate_fast_poll"):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)


if __name__ == "__main__":
    unittest.main()
