import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import detector_runner
import rinex_downloader
import retroactive_rinex
import scorer


class DetectorRinexContractTests(unittest.TestCase):
    def test_detector_uses_manifest_aliases_on_adjacent_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            rinex_dir = Path(tmp)
            (rinex_dir / "gvim0020.26o.Z").write_bytes(b"fake obs")
            (rinex_dir / "mkea0020.26o.Z").write_bytes(b"fake obs")
            (rinex_dir / "rinex_manifest.json").write_text(
                json.dumps(
                    {
                        "days": [
                            {
                                "year": 2026,
                                "doy": 2,
                                "resolved": {"guam": "gvim", "mkea": "mkea"},
                                "files": 2,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            event = {
                "usgs_id": "test-event",
                "rinex_dir": str(rinex_dir),
                "quake_utc": "2026-01-01T23:00:00Z",
                "lat": 13.0,
                "lon": 145.0,
                "magnitude": 7.8,
                "place": "test quake",
            }
            calls = []

            def fake_compute_tec(obs_path, *_args):
                calls.append(Path(obs_path).name)
                idx = pd.date_range("2026-01-02T00:00:00Z", periods=96, freq="15min")
                return pd.Series(np.sin(np.linspace(0, 2 * np.pi, len(idx))) * 0.01, index=idx)

            fake_ionosonde = types.SimpleNamespace(
                check_ionosonde_network=lambda *_args, **_kwargs: {
                    "ionosonde_detected": False,
                    "confirming_stations": 0,
                    "stations_with_data": 0,
                }
            )
            fake_dart = types.SimpleNamespace(
                check_dart_network=lambda *_args, **_kwargs: {
                    "tsunami_detected": False,
                    "confirming_buoys": 0,
                    "buoys_checked": 0,
                    "buoys_with_data": 0,
                }
            )

            with mock.patch.object(detector_runner, "decompress", side_effect=lambda p: Path(p)), \
                mock.patch.object(detector_runner, "compute_tec", side_effect=fake_compute_tec), \
                mock.patch.object(detector_runner, "compute_tec_for_constellation", return_value=None), \
                mock.patch.dict(
                    sys.modules,
                    {"ionosonde_checker": fake_ionosonde, "dart_checker": fake_dart},
                ):
                prediction = detector_runner.run_event(event, kp_override=0.0)

            self.assertIn("guam", prediction["stations_processed"])
            self.assertIn("mkea", prediction["stations_processed"])
            self.assertIn("gvim0020.26o.Z", calls)


class RetroactiveReprocessTests(unittest.TestCase):
    def test_queue_retroactive_reprocess_preserves_completed_result_until_download(self):
        event = {
            "usgs_id": "usgs-retro",
            "status": "scored",
            "rinex_downloaded": True,
            "detector_run": True,
            "scored": True,
            "prediction": {"detected": True, "run_utc": "2026-05-24T00:00:00+00:00"},
            "score": {"usgs_id": "usgs-retro", "outcome": "TRUE_POSITIVE"},
        }

        retroactive_rinex.queue_retroactive_reprocess(
            event,
            "new stations on CDDIS: GUAM",
            {"stations": ["guam"], "n_stations": 1},
        )

        self.assertEqual(event["status"], "scored")
        self.assertTrue(event["rinex_downloaded"])
        self.assertTrue(event["detector_run"])
        self.assertTrue(event["scored"])
        self.assertEqual(event["prediction"]["detected"], True)
        self.assertEqual(event["score"]["outcome"], "TRUE_POSITIVE")
        self.assertTrue(event["retroactive_pending"])

    def test_reset_event_for_reprocess_does_not_delete_running_log_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                Path("running_log.json").write_text(
                    json.dumps(
                        {
                            "scored_events": [
                                {"usgs_id": "usgs-retro", "outcome": "TRUE_POSITIVE"}
                            ],
                            "summary": {"total_scored": 1},
                        }
                    ),
                    encoding="utf-8",
                )
                rinex_downloader.reset_event_for_reprocess(
                    {
                        "usgs_id": "usgs-retro",
                        "prediction": {"detected": True},
                        "score": {"outcome": "TRUE_POSITIVE"},
                    }
                )
                data = json.loads(Path("running_log.json").read_text(encoding="utf-8"))
            finally:
                os.chdir(old_cwd)

        self.assertEqual(len(data["scored_events"]), 1)
        self.assertEqual(data["scored_events"][0]["usgs_id"], "usgs-retro")

    def test_scorer_dedupes_by_detector_run_for_retro_scores(self):
        old_score = {"usgs_id": "usgs-retro", "detector_run_utc": "2026-05-24T00:00:00+00:00"}
        event = {
            "usgs_id": "usgs-retro",
            "detector_run_utc": "2026-05-25T00:00:00+00:00",
            "prediction": {"run_utc": "2026-05-25T00:00:00+00:00"},
        }

        self.assertFalse(scorer._is_already_scored(event, [old_score]))
        self.assertTrue(
            scorer._is_already_scored(
                event,
                [
                    old_score,
                    {
                        "usgs_id": "usgs-retro",
                        "detector_run_utc": "2026-05-25T00:00:00+00:00",
                    },
                ],
            )
        )


if __name__ == "__main__":
    unittest.main()
