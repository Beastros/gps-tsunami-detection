"""Regression: Philippine/Manila Trench must match PACIFIC_ZONES."""

import unittest

import usgs_listener


class PhilippinesZoneTests(unittest.TestCase):
    def test_live_sarangani_matches(self):
        # Live USGS us6000ti6x (Mw6.3 Sarangani, Philippines) matched no zone
        # before the fix. Geography must queue if magnitude/depth qualify.
        zones = usgs_listener.in_pacific_zone(5.1812, 125.276)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Philippines/Taiwan")

    def test_live_sarangani_aftershock_matches(self):
        zones = usgs_listener.in_pacific_zone(5.3206, 125.181)
        self.assertTrue(any(z["name"] == "Philippines/Taiwan" for z in zones))

    def test_baganga_philippine_trench_matches(self):
        # poll_log near-miss: 25 km ENE of Baganga, Philippines
        zones = usgs_listener.in_pacific_zone(7.63, 126.78)
        self.assertTrue(any(z["name"] == "Philippines/Taiwan" for z in zones))

    def test_moro_gulf_historical_matches(self):
        # 1976 Moro Gulf Mw8.1 tsunami source — previously unmatched.
        zones = usgs_listener.in_pacific_zone(6.3, 124.0)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Philippines/Taiwan")

    def test_manila_trench_matches(self):
        zones = usgs_listener.in_pacific_zone(14.0, 119.5)
        self.assertTrue(any(z["name"] == "Philippines/Taiwan" for z in zones))

    def test_taiwan_east_coast_matches(self):
        # CNMR relay corridor; previously south of Japan/Kuril (lat>=30).
        zones = usgs_listener.in_pacific_zone(23.0, 121.5)
        self.assertTrue(any(z["name"] == "Philippines/Taiwan" for z in zones))

    def test_assess_event_queues_shallow_mw7_philippine_trench(self):
        feature = {
            "id": "test_philippine_trench",
            "properties": {
                "mag": 7.0,
                "place": "Philippine Islands region",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [126.5, 10.0, 25]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Philippines/Taiwan", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_assess_event_queues_shallow_mw7_manila_trench(self):
        feature = {
            "id": "test_manila_trench",
            "properties": {
                "mag": 6.8,
                "place": "west of Luzon, Philippines",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [119.5, 14.0, 30]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Philippines/Taiwan", candidate["zones"])

    def test_outside_lon_not_matched(self):
        # East of box toward Marianas — not this zone (Mariana coverage separate).
        self.assertEqual(usgs_listener.in_pacific_zone(15.0, 140.0), [])

    def test_sumatra_still_separate(self):
        zones = usgs_listener.in_pacific_zone(5.0, 100.0)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Sumatra/Andaman")


if __name__ == "__main__":
    unittest.main()
