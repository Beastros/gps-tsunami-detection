"""Regression: Mexico Pacific trench west of lon -100 must match PACIFIC_ZONES."""

import unittest

import usgs_listener


class MexicoPacificZoneTests(unittest.TestCase):
    def test_michoacan_2022_mw76_matches(self):
        # USGS us7000i9bw Mw7.6 2022-09-19, 35 km SSW of Aguililla, Mexico.
        # tsunami=1; west of Central America lon min -100.
        zones = usgs_listener.in_pacific_zone(18.46, -102.96)
        self.assertTrue(zones)
        self.assertTrue(any(z["name"] == "Mexico Pacific" for z in zones))

    def test_colima_jalisco_1995_mw80_matches(self):
        # USGS usp00074vc Mw8.0 1995-10-09 Colima-Jalisco.
        zones = usgs_listener.in_pacific_zone(19.05, -104.20)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Mexico Pacific")

    def test_michoacan_1985_mw80_matches(self):
        # USGS usp0002jwe Mw8.0 1985-09-19 Michoacan.
        zones = usgs_listener.in_pacific_zone(18.19, -102.53)
        self.assertTrue(any(z["name"] == "Mexico Pacific" for z in zones))

    def test_colima_2003_mw76_matches(self):
        # USGS usp000bnyr Mw7.6 2003-01-22, 16 km SSW of Cuyutlán.
        zones = usgs_listener.in_pacific_zone(18.77, -104.10)
        self.assertTrue(any(z["name"] == "Mexico Pacific" for z in zones))

    def test_guerrero_2014_west_of_minus_100_matches(self):
        # USGS usb000pq41 Mw7.2 2014-04-18, tsunami=1, lon -100.97.
        zones = usgs_listener.in_pacific_zone(17.40, -100.97)
        self.assertTrue(any(z["name"] == "Mexico Pacific" for z in zones))

    def test_manzanillo_dart_neighborhood_matches(self):
        # DART 43412 sits at ~16.04N, 106.98W — outside Central America lon min.
        zones = usgs_listener.in_pacific_zone(16.04, -106.50)
        self.assertTrue(any(z["name"] == "Mexico Pacific" for z in zones))

    def test_assess_event_queues_shallow_mw76_michoacan(self):
        feature = {
            "id": "test_michoacan_trench",
            "properties": {
                "mag": 7.6,
                "place": "35 km SSW of Aguililla, Mexico",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [-102.96, 18.46, 27]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Mexico Pacific", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "chat")

    def test_assess_event_queues_shallow_mw80_colima(self):
        feature = {
            "id": "test_colima_jalisco",
            "properties": {
                "mag": 8.0,
                "place": "1995 Colima-Jalisco, Mexico Earthquake",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [-104.20, 19.05, 33]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Mexico Pacific", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "chat")

    def test_acapulco_still_central_america(self):
        # USGS us7000f93v Mw7.0 2021 Acapulco — east of -100, must stay
        # on Central America (not only the new Mexico box).
        zones = usgs_listener.in_pacific_zone(16.95, -99.75)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Central America")

    def test_gulf_of_california_not_matched(self):
        # Strike-slip Gulf of California, west/north of the trench box.
        self.assertEqual(usgs_listener.in_pacific_zone(27.9, -111.0), [])


if __name__ == "__main__":
    unittest.main()
