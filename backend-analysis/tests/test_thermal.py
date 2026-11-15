"""Tests for environmental thermal index and heat load metrics."""

import unittest
import numpy as np
import pandas as pd
from analysis.env_thermal import calculate_thi, categorize_thi_strain, calculate_thermal_load


class TestEnvironmentalThermal(unittest.TestCase):
    def test_calculate_thi_known_values(self):
        # 25°C and 50% RH -> expected THI ~ 71.775
        thi = calculate_thi(25.0, 50.0)
        self.assertAlmostEqual(thi, 71.775, places=2)

        # 20°C and 40% RH -> expected THI ~ 65.6 (comfort)
        thi_cool = calculate_thi(20.0, 40.0)
        self.assertTrue(thi_cool < 68.0)

    def test_categorize_thi_strain(self):
        self.assertEqual(categorize_thi_strain(65.0), "comfort")
        self.assertEqual(categorize_thi_strain(69.5), "mild_strain")
        self.assertEqual(categorize_thi_strain(75.0), "moderate_strain")
        self.assertEqual(categorize_thi_strain(82.0), "severe_strain")

        # Test vectorization with pandas Series
        series = pd.Series([60.0, 70.0, 74.0, 80.0])
        categories = categorize_thi_strain(series)
        self.assertEqual(list(categories), ["comfort", "mild_strain", "moderate_strain", "severe_strain"])

    def test_calculate_thermal_load(self):
        # 60 minutes of THI = 70.0 (2 units above threshold 68.0)
        # 60 minutes = 1 hour -> cumulative thermal load = 2.0 degree-hours
        times = pd.date_range("2026-07-25 08:00:00", periods=60, freq="1min", tz="UTC")
        df = pd.DataFrame({
            "cow_id": ["cow_01"] * 60,
            "ts_utc": times,
            "thi": [70.0] * 60,
        })
        load = calculate_thermal_load(df, threshold=68.0, window_hours=1)
        self.assertAlmostEqual(float(load.iloc[-1]), 2.0, places=2)


if __name__ == "__main__":
    unittest.main()
