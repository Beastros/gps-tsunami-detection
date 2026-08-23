"""Regression: North Kamchatka / Ozernoy must match PACIFIC_ZONES."""

import unittest
from unittest.mock import patch

import usgs_listener


class NorthKamchatkaZoneTests(unittest.TestCase):
    def test_ust_kamchatsk_2017_mw66_thrust_matches(self):
        # USGS us20008vhl Mw6.6 2017-03-29, 81 km NNE of Ust’-Kamchatsk.
        # Thrust rake 92.3°, depth 17 km, tsunamigenic index 0.999 — ShakeMap pass.
        # USGS tsunami flag 1. North of Japan/Kuril lat max 55; west of
        # Alaska/Aleutian (even after PR #73 lon min 165).
        zones = usgs_listener.in_pacific_zone(56.940, 162.786)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "North Kamchatka")

    def test_ozernoy_1969_mw74_matches(self):
        # USGS iscgem802552 Mw7.4 1969-11-22, 172 km NNE of Ust’-Kamchatsk.
        # Ozernoy Peninsula tsunami earthquake; 1.67° north of Japan/Kuril.
        zones = usgs_listener.in_pacific_zone(57.668, 163.510)
        self.assertTrue(any(z["name"] == "North Kamchatka" for z in zones))

    def test_historical_mw80_1917_matches(self):
        # USGS iscgem913404 Mw8.0 at 56.154N 163.174E.
        zones = usgs_listener.in_pacific_zone(56.154, 163.174)
        self.assertTrue(any(z["name"] == "North Kamchatka" for z in zones))

    def test_historical_mw78_matches(self):
        # USGS iscgem16957872 Mw7.8 at 55.751N 163.952E.
        zones = usgs_listener.in_pacific_zone(55.751, 163.952)
        self.assertTrue(any(z["name"] == "North Kamchatka" for z in zones))

    def test_2018_mw73_matches_geographically(self):
        # USGS us2000ivfw Mw7.3 2018-12-20, 187 km SE of Ust’-Kamchatsk.
        # Strike-slip is ShakeMap-skipped; the trench location must still match.
        # 0.10° north of Japan/Kuril lat max 55.
        zones = usgs_listener.in_pacific_zone(55.100, 164.699)
        self.assertTrue(any(z["name"] == "North Kamchatka" for z in zones))

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={
        "rake_deg": 92.3,
        "fault_type": "thrust",
        "rake_score": 0.999,
        "product_type": "moment-tensor",
        "source": "us",
        "available": True,
    })
    def test_assess_event_queues_2017_thrust(self, _mock_fm):
        feature = {
            "id": "us20008vhl",
            "properties": {
                "mag": 6.6,
                "place": "81 km NNE of Ust’-Kamchatsk Staryy, Russia",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [162.786, 56.940, 17]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("North Kamchatka", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")
        self.assertGreaterEqual(candidate["tsunamigenic_index"], 0.25)

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False})
    def test_assess_event_queues_shallow_mw80_fail_open(self, _mock_fm):
        feature = {
            "id": "test_ozernoy_1917",
            "properties": {
                "mag": 8.0,
                "place": "43 km E of Ust’-Kamchatsk Staryy, Russia",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [163.174, 56.154, 20]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("North Kamchatka", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_petropavlovsk_still_japan_kuril(self):
        # Live us7000sui3 Mw6.6 east of Petropavlovsk is already Japan/Kuril.
        zones = usgs_listener.in_pacific_zone(53.249, 160.651)
        self.assertTrue(any(z["name"] == "Japan/Kuril" for z in zones))
        self.assertFalse(any(z["name"] == "North Kamchatka" for z in zones))

    def test_kronotsky_1997_still_japan_kuril(self):
        # USGS usp0008btk Mw7.8 1997 at 54.841N stays south of lat 55.
        zones = usgs_listener.in_pacific_zone(54.841, 162.035)
        self.assertTrue(any(z["name"] == "Japan/Kuril" for z in zones))
        self.assertFalse(any(z["name"] == "North Kamchatka" for z in zones))

    def test_tilichiki_inland_not_matched(self):
        # USGS usp000ef1h Mw7.6 2006 Olyutorsky / Tilichiki is inland Koryak,
        # not the Pacific trench (tsunami flag 0).
        self.assertEqual(usgs_listener.in_pacific_zone(60.949, 167.089), [])

    def test_commander_islands_not_this_zone(self):
        # USGS us20009x42 Mw7.7 2017 Komandorskiye Ostrova is east of lon 166
        # (covered by PR #73 Alaska lon min 165, and is strike-slip skipped).
        self.assertEqual(usgs_listener.in_pacific_zone(54.443, 168.857), [])


if __name__ == "__main__":
    unittest.main()
