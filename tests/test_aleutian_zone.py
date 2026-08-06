"""Regression: Alaska/Aleutian zone must span the antimeridian."""

import unittest

import usgs_listener


class AleutianZoneTests(unittest.TestCase):
    def test_west_of_dateline_rat_islands_is_in_zone(self):
        # Historical Mw7.8 Rat Islands (usp000cd1n): lon≈+178.65 is east of
        # the dateline in the western Aleutians. The old box (-180, -145)
        # only covered negative longitudes and silently dropped this corridor.
        zones = usgs_listener.in_pacific_zone(51.146, 178.650)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Alaska/Aleutian")

    def test_recent_attu_corridor_matches(self):
        # 2026 near-miss us7000s211 (Mw6.4, 223 km ESE of Attu Station).
        zones = usgs_listener.in_pacific_zone(52.326, 176.371)
        self.assertTrue(any(z["name"] == "Alaska/Aleutian" for z in zones))

    def test_east_of_dateline_aleutian_still_matches(self):
        zones = usgs_listener.in_pacific_zone(51.5, -179.0)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Alaska/Aleutian")

    def test_andreanof_still_matches(self):
        zones = usgs_listener.in_pacific_zone(51.5, -175.0)
        self.assertTrue(any(z["name"] == "Alaska/Aleutian" for z in zones))

    def test_assess_event_queues_shallow_mw7_rat_islands(self):
        feature = {
            "id": "test_rat_islands",
            "properties": {
                "mag": 7.0,
                "place": "Rat Islands, Aleutian Islands, Alaska",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [178.735, 51.849, 33]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Alaska/Aleutian", candidate["zones"])

    def test_outside_lat_band_not_matched(self):
        self.assertEqual(usgs_listener.in_pacific_zone(47.0, 178.0), [])


if __name__ == "__main__":
    unittest.main()
