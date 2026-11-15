"""Unit tests for S5–S7: Cow-day features, tiered baselines, health index, and acute mastitis risk."""

import unittest
import tempfile
from pathlib import Path
import pandas as pd
import numpy as np

from analysis.fixtures import generate_synthetic_mmcows_data
from analysis.cow_day_features import aggregate_cow_day_features
from analysis.tiered_baselines import compute_tiered_baselines
from analysis.health_index import compute_health_index
from analysis.mastitis_risk import evaluate_acute_mastitis_risk
from analysis.pipeline import run_analysis_pipeline


class TestS5S7Pipeline(unittest.TestCase):
    def setUp(self):
        self.df = generate_synthetic_mmcows_data(n_cows=4, n_minutes=60, seed=42)

    def test_aggregate_cow_day_features(self):
        day_df = aggregate_cow_day_features(self.df)
        self.assertEqual(len(day_df), 4)
        self.assertIn("cbt_mean", day_df.columns)
        self.assertIn("daily_milk_yield_kg", day_df.columns)
        self.assertIn("lying_time_min", day_df.columns)
        self.assertIn("lying_bouts_count", day_df.columns)
        self.assertIn("rumination_proxy_mean", day_df.columns)

        # Check values are populated and reasonable
        c01_row = day_df[day_df["cow_id"] == "C01"].iloc[0]
        self.assertGreater(c01_row["cbt_mean"], 38.0)
        self.assertGreater(c01_row["daily_milk_yield_kg"], 20.0)

    def test_tiered_baselines_cold_start_progression(self):
        current_day = aggregate_cow_day_features(self.df)

        # 1. Zero history -> cohort or literature prior
        empty_history = pd.DataFrame()
        baselines_cold = compute_tiered_baselines(empty_history, current_day)
        c01_cold = baselines_cold["C01"]
        self.assertIn(c01_cold["primary_baseline_tier"], ["cohort", "literature_prior"])
        self.assertLessEqual(c01_cold["overall_baseline_confidence"], 0.45)
        self.assertGreater(c01_cold["threshold_multiplier"], 1.4)

        # 2. 3 days of history -> blended tier
        history_3d = pd.concat([current_day] * 3, ignore_index=True)
        baselines_blended = compute_tiered_baselines(history_3d, current_day)
        c01_blended = baselines_blended["C01"]
        self.assertEqual(c01_blended["primary_baseline_tier"], "blended")
        self.assertGreater(c01_blended["overall_baseline_confidence"], 0.55)

        # 3. 8 days of history -> own_history tier
        history_8d = pd.concat([current_day] * 8, ignore_index=True)
        baselines_own = compute_tiered_baselines(history_8d, current_day)
        c01_own = baselines_own["C01"]
        self.assertEqual(c01_own["primary_baseline_tier"], "own_history")
        self.assertGreaterEqual(c01_own["overall_baseline_confidence"], 0.90)
        self.assertLessEqual(c01_own["threshold_multiplier"], 1.15)

    def test_health_index_computation(self):
        # Healthy cow: zero deviations
        healthy_base = {
            "metrics": {
                "cbt_mean": {"effective_z_score": 0.0},
                "rumination_proxy_mean": {"effective_z_score": 0.0},
                "lying_time_min": {"effective_z_score": 0.0},
                "activity_index_mean": {"effective_z_score": 0.0},
                "daily_milk_yield_kg": {"effective_z_score": 0.0},
            }
        }
        res_healthy = compute_health_index(healthy_base)
        self.assertEqual(res_healthy["health_index"], 100.0)
        self.assertEqual(res_healthy["vitality_tier"], "thriving")

        # Strained cow: elevated CBT, dropped rumination and yield
        strained_base = {
            "metrics": {
                "cbt_mean": {"effective_z_score": 2.2},
                "rumination_proxy_mean": {"effective_z_score": -2.0},
                "lying_time_min": {"effective_z_score": -1.5},
                "activity_index_mean": {"effective_z_score": -1.8},
                "daily_milk_yield_kg": {"effective_z_score": -2.5},
            }
        }
        res_strained = compute_health_index(strained_base)
        self.assertLess(res_strained["health_index"], 50.0)
        self.assertIn(res_strained["vitality_tier"], ["moderate_strain", "acute_attention"])

    def test_acute_mastitis_risk_and_autoflag(self):
        # Healthy cow: low risk, no auto flag
        normal_base = {
            "cow_id": "C01",
            "metrics": {
                "cbt_mean": {"effective_z_score": 0.1},
                "daily_milk_yield_kg": {"effective_z_score": 0.0},
                "lying_time_min": {"effective_z_score": 0.2},
                "conductivity_max": {"effective_z_score": 0.1},
                "scc_mean": {"effective_z_score": 0.0},
            }
        }
        res_normal = evaluate_acute_mastitis_risk(normal_base)
        self.assertLess(res_normal["mastitis_risk"], 40.0)
        self.assertIsNone(res_normal["auto_flag"])

        # Mastitis case: conductivity up, SCC up, milk yield dropped, CBT up
        acute_base = {
            "cow_id": "C02",
            "metrics": {
                "cbt_mean": {"effective_z_score": 2.6},
                "daily_milk_yield_kg": {"effective_z_score": -2.8},
                "lying_time_min": {"effective_z_score": -1.9},
                "conductivity_max": {"effective_z_score": 3.2},
                "scc_mean": {"effective_z_score": 3.0},
            }
        }
        res_acute = evaluate_acute_mastitis_risk(acute_base, risk_threshold=70.0)
        self.assertGreaterEqual(res_acute["mastitis_risk"], 70.0)
        self.assertIsNotNone(res_acute["auto_flag"])
        self.assertEqual(res_acute["auto_flag"]["flag_type"], "auto_mastitis_watch")
        self.assertEqual(res_acute["auto_flag"]["cow_id"], "C02")

    def test_pipeline_integration_with_s5_s7(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            result = run_analysis_pipeline(self.df, output_dir=out_path, n_cv_splits=4, seed=0)

            # Check cow_summaries contains S5-S7 fields
            c01 = result["cow_summaries"]["C01"]
            self.assertIn("health_index", c01)
            self.assertIn("vitality_tier", c01)
            self.assertIn("acute_mastitis_risk", c01)
            self.assertIn("baseline_tier", c01)
            self.assertIn("baseline_confidence", c01)

            # Check exported files
            self.assertTrue((out_path / "auto_flags.json").exists())
            self.assertTrue((out_path / "cow_day_features.parquet").exists())

    def test_optional_mendeley_physiology_and_composition_columns(self):
        # Create DataFrame with Mendeley 954f6g36sb/2 columns and without standard cbt_c / cbt
        df_ext = self.df.drop(columns=["cbt_c", "cbt"]).copy()
        df_ext["rectal_temp_c"] = 39.5
        df_ext["respiration_rate_bpm"] = 65.0
        df_ext["pulse_rate_bpm"] = 72.0
        df_ext["dmi_kg"] = 24.5
        df_ext["milk_fat_pct"] = 3.8
        df_ext["milk_protein_pct"] = 3.2
        df_ext["milk_lactose_pct"] = 4.8

        day_df = aggregate_cow_day_features(df_ext)
        self.assertEqual(len(day_df), 4)

        # Check rectal_temp_c fallback into cbt_mean
        c01 = day_df[day_df["cow_id"] == "C01"].iloc[0]
        self.assertEqual(c01["cbt_mean"], 39.5)
        self.assertEqual(c01["respiration_rate_bpm_mean"], 65.0)
        self.assertEqual(c01["pulse_rate_bpm_mean"], 72.0)
        self.assertEqual(c01["dmi_kg"], 24.5)
        self.assertEqual(c01["milk_fat_pct"], 3.8)
        self.assertEqual(c01["fat_pct"], 3.8)
        self.assertEqual(c01["milk_protein_pct"], 3.2)
        self.assertEqual(c01["protein_pct"], 3.2)
        self.assertEqual(c01["milk_lactose_pct"], 4.8)
        self.assertEqual(c01["lactose_pct"], 4.8)

        # Verify pipeline calculates cbt_strain_score from rectal_temp_c
        with tempfile.TemporaryDirectory() as tmpdir:
            res = run_analysis_pipeline(df_ext, output_dir=Path(tmpdir), n_cv_splits=4, seed=0)
            self.assertIn("cbt_strain_score", res["analyzed_df"].columns)
            self.assertGreater(res["analyzed_df"]["cbt_strain_score"].mean(), 0.0)


if __name__ == "__main__":
    unittest.main()
