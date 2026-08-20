"""Regression: New Guinea Trench / north coast must match PACIFIC_ZONES."""

import unittest
from unittest.mock import patch

import usgs_listener


class NorthNewGuineaZoneTests(unittest.TestCase):
    def test_aitape_1998_mw70_matches(self):
        # USGS usp0008rpa Mw7.0 1998-07-17 Sissano / Aitape tsunami.
        # Thrust, depth 10 km; west of New Britain lon min 148 and north of
        # Vanuatu/Solomon lat min -5 with lon 141.9 (west of 155).
        zones = usgs_listener.in_pacific_zone(-2.961, 141.926)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "North New Guinea")

    def test_aitape_2002_mw76_matches(self):
        # USGS usp000bbpf Mw7.6 2002-09-08, 68 km ESE of Aitape, thrust.
        zones = usgs_listener.in_pacific_zone(-3.302, 142.945)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "North New Guinea")

    def test_biak_1996_mw81_matches(self):
        # USGS official19960217055930550_33 Mw8.1 1996-02-17 Biak tsunami.
        zones = usgs_listener.in_pacific_zone(-0.891, 136.952)
        self.assertTrue(any(z["name"] == "North New Guinea" for z in zones))

    def test_abepura_2015_mw70_tsunami_flag_matches(self):
        # USGS us200030kn Mw7.0 2015-07-27, 234 km W of Abepura, tsunami=1.
        zones = usgs_listener.in_pacific_zone(-2.629, 138.528)
        self.assertTrue(any(z["name"] == "North New Guinea" for z in zones))

    def test_madang_2023_mw67_tsunami_flag_matches(self):
        # USGS us6000ldqd Mw6.7 2023-10-07, 54 km SE of Madang, tsunami=1.
        zones = usgs_listener.in_pacific_zone(-5.573, 146.138)
        self.assertTrue(any(z["name"] == "North New Guinea" for z in zones))

    def test_wewak_2002_mw67_matches(self):
        # USGS usp000aw5z Mw6.7 2002-01-10, 11 km SE of Aitape, thrust.
        zones = usgs_listener.in_pacific_zone(-3.212, 142.427)
        self.assertTrue(any(z["name"] == "North New Guinea" for z in zones))

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False})
    def test_assess_event_queues_shallow_mw70_aitape(self, _mock_fm):
        feature = {
            "id": "test_aitape_1998",
            "properties": {
                "mag": 7.0,
                "place": "50 km WNW of Aitape, Papua New Guinea",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [141.926, -2.961, 10]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("North New Guinea", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False})
    def test_assess_event_queues_shallow_mw81_biak(self, _mock_fm):
        feature = {
            "id": "test_biak_1996",
            "properties": {
                "mag": 8.1,
                "place": "1996 Biak, Indonesia Earthquake",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [136.952, -0.891, 33]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("North New Guinea", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_new_britain_east_not_this_zone(self):
        # East of lon 148 — Bismarck / New Britain, not this box.
        zones = usgs_listener.in_pacific_zone(-5.5, 151.5)
        self.assertFalse(any(z["name"] == "North New Guinea" for z in zones))

    def test_vanuatu_solomon_still_vanuatu(self):
        zones = usgs_listener.in_pacific_zone(-15.0, 167.0)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Vanuatu/Solomon")

    def test_flores_banda_not_matched(self):
        # Live Mw7.7 us6000tkt2 inner-seas Flores — west and south of this box.
        self.assertEqual(usgs_listener.in_pacific_zone(-8.310, 121.352), [])

    def test_nabire_cenderawasih_west_not_matched(self):
        # Bird's Head interior / Cenderawasih (usp000d975 lon 135.4) stays out
        # so the box does not swallow non-Pacific-trench highlands/bay events.
        self.assertEqual(usgs_listener.in_pacific_zone(-3.609, 135.404), [])


if __name__ == "__main__":
    unittest.main()
