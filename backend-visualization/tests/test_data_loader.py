"""
Unit tests for visualization data_loader real ingestion and fixture fallback.
Verifies cwd-independent path resolution, benchmark protocol conformity, and watch-list ingestion.
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in [REPO_ROOT / "backend-visualization", REPO_ROOT / "backend-cleaning", REPO_ROOT / "apis"]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from visualization.data_loader import (
    locate_joined_table,
    get_sidecar_metadata,
    load_raw_table_records,
    get_cow_timeseries_data,
    get_barn_overview_data,
    get_benchmarks_data,
    get_watch_list_data,
    REPO_ROOT,
)


class TestDataLoader(unittest.TestCase):

    def test_locate_joined_returns_none_or_path(self):
        p = locate_joined_table()
        if p is not None:
            self.assertTrue(p.is_file())

    def test_locate_joined_cwd_independence(self):
        """Verify locate_joined_table resolves identically regardless of current working directory."""
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                p_from_tmp = locate_joined_table()
                # If joined table exists at repo root, it must resolve from tmpdir
                canonical = REPO_ROOT / "backend-cleaning" / "data" / "processed" / "joined_1min.parquet"
                if canonical.is_file():
                    self.assertIsNotNone(p_from_tmp)
                    self.assertEqual(p_from_tmp.resolve(), canonical.resolve())
            finally:
                os.chdir(original_cwd)

    def test_sidecar_metadata_fallback(self):
        meta = get_sidecar_metadata(Path("nonexistent.parquet"))
        self.assertIn("cadence", meta)

    def test_timeseries_fallback_when_offline(self):
        points, is_synth = get_cow_timeseries_data("C01", days=3)
        self.assertIsInstance(is_synth, bool)
        self.assertGreater(len(points), 0)
        first_pt = points[0]
        self.assertIn("cbt_c", first_pt)
        self.assertIn("daily_milk_yield_kg", first_pt)

    def test_timeseries_with_real_records(self):
        mock_real_records = [
            {
                "cow_id": "C01",
                "ts_utc": "2023-07-28T14:00:00Z",
                "cbt_c": 39.85,
                "cbt_c_is_imputed": False,
                "cbt_c_age_s": 0.0,
                "neck_imu_magnitude_mean": 1.25,
                "neck_imu_magnitude_mean_is_imputed": False,
                "milk_yield_kg": 24.5,
                "milk_yield_kg_is_imputed": False,
                "milk_yield_kg_age_s": 7200.0,
                "lying": 1,
                "indoor_thi": 74.5,
                "indoor_thi_is_imputed": False,
                "out_of_pen": False,
            }
        ]
        points, is_synth = get_cow_timeseries_data("C01", custom_records=mock_real_records)
        self.assertFalse(is_synth)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["cbt_c"], 39.85)
        self.assertEqual(points[0]["daily_milk_yield_kg"], 24.5)
        self.assertEqual(points[0]["milk_yield_kg_age_s"], 7200.0)

    def test_barn_overview_fallback_when_offline(self):
        cows, env, is_synth = get_barn_overview_data()
        self.assertIsInstance(is_synth, bool)
        self.assertIn(len(cows), [10, 16])
        self.assertIn("indoor_thi", env)

    def test_barn_overview_with_real_records(self):
        mock_real_records = [
            {
                "cow_id": f"C{i:02d}",
                "ts_utc": "2023-07-28T14:00:00Z",
                "uwb_x_m": 12.0 + i,
                "uwb_y_m": 5.0,
                "lying": 1 if i % 2 == 0 else 0,
                "cbt_c": 38.8,
                "indoor_thi": 73.0,
                "indoor_temp_c": 25.0,
                "indoor_rh_pct": 60.0,
                "out_of_pen": False,
            }
            for i in range(1, 8)
        ]
        cows, env, is_synth = get_barn_overview_data(custom_records=mock_real_records)
        self.assertFalse(is_synth)
        self.assertEqual(len(cows), 7)
        self.assertEqual(env["indoor_thi"], 73.0)

    def test_get_benchmarks_data_protocol_and_fields(self):
        payload, is_synth = get_benchmarks_data()
        self.assertIsInstance(payload, dict)
        self.assertIsInstance(is_synth, bool)
        self.assertIn("dataset", payload)
        self.assertIn("evaluation_protocol", payload)
        # Valid protocol prefixes
        proto = payload["evaluation_protocol"]
        valid_prefixes = ["group_kfold", "leave_one_animal_out", "insufficient_animals_for_cv"]
        self.assertTrue(any(proto.startswith(p) for p in valid_prefixes), f"Unexpected protocol: {proto}")
        self.assertIn("cv_unavailable", payload)
        self.assertIn("baselines", payload)
        self.assertIn("multimodal_model", payload)

    def test_get_watch_list_data_non_clinical(self):
        items, is_synth = get_watch_list_data()
        self.assertIsInstance(items, list)
        self.assertIsInstance(is_synth, bool)
        self.assertGreater(len(items), 0)
        for item in items:
            self.assertIn("cow_id", item)
            self.assertIn(item["risk_category"], ["priority_watch", "moderate_watch", "baseline"])
            self.assertTrue(item["is_model_suggestion"])
            self.assertIn("confidence", item)
            self.assertIn("modalities_present", item)
            self.assertIn("modalities_missing", item)


if __name__ == "__main__":
    unittest.main()
