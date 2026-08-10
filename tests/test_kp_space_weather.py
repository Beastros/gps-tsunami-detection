"""Regression: geomagnetic Kp gate and space-weather fusion must stay wired."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_detector():
    # Import via path so tests work even when scripts/ is on PYTHONPATH.
    spec = importlib.util.spec_from_file_location(
        "detector_runner_under_test",
        ROOT / "detector_runner.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestKpParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dr = _load_detector()

    def test_select_kp_from_current_dict_shaped_feed(self):
        # Live NOAA format as of 2026-08: list of dicts with ISO time_tag.
        data = [
            {"time_tag": "2026-08-03T00:00:00", "Kp": 2.0, "a_running": 7, "station_count": 8},
            {"time_tag": "2026-08-03T03:00:00", "Kp": 4.33, "a_running": 32, "station_count": 8},
            {"time_tag": "2026-08-03T06:00:00", "Kp": 1.67, "a_running": 6, "station_count": 8},
        ]
        kp = self.dr.select_kp_near_quake(data, "2026-08-03T03:10:00+00:00")
        self.assertEqual(kp, 4.33)

    def test_select_kp_from_legacy_list_rows(self):
        data = [
            ["time_tag", "Kp", "Kp_fraction", "a_running", "station_count"],
            ["2026-08-03 00:00:00", "2.0", "2.00", "7", "8"],
            ["2026-08-03 03:00:00", "5.0", "5.00", "48", "8"],
            ["2026-08-03 06:00:00", "1.0", "1.00", "4", "8"],
        ]
        kp = self.dr.select_kp_near_quake(data, "2026-08-03T02:50:00Z")
        self.assertEqual(kp, 5.0)

    def test_fetch_kp_disturbed_enables_gate_flag(self):
        payload = [
            {"time_tag": "2026-08-03T00:00:00", "Kp": 4.67, "a_running": 39, "station_count": 8},
        ]

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                import json

                return json.dumps(payload).encode("utf-8")

        with mock.patch("urllib.request.urlopen", return_value=_Resp()):
            kp = self.dr.fetch_kp("2026-08-03T00:05:00+00:00")
        self.assertEqual(kp, 4.67)
        self.assertGreaterEqual(kp, self.dr.KP_THRESHOLD)


class TestSpaceWeatherWiring(unittest.TestCase):
    def test_run_event_wires_space_weather_quality_into_prediction(self):
        """run_event must call get_space_weather_quality (not leave score stuck at 0)."""
        src = (ROOT / "detector_runner.py").read_text(encoding="utf-8")
        # Import alone is insufficient — May 2026 left the call site unwired.
        self.assertIn("from space_weather import get_space_weather_quality", src)
        self.assertIn("_sw_quality = get_space_weather_quality()", src)
        self.assertIn('prediction["space_weather_score"]', src)
        self.assertIn('prediction["space_weather_gated"]', src)
        self.assertIn('prediction["space_weather_flags"]', src)

        scripts_src = (ROOT / "scripts" / "detector_runner.py").read_text(encoding="utf-8")
        self.assertIn("_sw_quality = get_space_weather_quality()", scripts_src)


if __name__ == "__main__":
    unittest.main()
