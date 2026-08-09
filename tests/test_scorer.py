import unittest
from unittest.mock import patch

import scorer
from scripts import scorer as scripts_scorer


SIGNAL = {
    "arrival_h_post_quake": 5.0,
    "amplitude_m": 0.1,
    "detection_method": "test",
}


def event(detected):
    return {
        "usgs_id": "test-event",
        "quake_utc": "2026-01-01T00:00:00+00:00",
        "magnitude": 7.0,
        "place": "Test event",
        "primary_anchor": "guam",
        "prediction": {
            "detected": detected,
            "combined_confidence": 0.5 if detected else 0.0,
            "detection": {"post_h": 3.0},
            "wave_forecast": {"predicted_wave_m": 0.08},
        },
    }


def gauges(signal_at=None):
    return {
        name: {
            "primary": config["primary"],
            "tsunami": SIGNAL if name == signal_at else None,
        }
        for name, config in scorer.GAUGE_NETWORK.items()
    }


class MultiGaugeScoringTests(unittest.TestCase):
    @patch("dyfi_checker.get_dyfi_contribution",
           return_value=(None, None, None, False))
    def test_secondary_gauge_signal_makes_algorithm_miss_false_negative(self, _):
        for module in (scorer, scripts_scorer):
            with self.subTest(module=module.__name__):
                score = module.score_event(event(False), gauges("midway"))

                self.assertFalse(score["gauge_tsunami"])
                self.assertTrue(score["any_gauge_tsunami"])
                self.assertEqual(score["outcome"], "FALSE_NEGATIVE")
                self.assertEqual(score["outcome_confidence"], "FALSE_NEGATIVE")
                self.assertEqual(score["tide_gauge_truth"], SIGNAL)

                log_data = {"scored_events": [score], "summary": {}}
                module.update_summary(log_data)
                self.assertEqual(log_data["summary"]["true_negatives"], 0)
                self.assertEqual(log_data["summary"]["false_negatives"], 1)

    @patch("dyfi_checker.get_dyfi_contribution",
           return_value=(None, None, None, False))
    def test_secondary_gauge_signal_makes_algorithm_detection_true_positive(self, _):
        for module in (scorer, scripts_scorer):
            with self.subTest(module=module.__name__):
                score = module.score_event(event(True), gauges("pago"))

                self.assertEqual(score["outcome"], "TRUE_POSITIVE")
                self.assertEqual(score["lead_time_min"], 120)
                self.assertEqual(score["amplitude_actual_m"], 0.1)

    @patch("dyfi_checker.get_dyfi_contribution",
           return_value=(None, None, None, False))
    def test_no_gauge_signal_remains_true_negative(self, _):
        for module in (scorer, scripts_scorer):
            with self.subTest(module=module.__name__):
                score = module.score_event(event(False), gauges())

                self.assertFalse(score["any_gauge_tsunami"])
                self.assertEqual(score["outcome"], "TRUE_NEGATIVE")


if __name__ == "__main__":
    unittest.main()
