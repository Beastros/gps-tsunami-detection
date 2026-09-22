"""Regression: Colombia/Ecuador/Panama Pacific trench must match PACIFIC_ZONES."""

import unittest

import usgs_listener


class ColombiaEcuadorZoneTests(unittest.TestCase):
    def test_tumaco_corridor_matches_south_america(self):
        # Historical Mw7.7 Tumaco, Colombia (1979): Pacific trench, previously
        # in the hole between Central America (lat>=5, lon<=-82) and
        # South America (lat<=-5).
        zones = usgs_listener.in_pacific_zone(1.6, -79.3)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "South America")

    def test_esmeraldas_ecuador_matches(self):
        zones = usgs_listener.in_pacific_zone(0.5, -79.5)
        self.assertTrue(any(z["name"] == "South America" for z in zones))

    def test_panama_pacific_matches_central_america(self):
        # Pacific Panama sits east of the old Central America lon max (-82).
        zones = usgs_listener.in_pacific_zone(8.0, -79.5)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Central America")

    def test_live_colombia_coords_match_when_shallow(self):
        # Live USGS us6000tjl2 (Mw7.4 Colombia, lat≈4.84, lon≈-76.24) matched
        # no zone before the fix. Depth 110 km still fails the depth filter;
        # a shallow event at the same epicenter must queue.
        zones = usgs_listener.in_pacific_zone(4.844, -76.242)
        self.assertTrue(any(z["name"] == "South America" for z in zones))

    def test_assess_event_queues_shallow_mw7_colombia_trench(self):
        feature = {
            "id": "test_colombia_trench",
            "properties": {
                "mag": 7.0,
                "place": "near the coast of Colombia",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [-79.3, 1.6, 33]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("South America", candidate["zones"])

    def test_assess_event_queues_shallow_panama_pacific(self):
        feature = {
            "id": "test_panama_pacific",
            "properties": {
                "mag": 6.8,
                "place": "south of Panama",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [-79.5, 8.0, 20]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Central America", candidate["zones"])

    def test_costa_rica_still_matches(self):
        zones = usgs_listener.in_pacific_zone(9.5, -84.0)
        self.assertTrue(any(z["name"] == "Central America" for z in zones))

    def test_chile_still_matches(self):
        zones = usgs_listener.in_pacific_zone(-19.6, -70.8)
        self.assertTrue(any(z["name"] == "South America" for z in zones))

    def test_caribbean_colombia_still_excluded(self):
        # Caribbean coast near Cartagena should remain outside Pacific boxes.
        self.assertEqual(usgs_listener.in_pacific_zone(10.4, -75.5), [])


if __name__ == "__main__":
    unittest.main()
