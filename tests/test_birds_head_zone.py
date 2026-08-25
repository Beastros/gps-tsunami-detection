"""Regression: Bird's Head / Manokwari Trench must match PACIFIC_ZONES."""

import unittest
from unittest.mock import patch

import usgs_listener


class BirdsHeadManokwariZoneTests(unittest.TestCase):
    def test_manokwari_2009_mw77_thrust_matches(self):
        # USGS usp000gs2d Mw7.7 2009-01-03, 140 km WNW of Manokwari.
        # Thrust rake 103°, depth 17 km, tsunamigenic index 0.974 — ShakeMap pass.
        # PTWC recorded a local/Pacific tsunami (Chichijima 36 cm).
        # Sumatra lon max 110 / North New Guinea PR #82 lon min 136 leave
        # this Manokwari Trench corridor unmatched.
        zones = usgs_listener.in_pacific_zone(-0.414, 132.885)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Bird's Head/Manokwari")

    def test_manokwari_2009_mw74_aftershock_matches(self):
        # USGS usp000gs3t Mw7.4 2009-01-03, 86 km WNW of Manokwari.
        # Thrust rake 72°, depth 23 km, index 0.951 — ShakeMap pass.
        zones = usgs_listener.in_pacific_zone(-0.691, 133.305)
        self.assertTrue(any(z["name"] == "Bird's Head/Manokwari" for z in zones))

    def test_sorong_2015_mw66_matches(self):
        # USGS us20003nqr Mw6.6 2015-09-24, 28 km N of Sorong.
        # Thrust rake 91°, depth 18 km, index 1.000 — ShakeMap pass.
        zones = usgs_listener.in_pacific_zone(-0.6212, 131.2622)
        self.assertTrue(any(z["name"] == "Bird's Head/Manokwari" for z in zones))

    def test_manokwari_2004_mw65_matches(self):
        # USGS usp000d0zn Mw6.5 2004-07-28, 117 km WNW of Manokwari.
        # Thrust rake 80°, depth 13.4 km, index 0.985 — ShakeMap pass.
        zones = usgs_listener.in_pacific_zone(-0.443, 133.091)
        self.assertTrue(any(z["name"] == "Bird's Head/Manokwari" for z in zones))

    def test_manokwari_2001_mw65_matches(self):
        # USGS usp000ap03 Mw6.5 2001-09-11, 108 km WNW of Manokwari.
        zones = usgs_listener.in_pacific_zone(-0.578, 133.13)
        self.assertTrue(any(z["name"] == "Bird's Head/Manokwari" for z in zones))

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={
        "rake_deg": 103.0,
        "fault_type": "thrust",
        "rake_score": 0.974,
        "product_type": "moment-tensor",
        "source": "us",
        "available": True,
    })
    def test_assess_event_queues_2009_thrust(self, _mock_fm):
        feature = {
            "id": "usp000gs2d",
            "properties": {
                "mag": 7.7,
                "place": "140 km WNW of Manokwari, Indonesia",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [132.885, -0.414, 17]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Bird's Head/Manokwari", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")
        self.assertGreaterEqual(candidate["tsunamigenic_index"], 0.25)

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False})
    def test_assess_event_queues_shallow_mw66_fail_open(self, _mock_fm):
        feature = {
            "id": "us20003nqr",
            "properties": {
                "mag": 6.6,
                "place": "28 km N of Sorong, Indonesia",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [131.2622, -0.6212, 18]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Bird's Head/Manokwari", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_flores_inner_seas_not_matched(self):
        # Live us6000tkt2 Mw7.7 2026-08-14 is Flores/Banda inner seas, not this trench.
        self.assertEqual(usgs_listener.in_pacific_zone(-8.310, 121.352), [])

    def test_nabire_cenderawasih_not_matched(self):
        # 2004 Nabire usp000d975 is Cenderawasih Bay; PR #82 excluded west of lon 136
        # and this box stops at lat -1 so the inner-bay cluster stays unmatched.
        self.assertEqual(usgs_listener.in_pacific_zone(-3.609, 135.404), [])

    def test_biak_not_this_zone(self):
        # 1996 Biak Mw8.1 is east of lon 136 (North New Guinea hole, PR #82).
        self.assertEqual(usgs_listener.in_pacific_zone(-0.891, 136.952), [])

    def test_bitung_not_this_zone(self):
        # 2026 Bitung us6000slss is west of lon 130 (Molucca/Sangihe hole, PR #86).
        self.assertEqual(usgs_listener.in_pacific_zone(1.093, 126.235), [])


if __name__ == "__main__":
    unittest.main()
