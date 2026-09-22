"""Regression: New Britain / New Ireland trench must match PACIFIC_ZONES."""

import unittest

import usgs_listener


class NewBritainNewIrelandZoneTests(unittest.TestCase):
    def test_new_ireland_2000_mw80_matches(self):
        # USGS usp000a3qq Mw8.0 2000-11-16 New Ireland Earthquake.
        # North of Vanuatu/Solomon lat max -5 and west of lon min 155.
        zones = usgs_listener.in_pacific_zone(-3.98, 152.17)
        self.assertTrue(zones)
        self.assertTrue(any(z["name"] == "New Britain/New Ireland" for z in zones))

    def test_kokopo_2016_mw79_tsunami_flag_matches(self):
        # USGS us200081v8 Mw7.9 2016-12-17, 140 km E of Kokopo, tsunami=1.
        zones = usgs_listener.in_pacific_zone(-4.50, 153.52)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "New Britain/New Ireland")

    def test_new_britain_2000_aftershock_mw78_matches(self):
        # USGS usp000a45f Mw7.8 2000-11-17, 138 km SSW of Kokopo.
        # lat -5.50 is inside Vanuatu lat range but lon 151.78 is west of 155.
        zones = usgs_listener.in_pacific_zone(-5.50, 151.78)
        self.assertTrue(any(z["name"] == "New Britain/New Ireland" for z in zones))

    def test_kokopo_2019_mw76_tsunami_flag_matches(self):
        # USGS us70003kyy Mw7.6 2019-05-14, 48 km NE of Kokopo, tsunami=1, depth 10km.
        zones = usgs_listener.in_pacific_zone(-4.05, 152.60)
        self.assertTrue(any(z["name"] == "New Britain/New Ireland" for z in zones))

    def test_new_britain_2015_mw75_tsunami_flag_matches(self):
        # USGS us20002bnf Mw7.5 2015-05-05, 131 km SSW of Kokopo, tsunami=1.
        zones = usgs_listener.in_pacific_zone(-5.46, 151.88)
        self.assertTrue(any(z["name"] == "New Britain/New Ireland" for z in zones))

    def test_new_britain_2010_mw73_matches(self):
        # USGS usp000hfku Mw7.3 2010-07-18 New Britain region.
        zones = usgs_listener.in_pacific_zone(-5.93, 150.59)
        self.assertTrue(any(z["name"] == "New Britain/New Ireland" for z in zones))

    def test_assess_event_queues_shallow_mw80_new_ireland(self):
        feature = {
            "id": "test_new_ireland_2000",
            "properties": {
                "mag": 8.0,
                "place": "2000 New Ireland Earthquake",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [152.17, -3.98, 33]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("New Britain/New Ireland", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_assess_event_queues_shallow_mw76_kokopo(self):
        feature = {
            "id": "test_kokopo_2019",
            "properties": {
                "mag": 7.6,
                "place": "48 km NE of Kokopo, Papua New Guinea",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [152.60, -4.05, 10]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("New Britain/New Ireland", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_solomon_2007_still_vanuatu(self):
        # USGS usp000f83m Mw8.1 2007 Solomon Islands — east of lon 155,
        # must stay on Vanuatu/Solomon (not only the new box).
        zones = usgs_listener.in_pacific_zone(-8.47, 157.04)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Vanuatu/Solomon")

    def test_png_highlands_not_matched(self):
        # USGS us2000d7q6 Mw7.5 2018 Tari highlands — inland, west of trench box.
        self.assertEqual(usgs_listener.in_pacific_zone(-6.07, 142.75), [])


if __name__ == "__main__":
    unittest.main()
