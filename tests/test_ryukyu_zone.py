"""Regression: Ryukyu Trench / Nansei Islands must match PACIFIC_ZONES."""

import unittest
from unittest.mock import patch

import usgs_listener


class RyukyuZoneTests(unittest.TestCase):
    def test_amami_2009_mw68_thrust_matches(self):
        # USGS usp000h3jp Mw6.8 2009-10-30, 98 km NNE of Naze.
        # Thrust rake 66°, depth 34 km, tsunamigenic index 0.64 — ShakeMap pass.
        # West of Japan/Kuril lon min 130 and south of lat min 30.
        zones = usgs_listener.in_pacific_zone(29.218, 129.782)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Ryukyu")

    def test_naze_1995_mw71_matches(self):
        # USGS usp00075bd Mw7.1 1995-10-18, 83 km SE of Naze, depth 28 km.
        # Plane-1 normal still scores 0.365 > skip threshold 0.25.
        zones = usgs_listener.in_pacific_zone(27.929, 130.175)
        self.assertTrue(any(z["name"] == "Ryukyu" for z in zones))

    def test_naze_1995_aftershock_mw68_matches(self):
        # USGS usp00075db Mw6.8 1995-10-19, 71 km ESE of Naze, depth 20 km.
        zones = usgs_listener.in_pacific_zone(28.094, 130.148)
        self.assertTrue(any(z["name"] == "Ryukyu" for z in zones))

    def test_okinawa_2010_mw70_matches_geographically(self):
        # USGS usp000h7qu Mw7.0 2010-02-26, 70 km SE of Katsuren-haebaru.
        # Strike-slip is ShakeMap-skipped; the trench location must still match.
        zones = usgs_listener.in_pacific_zone(25.93, 128.425)
        self.assertTrue(any(z["name"] == "Ryukyu" for z in zones))

    def test_okinawa_2010_mw65_matches_geographically(self):
        # USGS usp000hd6j Mw6.5 2010-05-26, 216 km ESE of Katsuren-haebaru.
        zones = usgs_listener.in_pacific_zone(25.773, 129.944)
        self.assertTrue(any(z["name"] == "Ryukyu" for z in zones))

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False})
    def test_assess_event_queues_shallow_mw68_amami(self, _mock_fm):
        feature = {
            "id": "test_amami_2009",
            "properties": {
                "mag": 6.8,
                "place": "98 km NNE of Naze, Japan",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [129.782, 29.218, 34]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Ryukyu", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False})
    def test_assess_event_queues_shallow_mw71_naze(self, _mock_fm):
        feature = {
            "id": "test_naze_1995",
            "properties": {
                "mag": 7.1,
                "place": "83 km SE of Naze, Japan",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [130.175, 27.929, 28.4]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Ryukyu", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_kyushu_japan_still_japan(self):
        # USGS usp0007rku Mw6.6 1996 Nishinoomote at lat 30.57 is already Japan/Kuril.
        zones = usgs_listener.in_pacific_zone(30.568, 131.093)
        self.assertTrue(any(z["name"] == "Japan/Kuril" for z in zones))

    def test_taiwan_east_coast_not_this_zone(self):
        # 2025 Yilan Mw6.6 us7000rl2n (tsunami=1) is Philippines/Taiwan (#77), not Ryukyu.
        zones = usgs_listener.in_pacific_zone(24.6841, 122.0354)
        self.assertFalse(any(z["name"] == "Ryukyu" for z in zones))

    def test_east_china_sea_west_not_matched(self):
        # USGS usp000jajd 2011 Mw6.9 WNW of Naha (125.6E, 225 km) stays out so the
        # box does not swallow Okinawa Trough / East China Sea events west of 126.
        self.assertEqual(usgs_listener.in_pacific_zone(27.324, 125.621), [])

    def test_mariana_not_this_zone(self):
        # East of box toward Marianas — not this zone (Mariana coverage separate).
        self.assertEqual(usgs_listener.in_pacific_zone(15.0, 140.0), [])


if __name__ == "__main__":
    unittest.main()
