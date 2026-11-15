"""Tests for behavioral metrics and IMU processing."""

import unittest
import numpy as np
import pandas as pd
from analysis.behavior import (
    calculate_activity_index,
    classify_posture_state,
    calculate_rumination_proxy,
    calculate_behavior_anomaly_score,
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
        # Resting activity near 0.035 g yields maximum rumination proxy
        df = pd.DataFrame({"activity_index": [0.035, 0.20]})
        rum = calculate_rumination_proxy(df)
        self.assertAlmostEqual(rum.iloc[0], 100.0, delta=1.0)
        self.assertAlmostEqual(rum.iloc[1], 0.0, delta=0.1)

    def test_behavior_anomaly_score(self):
        # Depressed rumination (< 40) + extreme lethargy (< 0.015)
        df = pd.DataFrame({
            "rumination_proxy": [10.0, 80.0],
            "activity_index": [0.005, 0.04],
        })
        anom = calculate_behavior_anomaly_score(df)
        self.assertGreater(anom.iloc[0], 20.0)
        self.assertAlmostEqual(anom.iloc[1], 0.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
