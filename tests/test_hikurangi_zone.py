"""Regression: Hikurangi / New Zealand trench must match PACIFIC_ZONES."""

import unittest
from unittest.mock import patch

import usgs_listener


class HikurangiNewZealandZoneTests(unittest.TestCase):
    def test_kaikoura_2016_mw78_tsunami_flag_matches(self):
        # USGS us1000778i Mw7.8 2016-11-13 Kaikoura, tsunami=1, depth 15 km.
        # South of Tonga/Kermadec lat min -35; lon 173E is west of Tonga's
        # (-180, -172) box.
        zones = usgs_listener.in_pacific_zone(-42.7373, 173.054)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Hikurangi/New Zealand")

    def test_gisborne_2021_mw73_tsunami_flag_matches(self):
        # USGS us7000dffl Mw7.3 2021-03-04, 182 km NE of Gisborne, tsunami=1.
        # lat -37.48 is south of Tonga lat min -35; lon +179.46 is the
        # western side of the dateline, not Tonga's negative-lon box.
        zones = usgs_listener.in_pacific_zone(-37.4787, 179.4576)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Hikurangi/New Zealand")

    def test_te_araroa_2016_mw70_tsunami_flag_matches(self):
        # USGS us10006jbi Mw7.0 2016-09-01, 175 km NE of Gisborne, tsunami=1.
        zones = usgs_listener.in_pacific_zone(-37.3586, 179.1461)
        self.assertTrue(any(z["name"] == "Hikurangi/New Zealand" for z in zones))

    def test_gisborne_2014_mw67_tsunami_flag_matches(self):
        # USGS usc000sxye Mw6.7 2014-11-16, 183 km NE of Gisborne, tsunami=1.
        zones = usgs_listener.in_pacific_zone(-37.6478, 179.6621)
        self.assertTrue(any(z["name"] == "Hikurangi/New Zealand" for z in zones))

    def test_puysegur_2025_mw67_tsunami_flag_matches(self):
        # USGS us7000pmem Mw6.7 2025-03-25, 170 km WSW of Riverton, tsunami=1.
        # Fiordland / Puysegur trench — west of Hikurangi, still NZ subduction.
        zones = usgs_listener.in_pacific_zone(-46.7305, 165.8632)
        self.assertTrue(any(z["name"] == "Hikurangi/New Zealand" for z in zones))

    def test_dusky_sound_2009_mw78_matches(self):
        # USGS usp000gz8j Mw7.8 2009-07-15 Dusky Sound / Fiordland.
        zones = usgs_listener.in_pacific_zone(-45.762, 166.562)
        self.assertTrue(any(z["name"] == "Hikurangi/New Zealand" for z in zones))

    def test_cook_strait_2013_mw65_tsunami_flag_matches(self):
        # USGS usb000j4iz Mw6.5 2013-08-16, 29 km SE of Blenheim, tsunami=1.
        zones = usgs_listener.in_pacific_zone(-41.734, 174.152)
        self.assertTrue(any(z["name"] == "Hikurangi/New Zealand" for z in zones))

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False})
    def test_assess_event_queues_shallow_mw78_kaikoura(self, _mock_fm):
        feature = {
            "id": "test_kaikoura_2016",
            "properties": {
                "mag": 7.8,
                "place": "53 km NNE of Amberley, New Zealand",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [173.054, -42.7373, 15.11]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Hikurangi/New Zealand", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "chat")

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False})
    def test_assess_event_queues_shallow_mw67_puysegur(self, _mock_fm):
        feature = {
            "id": "test_puysegur_2025",
            "properties": {
                "mag": 6.7,
                "place": "170 km WSW of Riverton, New Zealand",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [165.8632, -46.7305, 21]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Hikurangi/New Zealand", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "chat")

    def test_kermadec_still_tonga(self):
        # Typical Kermadec trench epicenter (2021 Mw8.1 class) — north of
        # NZ lat max -34, negative lon inside Tonga/Kermadec.
        zones = usgs_listener.in_pacific_zone(-29.6, -177.8)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Tonga/Kermadec")

    def test_macquarie_ridge_south_not_matched(self):
        # South of lat -48 — Macquarie Ridge, not NZ subduction boxes.
        self.assertEqual(usgs_listener.in_pacific_zone(-50.2, 166.5), [])


if __name__ == "__main__":
    unittest.main()
