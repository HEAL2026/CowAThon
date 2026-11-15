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
        act = pd.Series([0.02, 0.15])
        states = classify_posture_state(act, resting_threshold=0.08)
        self.assertEqual(list(states), ["resting", "active"])

    def test_rumination_proxy(self):
        df = pd.DataFrame({"activity_index": [0.035, 0.20]})
        rum = calculate_rumination_proxy(df)
        self.assertAlmostEqual(rum.iloc[0], 100.0, delta=1.0)
        self.assertAlmostEqual(rum.iloc[1], 0.0, delta=0.1)

    def test_behavior_anomaly_score(self):
        df = pd.DataFrame({
            "rumination_proxy": [10.0, 80.0],
            "activity_index": [0.005, 0.04],
        })
        anom = calculate_behavior_anomaly_score(df)
        self.assertGreater(anom.iloc[0], 20.0)
        self.assertAlmostEqual(anom.iloc[1], 0.0, delta=1.0)

    def test_validate_behavior_against_ground_truth(self):
        # Unlabeled window
        df_unlabeled = pd.DataFrame({"activity_index": [0.02, 0.1]})
        res_unlabeled = validate_behavior_against_ground_truth(df_unlabeled)
        self.assertFalse(res_unlabeled["has_ground_truth_labels"])

        # Labeled window (e.g. mode 7 = lying, mode 1 = walking)
        df_labeled = pd.DataFrame({
            "behavior_mode": [7, 7, 1, 2],
            "behavior_mode_name": ["lying", "lying", "walking", "standing"],
            "posture_state": ["resting", "resting", "active", "active"],
            "lying": [1, 1, 0, 0],
        })
        res_labeled = validate_behavior_against_ground_truth(df_labeled)
        self.assertTrue(res_labeled["has_ground_truth_labels"])
        self.assertEqual(res_labeled["n_labeled_rows"], 4)
        self.assertEqual(res_labeled["ankle_sensor_ground_truth_concordance"], 1.0)
        self.assertEqual(res_labeled["imu_posture_model"]["accuracy"], 1.0)
        self.assertEqual(res_labeled["imu_posture_model"]["f1"], 1.0)


if __name__ == "__main__":
    unittest.main()
