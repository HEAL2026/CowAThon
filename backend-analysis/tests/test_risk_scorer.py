"""Tests for multimodal watch-list risk scoring and graceful degradation."""

import unittest
import numpy as np
import pandas as pd
from analysis.risk_scorer import MultimodalRiskScorer
from analysis.behavior import classify_posture_state, detect_stationary_hardware_candidate


class TestRiskScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = MultimodalRiskScorer()

    def test_healthy_baseline_cow(self):
        record = {
            "cow_id": "C01",
            "ts_utc": "2023-07-25T10:00:00Z",
            "cbt_c": 38.7,
            "indoor_thi": 64.0,
            "neck_imu_magnitude_std": 0.40,
            "rumination_proxy": 85.0,
            "milk_drop_pct": 0.5,
            "idling_fraction": 0.3,
        }
        res = self.scorer.score_record(record)
        self.assertLess(res["watch_risk_score"], 40.0)
        self.assertEqual(res["risk_category"], "baseline")
        self.assertAlmostEqual(res["confidence_score"], 1.0, delta=0.05)
        self.assertTrue(res["is_model_suggestion"])

    def test_distressed_priority_watch_cow(self):
        record = {
            "cow_id": "C02",
            "ts_utc": "2023-07-25T10:00:00Z",
            "cbt_c": 40.2, # Elevated fever / heat strain
            "indoor_thi": 76.0, # High environmental THI
            "neck_imu_magnitude_std": 0.08, # Lethargy
            "rumination_proxy": 15.0, # Depressed rumination
            "milk_drop_pct": 18.0, # Significant milk drop
            "idling_fraction": 0.8,
        }
        res = self.scorer.score_record(record)
        self.assertGreaterEqual(res["watch_risk_score"], 70.0)
        self.assertEqual(res["risk_category"], "priority_watch")
        self.assertTrue(any("CBT elevated" in f for f in res["contributing_factors"]))
        self.assertTrue(any("THI indicates heat stress" in f for f in res["contributing_factors"]))
        self.assertTrue(len(res["recommended_actions"]) > 0)

    def test_graceful_missing_modality_degradation(self):
        record = {
            "cow_id": "C03",
            "ts_utc": "2023-07-25T10:00:00Z",
            "cbt_c": None,
            "indoor_thi": 75.0,
            "neck_imu_magnitude_std": 0.35,
            "rumination_proxy": 45.0,
            "milk_drop_pct": 2.0,
        }
        res = self.scorer.score_record(record)
        self.assertIn("cbt", res["missing_modalities"])
        self.assertNotIn("cbt", res["modalities_present"])
        self.assertLess(res["confidence_score"], 0.8)
        self.assertGreaterEqual(res["watch_risk_score"], 0.0)
        self.assertLessEqual(res["watch_risk_score"], 100.0)

    def test_stationary_reference_hardware_tag(self):
        # Stress-test case: T13/T14 stationary reference tag
        # Collar and UWB present, but zero biological movement
        # No CBT bolus, no milk, no barn environment
        record = {
            "cow_id": "T13",
            "ts_utc": "2023-07-25T12:00:00Z",
            "neck_imu_magnitude_std": 0.095, # Real empirical post noise floor
            "uwb_x_m": 5.4,
            "uwb_y_m": 3.2,
            "cbt_c": None,
            "indoor_thi": None,
            "milk_yield_kg": None,
            "lying": None,
        }

        # 1. Structural + kinetic detection identifies stationary reference hardware
        df_rec = pd.DataFrame([record])
        is_hw = detect_stationary_hardware_candidate(df_rec)
        posture = classify_posture_state(df_rec["neck_imu_magnitude_std"], is_stationary_hardware=is_hw)
        self.assertEqual(posture.iloc[0], "stationary_hardware")

        # 2. Risk scoring drops confidence severely and reports missing channels
        res = self.scorer.score_record(record)
        self.assertLess(res["confidence_score"], 0.50)
        self.assertIn("cbt", res["missing_modalities"])
        self.assertIn("indoor_env", res["missing_modalities"])
        self.assertIn("milk_yield", res["missing_modalities"])
        self.assertTrue(res["is_model_suggestion"])


if __name__ == "__main__":
    unittest.main()
