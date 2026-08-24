"""Regression: Molucca Sea / Sangihe-Talaud must match PACIFIC_ZONES."""

import unittest
from unittest.mock import patch

import usgs_listener


class MoluccaSangiheZoneTests(unittest.TestCase):
    def test_bitung_2026_mw74_thrust_matches(self):
        # USGS us6000slss Mw7.4 2026-04-01, 129 km ESE of Bitung.
        # Thrust rake 69.4°, depth 35 km, tsunamigenic index 0.655 — ShakeMap pass.
        # Live-window miss: not in event_queue; Sumatra lon max 110 /
        # Philippines PR #77 lat min 4 leave this Molucca corridor unmatched.
        zones = usgs_listener.in_pacific_zone(1.093, 126.235)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Molucca/Sangihe")

    def test_ternate_2019_mw71_tsunami_flag_matches(self):
        # USGS us60006bjl Mw7.1 2019-11-14, 141 km NW of Ternate.
        # Thrust rake 75.8°, tsunami=1, index 0.678 — ShakeMap pass.
        zones = usgs_listener.in_pacific_zone(1.621, 126.416)
        self.assertTrue(any(z["name"] == "Molucca/Sangihe" for z in zones))

    def test_ternate_2014_mw71_tsunami_flag_matches(self):
        # USGS usc000sxh8 Mw7.1 2014-11-15, 155 km NW of Ternate.
        # Thrust rake 79°, tsunami=1, index 0.687 — ShakeMap pass.
        zones = usgs_listener.in_pacific_zone(1.893, 126.522)
        self.assertTrue(any(z["name"] == "Molucca/Sangihe" for z in zones))

    def test_ternate_2007_mw75_matches(self):
        # USGS usp000f34b Mw7.5 2007-01-21, 126 km WNW of Ternate.
        # Thrust rake 78°, index 0.978 — ShakeMap pass.
        zones = usgs_listener.in_pacific_zone(1.065, 126.282)
        self.assertTrue(any(z["name"] == "Molucca/Sangihe" for z in zones))

    def test_sarangani_2009_mw72_matches(self):
        # USGS usp000gtnc Mw7.2 2009-02-11, 196 km SSE of Sarangani.
        # Southern Philippine Trench / Talaud; 0.11° south of PR #77 lat min 4.
        # Thrust rake 68°, index 0.927 — ShakeMap pass.
        zones = usgs_listener.in_pacific_zone(3.886, 126.387)
        self.assertTrue(any(z["name"] == "Molucca/Sangihe" for z in zones))

    def test_sarangani_2016_mw65_tsunami_flag_matches(self):
        # USGS us10004dj5 Mw6.5 2016-01-11, 227 km SE of Sarangani.
        # Thrust rake 101°, tsunami=1, index 0.982 — ShakeMap pass.
        zones = usgs_listener.in_pacific_zone(3.897, 126.862)
        self.assertTrue(any(z["name"] == "Molucca/Sangihe" for z in zones))

    def test_tobelo_2003_mw70_pacific_side_matches(self):
        # USGS usp000by7n Mw7.0 2003-05-26, 116 km NE of Tobelo (Philippine Sea).
        # Thrust rake 67°, index 0.645 — ShakeMap pass.
        zones = usgs_listener.in_pacific_zone(2.354, 128.855)
        self.assertTrue(any(z["name"] == "Molucca/Sangihe" for z in zones))

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={
        "rake_deg": 69.4,
        "fault_type": "thrust",
        "rake_score": 0.936,
        "product_type": "moment-tensor",
        "source": "us",
        "available": True,
    })
    def test_assess_event_queues_2026_thrust(self, _mock_fm):
        feature = {
            "id": "us6000slss",
            "properties": {
                "mag": 7.4,
                "place": "129 km ESE of Bitung, Indonesia",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [126.235, 1.093, 35]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Molucca/Sangihe", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")
        self.assertGreaterEqual(candidate["tsunamigenic_index"], 0.25)

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False})
    def test_assess_event_queues_shallow_mw71_fail_open(self, _mock_fm):
        feature = {
            "id": "us60006bjl",
            "properties": {
                "mag": 7.1,
                "place": "141 km NW of Ternate, Indonesia",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [126.416, 1.621, 33]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Molucca/Sangihe", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_flores_inner_seas_not_matched(self):
        # Live us6000tkt2 Mw7.7 2026-08-14 is Flores/Banda inner seas, not this trench.
        self.assertEqual(usgs_listener.in_pacific_zone(-8.310, 121.352), [])

    def test_palu_celebes_not_matched(self):
        # 2018 Palu us1000h3p4 is Celebes/Palu Bay (strike-slip), west of lon 125.
        self.assertEqual(usgs_listener.in_pacific_zone(-0.256, 119.846), [])

    def test_mindanao_not_this_zone(self):
        # Live-window us7000srb1 Mw7.8 2026-06-07 is north of lat 4
        # (Philippines/Taiwan hole, PR #77 — not this box).
        self.assertEqual(usgs_listener.in_pacific_zone(5.599, 125.056), [])


if __name__ == "__main__":
    unittest.main()
