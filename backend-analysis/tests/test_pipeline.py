"""Integration tests for end-to-end backend analysis pipeline."""

import unittest
import json
import tempfile
from pathlib import Path
import pandas as pd

from tests.fixtures import generate_synthetic_mmcows_data
from analysis.pipeline import run_analysis_pipeline


class TestPipelineIntegration(unittest.TestCase):
    def setUp(self):
        self.df = generate_synthetic_mmcows_data(n_cows=10, n_minutes=30, seed=42)

    def test_run_analysis_pipeline_and_export(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            result = run_analysis_pipeline(
                self.df,
                output_dir=out_path,
                n_cv_splits=5,
                seed=0,
            )

            # Check return structure
            self.assertIn("cow_summaries", result)
            self.assertIn("benchmarks", result)
            self.assertIn("analyzed_df", result)

            self.assertEqual(len(result["cow_summaries"]), 10)
            cow_01 = result["cow_summaries"]["C01"]
            self.assertIn("watch_risk_score", cow_01)
            self.assertIn("risk_category", cow_01)
            self.assertIn("confidence_score", cow_01)
            self.assertIn("metrics", cow_01)
            self.assertIn("contributing_factors", cow_01)
            self.assertIn("recommended_actions", cow_01)
            self.assertTrue(cow_01["is_model_suggestion"])

            # Verify exported files exist
            summary_file = out_path / "cow_risk_summary.json"
            benchmark_file = out_path / "benchmark_results.json"
            timeseries_file = out_path / "analyzed_timeseries.parquet"

            self.assertTrue(summary_file.exists())
            self.assertTrue(benchmark_file.exists())
            self.assertTrue(timeseries_file.exists())

            # Check schema sidecars exist and are valid
            ts_schema_file = out_path / "analyzed_timeseries.schema.json"
            day_schema_file = out_path / "cow_day_features.schema.json"
            self.assertTrue(ts_schema_file.exists())
            self.assertTrue(day_schema_file.exists())
            with open(ts_schema_file, "r", encoding="utf-8") as f:
                ts_schema = json.load(f)
            self.assertEqual(ts_schema["cadence"], "1m")
            self.assertIn("watch_risk_score", ts_schema["columns"])
            with open(day_schema_file, "r", encoding="utf-8") as f:
                day_schema = json.load(f)
            self.assertEqual(day_schema["cadence"], "1d")
            self.assertIn("cbt_mean", day_schema["columns"])

            # Validate JSON loads cleanly
            with open(summary_file, "r", encoding="utf-8") as f:
                loaded_summary = json.load(f)
            self.assertEqual(len(loaded_summary), 10)

            with open(benchmark_file, "r", encoding="utf-8") as f:
                loaded_benchmarks = json.load(f)
            self.assertIn("baselines", loaded_benchmarks)
            self.assertIn("multimodal_model", loaded_benchmarks)
            self.assertEqual(loaded_benchmarks["evaluation_protocol"], "group_kfold_5 (n=10)")

            # Validate Parquet file loads cleanly
            df_loaded = pd.read_parquet(timeseries_file)
            self.assertIn("watch_risk_score", df_loaded.columns)
            self.assertIn("indoor_thi", df_loaded.columns)
            self.assertIn("activity_index", df_loaded.columns)

    def test_pipeline_with_stationary_hardware_tag(self):
        # Mix 2 live cows with 1 stationary hardware tag (T14)
        cows_df = generate_synthetic_mmcows_data(n_cows=2, n_minutes=15, seed=7)
        t14_df = pd.DataFrame({
            "ts_utc": cows_df["ts_utc"][:15].values,
            "cow_id": ["T14"] * 15,
            "indoor_thi": [68.0] * 15,
            "cbt_c": [float("nan")] * 15,
            "neck_imu_magnitude_std": [0.151] * 15,
            "lying": [float("nan")] * 15,
            "uwb_x_m": [5.1] * 15,
            "uwb_y_m": [3.2] * 15,
            "milk_yield_kg": [float("nan")] * 15,
            "milk_drop_pct": [0.0] * 15,
            "out_of_pen": [False] * 15,
        })
        mixed_df = pd.concat([cows_df, t14_df], ignore_index=True)

        result = run_analysis_pipeline(mixed_df, n_cv_splits=2, seed=0)

        # Check summaries
        self.assertIn("T14", result["cow_summaries"])
        t14_summary = result["cow_summaries"]["T14"]
        self.assertTrue(t14_summary["metrics"]["is_stationary_hardware"])
        self.assertEqual(t14_summary["metrics"]["posture_state"], "stationary_hardware")

        # Check analyzed dataframe
        analyzed_df = result["analyzed_df"]
        t14_rows = analyzed_df[analyzed_df["cow_id"] == "T14"]
        self.assertTrue((t14_rows["posture_state"] == "stationary_hardware").all())
        self.assertTrue(t14_rows["is_stationary_hardware"].all())

    def test_pipeline_adaptive_splits_for_small_herd(self):
        # 4 cows with 5 requested splits should clamp to 4 folds without crashing
        cows_4_df = generate_synthetic_mmcows_data(n_cows=4, n_minutes=30, seed=10)
        result = run_analysis_pipeline(cows_4_df, n_cv_splits=5, seed=0)

        benchmarks = result["benchmarks"]
        self.assertFalse(benchmarks["cv_unavailable"])
        self.assertEqual(benchmarks["n_groups"], 4)
        self.assertEqual(benchmarks["n_splits"], 4)
        self.assertEqual(benchmarks["evaluation_protocol"], "leave_one_animal_out (n=4)")

    def test_pipeline_undersized_herd_cv_degradation(self):
        # 2 cows: below n=3 floor, skips CV and degrades confidence without crashing
        cows_2_df = generate_synthetic_mmcows_data(n_cows=2, n_minutes=30, seed=11)
        result = run_analysis_pipeline(cows_2_df, n_cv_splits=5, seed=0)

        benchmarks = result["benchmarks"]
        self.assertTrue(benchmarks["cv_unavailable"])
        self.assertEqual(benchmarks["n_splits"], 0)
        self.assertEqual(benchmarks["evaluation_protocol"], "insufficient_animals_for_cv (n=2)")
        self.assertIn("Need at least 3", benchmarks["cv_unavailable_reason"])

        # Confidence should be gracefully degraded
        c01_summary = result["cow_summaries"]["C01"]
        self.assertLessEqual(c01_summary["confidence_score"], 0.60)

    def test_pipeline_all_hardware_fixture(self):
        # Herd consisting entirely of hardware tags (zero live cows)
        t_df = pd.DataFrame({
            "ts_utc": pd.date_range("2023-07-25 08:00", periods=10, freq="min", tz="UTC"),
            "cow_id": ["T13"] * 5 + ["T14"] * 5,
            "indoor_thi": [68.0] * 10,
            "cbt_c": [float("nan")] * 10,
            "neck_imu_magnitude_std": [0.09] * 5 + [0.151] * 5,
            "lying": [float("nan")] * 10,
            "uwb_x_m": [5.1] * 10,
            "uwb_y_m": [3.2] * 10,
            "milk_yield_kg": [float("nan")] * 10,
            "milk_drop_pct": [0.0] * 10,
            "out_of_pen": [False] * 10,
        })
        result = run_analysis_pipeline(t_df, n_cv_splits=5, seed=0)
        benchmarks = result["benchmarks"]
        self.assertTrue(benchmarks["cv_unavailable"])
        self.assertEqual(benchmarks["n_groups"], 0)
        for cid in ["T13", "T14"]:
            self.assertEqual(result["cow_summaries"][cid]["metrics"]["posture_state"], "stationary_hardware")


if __name__ == "__main__":
    unittest.main()
