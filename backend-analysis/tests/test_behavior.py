"""Tests for behavioral metrics and IMU processing."""

import unittest
import numpy as np
import pandas as pd
from analysis.behavior import (
    calculate_activity_index,
    classify_posture_state,
    calculate_rumination_proxy,
    calculate_behavior_anomaly_score,
    validate_behavior_against_ground_truth,
    detect_stationary_hardware_candidate,
)


class TestBehavior(unittest.TestCase):
    def test_activity_index(self):
        df = pd.DataFrame({
            "acc_x_std": [0.03, 0.0],
            "acc_y_std": [0.04, 0.0],
            "acc_z_std": [0.0, 0.0],
        })
        act = calculate_activity_index(df)
        self.assertAlmostEqual(act.iloc[0], 0.05, places=3)
        self.assertAlmostEqual(act.iloc[1], 0.0, places=3)

    def test_classify_posture_state(self):
        # Calibrated against real MMCows distributions (resting < 0.20, active >= 0.20)
        act = pd.Series([0.10, 0.45, 0.12])
        is_hw = pd.Series([False, False, True])
        states = classify_posture_state(act, resting_threshold=0.20, is_stationary_hardware=is_hw)
        self.assertEqual(list(states), ["resting", "active", "stationary_hardware"])

    def test_classify_posture_state_with_classifier(self):
        # Classifier state mapping takes precedence over IMU threshold
        act = pd.Series([0.45, 0.10, 0.30])
        # By threshold: active, resting, active.
        # But classifier says: lying (7 -> resting), feeding (1 -> active), resting (5 -> resting)
        b_names = pd.Series(["lying", "feeding", "resting"])
        states = classify_posture_state(act, behavior_name_col=b_names)
        self.assertEqual(list(states), ["resting", "active", "resting"])

        # Also supports integer codes: 7 (lying) -> resting, 3 (walking) -> active
        b_codes = pd.Series([7, 3, 5])
        states_code = classify_posture_state(act, behavior_col=b_codes)
        self.assertEqual(list(states_code), ["resting", "active", "resting"])

    def test_detect_stationary_hardware_candidate(self):
        # T13 tag on post: no CBT, no milk, no lying, static UWB, low median IMU (0.095)
        df_t13 = pd.DataFrame({
            "cow_id": ["T13"] * 10,
            "neck_imu_magnitude_std": [0.09, 0.095, 0.10, 0.08, 0.09, 0.11, 0.095, 0.085, 0.10, 0.09],
            "uwb_x_m": [5.1, 5.12, 5.09, 5.11, 5.10, 5.11, 5.08, 5.12, 5.10, 5.09],
            "uwb_y_m": [3.2, 3.21, 3.19, 3.20, 3.22, 3.19, 3.20, 3.21, 3.20, 3.19],
            "cbt_c": [np.nan] * 10,
            "milk_yield_kg": [np.nan] * 10,
            "lying": [np.nan] * 10,
        })
        is_hw_13 = detect_stationary_hardware_candidate(df_t13)
        self.assertTrue(is_hw_13.all())

        # T14 tag on post: empirical MMCows values (median IMU 0.151, position std ~0.32m)
        df_t14 = pd.DataFrame({
            "cow_id": ["T14"] * 10,
            "neck_imu_magnitude_std": [0.14, 0.151, 0.16, 0.15, 0.152, 0.149, 0.155, 0.148, 0.151, 0.153],
            "uwb_x_m": [5.1, 5.3, 4.9, 5.2, 5.0, 5.1, 4.8, 5.3, 5.1, 5.0],
            "uwb_y_m": [3.2, 3.4, 3.0, 3.3, 3.1, 3.2, 2.9, 3.4, 3.2, 3.1],
            "cbt_c": [np.nan] * 10,
            "milk_yield_kg": [np.nan] * 10,
            "lying": [np.nan] * 10,
        })
        is_hw_14 = detect_stationary_hardware_candidate(df_t14)
        self.assertTrue(is_hw_14.all())

        # Live cow C01: has CBT, milk, lying, high position variance
        df_cow = pd.DataFrame({
            "cow_id": ["C01"] * 10,
            "neck_imu_magnitude_std": [0.35, 0.45, 0.50, 0.28, 0.40, 0.60, 0.45, 0.38, 0.52, 0.48],
            "uwb_x_m": [2.0, 5.0, 8.0, 11.0, 14.0, 12.0, 9.0, 6.0, 4.0, 3.0],
            "uwb_y_m": [1.0, 3.0, 6.0, 9.0, 7.0, 5.0, 3.0, 2.0, 1.5, 1.2],
            "cbt_c": [38.8] * 10,
            "milk_yield_kg": [31.5] * 10,
            "lying": [0, 0, 1, 1, 0, 0, 1, 0, 0, 0],
        })
        is_cow_hw = detect_stationary_hardware_candidate(df_cow)
        self.assertFalse(is_cow_hw.any())

    def test_rumination_proxy(self):
        # Rumination peaks in live resting band near 0.12 m/s²
        df = pd.DataFrame({"activity_index": [0.12, 0.65]})
        rum = calculate_rumination_proxy(df)
        self.assertAlmostEqual(rum.iloc[0], 100.0, delta=2.0)
        self.assertAlmostEqual(rum.iloc[1], 0.0, delta=0.1)

    def test_rumination_proxy_with_classifier(self):
        # Conflicting active behavior (e.g. feeding, walking) suppresses rumination proxy
        df_active = pd.DataFrame({
            "activity_index": [0.12],  # In resting band, but behavior classifier identifies feeding
            "behavior_name": ["feeding"],
            "prob": [0.95],
        })
        rum_suppressed = calculate_rumination_proxy(df_active)
        self.assertLess(rum_suppressed.iloc[0], 25.0)

        # Classified ruminating state elevates score proportionally to prob
        df_rum = pd.DataFrame({
            "activity_index": [0.30],  # Slightly outside resting band, but classified as ruminating
            "behavior_name": ["ruminating"],
            "prob": [0.90],
        })
        rum_boosted = calculate_rumination_proxy(df_rum)
        self.assertGreaterEqual(rum_boosted.iloc[0], 90.0)

    def test_behavior_anomaly_score(self):
        df = pd.DataFrame({
            "rumination_proxy": [10.0, 80.0],
            "activity_index": [0.04, 0.35],
        })
        anom = calculate_behavior_anomaly_score(df)
        self.assertGreater(anom.iloc[0], 20.0)
        self.assertAlmostEqual(anom.iloc[1], 0.0, delta=1.0)

    def test_validate_behavior_against_ground_truth(self):
        df_unlabeled = pd.DataFrame({"activity_index": [0.10, 0.40]})
        res_unlabeled = validate_behavior_against_ground_truth(df_unlabeled)
        self.assertFalse(res_unlabeled["has_ground_truth_labels"])

        df_labeled = pd.DataFrame({
            "behavior_mode": [7, 7, 1, 2],
            "behavior_mode_name": ["lying", "lying", "walking", "standing"],
            "posture_state": ["resting", "resting", "active", "active"],
            "lying": [1, 1, 0, 0],
            "behavior": [7, 7, 1, 3],  # Classifier prediction
        })
        res_labeled = validate_behavior_against_ground_truth(df_labeled)
        self.assertTrue(res_labeled["has_ground_truth_labels"])
        self.assertEqual(res_labeled["n_labeled_rows"], 4)
        self.assertEqual(res_labeled["ankle_sensor_ground_truth_concordance"], 1.0)
        self.assertEqual(res_labeled["imu_posture_model"]["accuracy"], 1.0)
        self.assertEqual(res_labeled["imu_posture_model"]["f1"], 1.0)
        self.assertIn("behavior_classifier_ground_truth_concordance", res_labeled)
        clf_eval = res_labeled["behavior_classifier_ground_truth_concordance"]
        self.assertEqual(clf_eval["overall_accuracy"], 0.75)  # 3 of 4 correct
        self.assertEqual(clf_eval["lying_f1"], 1.0)
        self.assertEqual(clf_eval["n_compared"], 4)


if __name__ == "__main__":
    unittest.main()
