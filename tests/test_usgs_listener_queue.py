import unittest
from datetime import datetime, timezone
from unittest import mock

import usgs_listener


def _feature(usgs_id="upgrade-1", mag=6.7, depth=25.0):
    return {
        "id": usgs_id,
        "properties": {
            "mag": mag,
            "place": "test event near Japan",
            "type": "earthquake",
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
        "geometry": {
            "coordinates": [142.0, 38.0, depth],
        },
    }


class UsgsListenerQueueTests(unittest.TestCase):
    def test_seen_but_unqueued_event_can_later_qualify(self):
        queue = {"events": [], "seen_ids": ["upgrade-1"]}

        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[_feature()]), \
             mock.patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False}), \
             mock.patch.object(usgs_listener, "_activate_fast_poll"):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 1)
        self.assertEqual(near_misses, [])
        self.assertEqual([event["usgs_id"] for event in queue["events"]], ["upgrade-1"])
        self.assertEqual(queue["seen_ids"].count("upgrade-1"), 1)

    def test_already_queued_event_is_not_duplicated(self):
        queue = {
            "events": [{"usgs_id": "upgrade-1", "status": "queued"}],
            "seen_ids": [],
        }

        with mock.patch.object(usgs_listener, "fetch_feed", return_value=[_feature()]), \
             mock.patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False}), \
             mock.patch.object(usgs_listener, "_activate_fast_poll"):
            new_count, near_misses = usgs_listener.check_feed(queue)

        self.assertEqual(new_count, 0)
        self.assertEqual(near_misses, [])
        self.assertEqual(len(queue["events"]), 1)
        self.assertEqual(queue["seen_ids"], [])


if __name__ == "__main__":
    unittest.main()
