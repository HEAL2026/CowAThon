"""Unit tests for all external farm system mock adapters in apis.adapters."""

import unittest
from apis.adapters.bolus import MockCbtBolusAdapter
from apis.adapters.climate import MockBarnClimateAdapter
from apis.adapters.collar import MockCollarImuAdapter
from apis.adapters.herd import MockHerdManagementAdapter
from apis.adapters.location import MockUwbLocationAdapter
from apis.adapters.milking import MockMilkingParlorAdapter
from apis.adapters.pedometer import MockAnklePedometerAdapter
from apis.adapters.weather import MockWeatherStationAdapter


class TestMockAdapters(unittest.TestCase):
    def test_milking_parlor_adapter(self):
        adapter = MockMilkingParlorAdapter(is_attached=True)
        self.assertEqual(adapter.metadata.system_category, "milking")
        self.assertTrue(adapter.metadata.is_animal_level)

        records = adapter.fetch_window(
            start_utc="2023-07-25T00:00:00Z",
            end_utc="2023-07-26T00:00:00Z",
            cow_ids=["C01", "C02"],
        )
        self.assertGreater(len(records), 0)
        for r in records:
            self.assertIn(r.cow_id, ["C01", "C02"])
            self.assertIn("milk_yield_kg", r.values)
            self.assertIn("dim", r.values)
            self.assertTrue(r.is_synthetic)
            self.assertIn("milk_yield_kg_is_imputed", r.to_dict())

        # Detached returns empty list
        adapter.detach()
        self.assertEqual(adapter.fetch_window("2023-07-25T00:00:00Z", "2023-07-26T00:00:00Z"), [])

    def test_bolus_cbt_adapter(self):
        adapter = MockCbtBolusAdapter(is_attached=True)
        self.assertEqual(adapter.metadata.system_category, "bolus_temperature")

        records = adapter.fetch_window(
            start_utc="2023-07-25T14:00:00Z",
            end_utc="2023-07-25T14:10:00Z",
            cow_ids=["C01"],
        )
        self.assertGreater(len(records), 0)
        for r in records:
            self.assertEqual(r.cow_id, "C01")
            self.assertIn("cbt_c", r.values)
            self.assertGreater(r.values["cbt_c"], 37.0)
            self.assertLess(r.values["cbt_c"], 41.5)
            self.assertTrue(r.is_synthetic)

    def test_climate_adapter_farm_level(self):
        adapter = MockBarnClimateAdapter(is_attached=True)
        self.assertFalse(adapter.metadata.is_animal_level)

        records = adapter.fetch_window(
            start_utc="2023-07-25T14:00:00Z",
            end_utc="2023-07-25T14:05:00Z",
        )
        self.assertGreater(len(records), 0)
        for r in records:
            self.assertIsNone(r.cow_id)  # Farm-level invariant
            self.assertIn("indoor_temp_c", r.values)
            self.assertIn("indoor_rh_pct", r.values)
            self.assertIn("indoor_thi", r.values)
            self.assertTrue(r.is_synthetic)

    def test_ankle_pedometer_adapter(self):
        adapter = MockAnklePedometerAdapter(is_attached=True)
        records = adapter.fetch_window(
            start_utc="2023-07-25T14:00:00Z",
            end_utc="2023-07-25T14:05:00Z",
            cow_ids=["C03"],
        )
        self.assertGreater(len(records), 0)
        for r in records:
            self.assertEqual(r.cow_id, "C03")
            self.assertIn("lying", r.values)
            self.assertIn(r.values["lying"], (0, 1))

    def test_uwb_location_adapter(self):
        adapter = MockUwbLocationAdapter(is_attached=True)
        self.assertEqual(adapter.metadata.cost_profile.feasibility_tier.value, "high_cost_specialized")

        # Regular pen hour (e.g. 14:00 UTC)
        records_pen = adapter.fetch_window(
            start_utc="2023-07-25T14:00:00Z",
            end_utc="2023-07-25T14:02:00Z",
            cow_ids=["C01"],
        )
        self.assertGreater(len(records_pen), 0)
        self.assertFalse(records_pen[0].values["out_of_pen"])
        self.assertIsNotNone(records_pen[0].values["uwb_x_m"])

        # Milking trip hour (09:00 UTC)
        records_milking = adapter.fetch_window(
            start_utc="2023-07-25T09:00:00Z",
            end_utc="2023-07-25T09:02:00Z",
            cow_ids=["C01"],
        )
        self.assertTrue(records_milking[0].values["out_of_pen"])
        self.assertIsNone(records_milking[0].values["uwb_x_m"])

    def test_collar_imu_adapter(self):
        adapter = MockCollarImuAdapter(is_attached=True)
        records = adapter.fetch_window(
            start_utc="2023-07-25T14:00:00Z",
            end_utc="2023-07-25T14:03:00Z",
            cow_ids=["C05"],
        )
        self.assertGreater(len(records), 0)
        for r in records:
            self.assertEqual(r.cow_id, "C05")
            self.assertIn("neck_imu_magnitude_mean", r.values)
            self.assertIn("neck_imu_magnitude_std", r.values)
            self.assertIn("collar_pressure_hpa", r.values)

    def test_weather_station_adapter_farm_level(self):
        adapter = MockWeatherStationAdapter(is_attached=True)
        self.assertFalse(adapter.metadata.is_animal_level)

        records = adapter.fetch_window(
            start_utc="2023-07-25T12:00:00Z",
            end_utc="2023-07-25T12:15:00Z",
        )
        self.assertGreater(len(records), 0)
        for r in records:
            self.assertIsNone(r.cow_id)
            self.assertIn("outdoor_temp_c", r.values)
            self.assertIn("outdoor_solar_wm2", r.values)

    def test_herd_management_adapter(self):
        adapter = MockHerdManagementAdapter(is_attached=True)
        records = adapter.fetch_window(
            start_utc="2023-07-25T00:00:00Z",
            end_utc="2023-07-26T00:00:00Z",
            cow_ids=["C02"],
        )
        self.assertGreater(len(records), 0)
        for r in records:
            self.assertEqual(r.cow_id, "C02")
            self.assertIn("parity", r.values)
            self.assertIn("days_in_milk", r.values)
            self.assertIn("reproductive_status", r.values)


if __name__ == "__main__":
    unittest.main()
