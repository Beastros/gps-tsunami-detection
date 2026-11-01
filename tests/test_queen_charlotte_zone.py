"""Regression: Queen Charlotte / Haida Gwaii must match PACIFIC_ZONES."""

import unittest
from unittest.mock import patch

import usgs_listener


class QueenCharlotteZoneTests(unittest.TestCase):
    def test_haida_gwaii_2012_mw78_thrust_matches(self):
        # USGS usp000juhz Mw7.8 2012-10-28, 206 km SW of Prince Rupert.
        # Thrust rake 115°, depth 14 km, tsunamigenic index 0.906 — ShakeMap pass.
        # North of Cascadia/BC lat max 52; east of Alaska/Aleutian lon max -145.
        # Project backtest/README list this event as TRUE_POSITIVE (HNLC–GUAM).
        zones = usgs_listener.in_pacific_zone(52.788, -132.101)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Queen Charlotte/Haida Gwaii")

    def test_haida_gwaii_2012_aftershock_mw63_matches(self):
        # USGS usp000junu Mw6.3 2012-10-28, 237 km SW of Prince Rupert.
        zones = usgs_listener.in_pacific_zone(52.674, -132.602)
        self.assertTrue(any(z["name"] == "Queen Charlotte/Haida Gwaii" for z in zones))

    def test_haida_gwaii_2012_aftershock_mw62_matches(self):
        # USGS usp000jus5 Mw6.2 2012-10-30, 241 km SSW of Prince Rupert.
        zones = usgs_listener.in_pacific_zone(52.365, -131.902)
        self.assertTrue(any(z["name"] == "Queen Charlotte/Haida Gwaii" for z in zones))

    def test_haida_gwaii_2009_mw66_matches_geographically(self):
        # USGS usp000h44s Mw6.6 2009-11-17, 254 km SSW of Prince Rupert.
        # Strike-slip is ShakeMap-skipped; the trench location must still match.
        # 0.12° north of Cascadia/BC lat max 52.
        zones = usgs_listener.in_pacific_zone(52.123, -131.395)
        self.assertTrue(any(z["name"] == "Queen Charlotte/Haida Gwaii" for z in zones))

    def test_craig_2013_mw75_matches_geographically(self):
        # USGS ak0138esnzr Mw7.5 2013-01-05, 110 km SW of Edna Bay.
        # Queen Charlotte Fault strike-slip is ShakeMap-skipped.
        zones = usgs_listener.in_pacific_zone(55.228, -134.859)
        self.assertTrue(any(z["name"] == "Queen Charlotte/Haida Gwaii" for z in zones))

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={
        "rake_deg": 115.0,
        "fault_type": "thrust",
        "rake_score": 0.906,
        "product_type": "moment-tensor",
        "source": "us",
        "available": True,
    })
    def test_assess_event_queues_haida_gwaii_thrust(self, _mock_fm):
        feature = {
            "id": "usp000juhz",
            "properties": {
                "mag": 7.8,
                "place": "206 km SW of Prince Rupert, Canada",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [-132.101, 52.788, 14]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Queen Charlotte/Haida Gwaii", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")
        self.assertGreaterEqual(candidate["tsunamigenic_index"], 0.25)

    @patch.object(usgs_listener, "fetch_focal_mechanism", return_value={"available": False})
    def test_assess_event_queues_shallow_mw78_fail_open(self, _mock_fm):
        feature = {
            "id": "test_haida_gwaii_2012",
            "properties": {
                "mag": 7.8,
                "place": "206 km SW of Prince Rupert, Canada",
                "type": "earthquake",
                "time": 0,
            },
            "geometry": {"coordinates": [-132.101, 52.788, 14]},
        }
        candidate = usgs_listener.assess_event(feature)
        self.assertIsNotNone(candidate)
        self.assertIn("Queen Charlotte/Haida Gwaii", candidate["zones"])
        self.assertEqual(candidate["primary_anchor"], "guam")

    def test_cascadia_port_mcneill_still_cascadia(self):
        # USGS us7000ne51 Mw6.5 2024 west of Port McNeill is already Cascadia/BC.
        zones = usgs_listener.in_pacific_zone(51.609, -130.612)
        self.assertTrue(any(z["name"] == "Cascadia/BC" for z in zones))
        self.assertFalse(any(z["name"] == "Queen Charlotte/Haida Gwaii" for z in zones))

    def test_alaska_kenai_not_this_zone(self):
        # Inside Alaska/Aleutian (lon west of -145), not Queen Charlotte.
        zones = usgs_listener.in_pacific_zone(59.0, -150.0)
        self.assertTrue(any(z["name"] == "Alaska/Aleutian" for z in zones))
        self.assertFalse(any(z["name"] == "Queen Charlotte/Haida Gwaii" for z in zones))

    def test_hubbard_glacier_inland_not_matched(self):
        # USGS us6000rsy1 Mw7.0 2025 Hubbard Glacier is strike-slip inland
        # St. Elias, not the Queen Charlotte trench.
        self.assertEqual(usgs_listener.in_pacific_zone(60.313, -139.541), [])

    def test_sitka_north_not_this_zone(self):
        # 1972 Sitka Mw7.6 iscgem772060 at 56.67N stays north of lat max 56.
        self.assertEqual(usgs_listener.in_pacific_zone(56.674, -135.918), [])


if __name__ == "__main__":
    unittest.main()
