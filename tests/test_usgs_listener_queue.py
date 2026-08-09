import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import usgs_listener


def _feature(usgs_id, mag, lat=38.913, lon=142.25, depth=43.6):
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "near the east coast of Honshu, Japan",
            "type": "earthquake",
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        "geometry": {"coordinates": [lon, lat, depth]},
    }


class UsgsListenerQueueTests(unittest.TestCase):
    def test_seen_but_unqueued_upgrade_can_be_queued(self):
        queue = {"events": [], "seen_ids": ["upgrade-id"]}

        with (
            patch.object(usgs_listener, "fetch_feed", return_value=[_feature("upgrade-id", 6.7)]),
            patch.object(
                usgs_listener,
                "fetch_focal_mechanism",
                return_value={"available": False, "fault_type": "unknown", "rake_score": 0.5},
            ),
            patch.object(usgs_listener, "_activate_fast_poll"),
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual([event["usgs_id"] for event in queue["events"]], ["upgrade-id"])
        self.assertEqual(queue["seen_ids"].count("upgrade-id"), 1)

    def test_already_queued_event_is_not_duplicated(self):
        queue = {"events": [{"usgs_id": "queued-id"}], "seen_ids": []}

        with (
            patch.object(usgs_listener, "fetch_feed", return_value=[_feature("queued-id", 7.1)]),
            patch.object(usgs_listener, "assess_event") as assess_event,
            patch.object(usgs_listener, "_activate_fast_poll") as activate_fast_poll,
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)
        assess_event.assert_not_called()
        activate_fast_poll.assert_not_called()

    def test_seen_below_threshold_event_does_not_repeat_near_miss(self):
        queue = {"events": [], "seen_ids": ["seen-low"]}

        with (
            patch.object(usgs_listener, "fetch_feed", return_value=[_feature("seen-low", 6.0)]),
            patch.object(usgs_listener, "assess_event") as assess_event,
            patch.object(usgs_listener, "_activate_fast_poll"),
        ):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual(near_misses, [])
        self.assertEqual(queue["events"], [])
        assess_event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
