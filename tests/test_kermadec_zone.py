"""Regression: Tonga/Kermadec zone must span the antimeridian."""

import unittest

import usgs_listener


class KermadecZoneTests(unittest.TestCase):
    def test_east_of_dateline_kermadec_is_in_zone(self):
        # Concrete 2026-08-05 event us6000ti8i (Mw6.3 south of Kermadec).
        # lon≈+179 is east of the dateline; the old box (-180,-172) missed it.
        zones = usgs_listener.in_pacific_zone(-33.8063, 179.4727)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Tonga/Kermadec")

    def test_west_of_dateline_kermadec_still_matches(self):
        zones = usgs_listener.in_pacific_zone(-29.51, -177.0)
        self.assertTrue(zones)
        self.assertEqual(zones[0]["name"], "Tonga/Kermadec")

    def test_positive_lon_strip_inside_lat_band(self):
        zones = usgs_listener.in_pacific_zone(-30.0, 175.0)
        self.assertTrue(any(z["name"] == "Tonga/Kermadec" for z in zones))

    def test_outside_lat_band_not_matched(self):
        self.assertEqual(usgs_listener.in_pacific_zone(-36.0, 179.0), [])


if __name__ == "__main__":
    unittest.main()
