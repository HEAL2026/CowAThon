"""
Unit tests for AgTech commercial mock APIs and cleaned mastitis benchmark dataset.
"""

import os
import json
import unittest

from visualization.mock_apis import (
    ALL_MOCK_APIS,
    get_mock_nedap_collar_response,
    get_mock_allflex_sensehub_response,
    get_mock_munters_thi_response,
    get_mock_tomorrow_io_weather_response,
    get_mock_vas_pulse_response,
    map_vendor_telemetry_to_canonical_row,
)


class TestMockAgTechAPIs(unittest.TestCase):

    def test_mock_apis_registry(self):
        self.assertEqual(len(ALL_MOCK_APIS), 5)
        for api in ALL_MOCK_APIS:
            self.assertIn("vendor", api)
            self.assertIn("product_name", api)
            self.assertIn("category", api)
            self.assertIn("base_url", api)
            self.assertIn("cost_per_head_usd_year", api)

    def test_nedap_collar_schema(self):
        resp = get_mock_nedap_collar_response("C01", "T01")
        self.assertEqual(resp["status"], "success")
        self.assertTrue(resp["is_synthetic"])
        data = resp["data"]
        self.assertEqual(data["animal_id"], "C01")
        self.assertIn("kinetic_activity_mean", data["last_interval_metrics_1m"])

    def test_allflex_sensehub_schema(self):
        resp = get_mock_allflex_sensehub_response("C01")
        self.assertTrue(resp["is_synthetic"])
        self.assertIn("health_index", resp["metrics"])
        self.assertIn("panting_motion_detected", resp["metrics"])

    def test_munters_thi_schema(self):
        resp = get_mock_munters_thi_response("main_barn_01")
        self.assertTrue(resp["is_synthetic"])
        climate = resp["climate_metrics"]
        self.assertEqual(climate["indoor_thi"], 74.2)
        self.assertIn("ventilation_fans_stage", resp["actuators_state"])

    def test_tomorrow_io_weather_schema(self):
        resp = get_mock_tomorrow_io_weather_response(40.08, -88.24)
        self.assertTrue(resp["is_synthetic"])
        cond = resp["current_conditions"]
        self.assertEqual(cond["outdoor_temp_c"], 28.5)
        self.assertEqual(cond["calculated_outdoor_thi"], 76.8)

    def test_vas_pulse_schema(self):
        resp = get_mock_vas_pulse_response("C01")
        self.assertTrue(resp["is_synthetic"])
        self.assertEqual(resp["cow_id"], "C01")
        self.assertIn("daily_milk_weight_kg", resp["production"])

    def test_map_vendor_telemetry_to_canonical(self):
        ts = "2023-07-28T14:00:00Z"
        nedap = get_mock_nedap_collar_response("C01", "T01", ts)
        munters = get_mock_munters_thi_response("main_barn_01", ts)
        weather = get_mock_tomorrow_io_weather_response(40.08, -88.24, ts)
        vas = get_mock_vas_pulse_response("C01", ts)

        canonical = map_vendor_telemetry_to_canonical_row(
            cow_id="C01",
            ts_utc=ts,
            nedap_data=nedap,
            munters_data=munters,
            weather_data=weather,
            vas_data=vas,
        )

        self.assertEqual(canonical["cow_id"], "C01")
        self.assertEqual(canonical["ts_utc"], ts)
        self.assertEqual(canonical["indoor_thi"], 74.2)
        self.assertEqual(canonical["neck_imu_magnitude_mean"], 1.15)
        self.assertEqual(canonical["milk_yield_kg"], 21.8)
        self.assertEqual(canonical["outdoor_temp_c"], 28.5)
        self.assertFalse(canonical["neck_imu_magnitude_mean_is_imputed"])
        self.assertFalse(canonical["milk_yield_kg_is_imputed"])

    def test_cleaned_benchmarks_exist(self):
        json_path = "backend-visualization/data/benchmarks/farm_housing_mastitis_risk.json"
        csv_path = "backend-visualization/data/benchmarks/farm_housing_mastitis_risk.csv"
        self.assertTrue(os.path.exists(json_path), "Missing cleaned benchmark JSON")
        self.assertTrue(os.path.exists(csv_path), "Missing cleaned benchmark CSV")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["farm_count"], 88)
            self.assertIn("farms", data)
            first_farm = data["farms"][0]
            self.assertIn("housing_type", first_farm)
            self.assertIn("cm_rate_per_1000_cow_days", first_farm)


if __name__ == "__main__":
    unittest.main()
