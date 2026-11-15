"""Unit tests for base data models and contracts in apis.base."""

import unittest
from apis.base import (
    AdapterHealth,
    CostProfile,
    FeasibilityTier,
    HealthStatus,
    ObservationRecord,
    SystemMetadata,
)


class TestBaseModels(unittest.TestCase):
    def test_observation_record_valid_animal(self):
        rec = ObservationRecord(
            cow_id="C01",
            ts_utc="2023-07-25T14:00:00Z",
            values={"cbt_c": 38.9},
            imputation_flags={"cbt_c": False},
            age_seconds={"cbt_c": 0.0},
            is_synthetic=True,
        )
        d = rec.to_dict()
        self.assertEqual(d["cow_id"], "C01")
        self.assertEqual(d["ts_utc"], "2023-07-25T14:00:00Z")
        self.assertEqual(d["cbt_c"], 38.9)
        self.assertFalse(d["cbt_c_is_imputed"])
        self.assertEqual(d["cbt_c_age_s"], 0.0)
        self.assertTrue(d["is_synthetic"])

    def test_observation_record_valid_farm_level(self):
        # Farm-level record: cow_id must be None
        rec = ObservationRecord(
            cow_id=None,
            ts_utc="2023-07-25T14:00:00Z",
            values={"indoor_thi": 72.4},
            imputation_flags={"indoor_thi": True},
            age_seconds={"indoor_thi": 120.0},
            is_synthetic=True,
        )
        d = rec.to_dict()
        self.assertIsNone(d["cow_id"])
        self.assertEqual(d["indoor_thi"], 72.4)
        self.assertTrue(d["indoor_thi_is_imputed"])
        self.assertEqual(d["indoor_thi_age_s"], 120.0)

    def test_observation_record_invalid_ts(self):
        # Non-Z or naive timestamp must fail validation
        with self.assertRaises(ValueError):
            ObservationRecord(
                cow_id="C01",
                ts_utc="2023-07-25 14:00:00",  # missing T and Z
                values={"cbt_c": 38.9},
            )

    def test_observation_record_invalid_cow_id_type(self):
        with self.assertRaises(TypeError):
            ObservationRecord(
                cow_id=123,  # type: ignore - must be str or None
                ts_utc="2023-07-25T14:00:00Z",
                values={"cbt_c": 38.9},
            )

    def test_cost_profile(self):
        cost = CostProfile(
            annual_cost_per_head_usd=35.0,
            hardware_setup_cost_usd=1600.0,
            feasibility_tier=FeasibilityTier.RECOMMENDED,
            recommended_min_herd_size=30,
            roi_summary="High ROI",
        )
        d = cost.to_dict()
        self.assertEqual(d["annual_cost_per_head_usd"], 35.0)
        self.assertEqual(d["feasibility_tier"], "recommended")

    def test_health_status(self):
        health = AdapterHealth(
            adapter_id="test_adapter",
            status=HealthStatus.MOCKED,
            is_attached=True,
            is_healthy=True,
            is_synthetic=True,
            message="Ready",
        )
        d = health.to_dict()
        self.assertEqual(d["status"], "mocked")
        self.assertTrue(d["is_attached"])
        self.assertTrue(d["is_synthetic"])


if __name__ == "__main__":
    unittest.main()
