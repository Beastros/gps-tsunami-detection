"""Regression: Mariana Trench / Izu-Bonin must match PACIFIC_ZONES."""

import unittest

import usgs_listener


class MarianaZoneTests(unittest.TestCase):
    def test_guam_2002_mw71_matches(self):
        # USGS usp000b37m Mw7.1 2002-04-26, 20 km SSW of Merizo Village, Guam.
        # Detector already has unconstrained GUAM on this trench; zone was missing.
        zones = usgs_listener.in_pacific_zone(13.09, 144.62)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Mariana/Izu-Bonin")

    def test_guam_2001_mw70_matches(self):
        zones = usgs_listener.in_pacific_zone(12.69, 144.98)
        self.assertTrue(any(z["name"] == "Mariana/Izu-Bonin" for z in zones))

    def test_maug_islands_2023_matches(self):
        # USGS us6000lqf9 Mw6.9 2023-11-24, Maug Islands region.
        zones = usgs_listener.in_pacific_zone(20.13, 145.52)
        self.assertTrue(any(z["name"] == "Mariana/Izu-Bonin" for z in zones))

    def test_south_of_marianas_matches(self):
        zones = usgs_listener.in_pacific_zone(10.45, 145.72)
        self.assertTrue(any(z["name"] == "Mariana/Izu-Bonin" for z in zones))

    def test_izu_bonin_2010_mw74_matches(self):
        # USGS usp000hr97 Mw7.4 2010-12-21 Bonin Islands — south of Japan/Kuril
        # (lat>=30) and previously unmatched.
        zones = usgs_listener.in_pacific_zone(26.90, 143.70)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Mariana/Izu-Bonin")

    def test_assess_event_queues_shallow_mw7_guam(self):
        feature = {
            "id": "test_guam_trench",
            "properties": {
                "mag": 7.0,
                "place": "Guam region",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [144.8, 13.4, 25]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Mariana/Izu-Bonin", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_assess_event_queues_shallow_mw7_bonin(self):
        feature = {
            "id": "test_bonin_trench",
            "properties": {
                "mag": 7.1,
                "place": "Bonin Islands, Japan region",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [143.7, 26.9, 20]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Mariana/Izu-Bonin", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_japan_kuril_still_separate(self):
        # Tohoku corridor must stay on Japan/Kuril, not this box (lat>=30).
        zones = usgs_listener.in_pacific_zone(38.3, 142.4)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Japan/Kuril")

    def test_philippine_trench_not_this_zone(self):
        # West of box toward Mindanao — Philippines coverage is a separate zone.
        zones = usgs_listener.in_pacific_zone(5.18, 125.28)
        self.assertFalse(any(z["name"] == "Mariana/Izu-Bonin" for z in zones))

    def test_west_of_box_not_matched(self):
        # 139E is west of Mariana trench axis; must not false-positive.
        self.assertEqual(usgs_listener.in_pacific_zone(15.0, 139.0), [])


if __name__ == "__main__":
    unittest.main()
