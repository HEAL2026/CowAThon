"""Unit tests for IntegrationRegistry in apis.registry."""

import unittest
from apis.base import (
    AdapterHealth,
    BaseAdapter,
    CostProfile,
    FeasibilityTier,
    HealthStatus,
    ObservationRecord,
    SystemMetadata,
)
from apis.registry import IntegrationRegistry, create_default_registry


class DummyAdapter(BaseAdapter):
    def __init__(self, adapter_id: str = "dummy_1", is_attached: bool = True) -> None:
        super().__init__(is_attached=is_attached)
        self._meta = SystemMetadata(
            adapter_id=adapter_id,
            name="Dummy Test System",
            vendor="DummyCorp",
            system_category="testing",
            signals=["test_signal"],
            cadence="1_min",
            is_animal_level=True,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=10.0,
                hardware_setup_cost_usd=500.0,
                feasibility_tier=FeasibilityTier.RECOMMENDED,
                recommended_min_herd_size=20,
                roi_summary="Quick test ROI",
            ),
        )

    @property
    def metadata(self) -> SystemMetadata:
        return self._meta

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            adapter_id=self._meta.adapter_id,
            status=HealthStatus.ATTACHED if self._is_attached else HealthStatus.DETACHED,
            is_attached=self._is_attached,
            is_healthy=self._is_attached,
            is_synthetic=True,
        )

    def fetch_window(self, start_utc: str, end_utc: str, cow_ids=None):
        if not self._is_attached:
            return []
        return [
            ObservationRecord(
                cow_id="C01",
                ts_utc=start_utc,
                values={"test_signal": 42.0},
                imputation_flags={"test_signal": False},
                age_seconds={"test_signal": 0.0},
                is_synthetic=True,
            )
        ]


class TestIntegrationRegistry(unittest.TestCase):
    def test_register_and_get(self):
        reg = IntegrationRegistry()
        adapter = DummyAdapter("sys_1")
        reg.register(adapter)
        self.assertEqual(len(reg.list_adapters()), 1)
        self.assertEqual(reg.get("sys_1"), adapter)

    def test_duplicate_registration_raises(self):
        reg = IntegrationRegistry()
        reg.register(DummyAdapter("sys_1"))
        with self.assertRaises(ValueError):
            reg.register(DummyAdapter("sys_1"))

    def test_attach_and_detach(self):
        reg = IntegrationRegistry()
        adapter = DummyAdapter("sys_1", is_attached=False)
        reg.register(adapter)
        self.assertFalse(adapter.is_attached)

        # Attach
        self.assertTrue(reg.attach("sys_1"))
        self.assertTrue(adapter.is_attached)
        self.assertIn(adapter, reg.list_attached_adapters())

        # Detach
        self.assertTrue(reg.detach("sys_1"))
        self.assertFalse(adapter.is_attached)
        self.assertNotIn(adapter, reg.list_attached_adapters())

    def test_feasibility_payload_matches_schema(self):
        reg = create_default_registry(attach_all=False)
        payload = reg.to_feasibility_payload()
        self.assertIn("systems", payload)
        self.assertGreaterEqual(len(payload["systems"]), 8)

        # Check fields match backend-visualization/CONTRACT.md §3.5
        first = payload["systems"][0]
        required_keys = [
            "adapter_id",
            "name",
            "vendor",
            "attached",
            "cadence",
            "annual_cost_per_head_usd",
            "hardware_setup_cost_usd",
            "feasibility_tier",
            "signals",
            "is_synthetic",
            "roi_summary",
        ]
        for key in required_keys:
            self.assertIn(key, first)

        # UWB is specialized: should be detached by default when attach_all=False
        uwb = next(s for s in payload["systems"] if s["adapter_id"] == "uwb_location_ubisense")
        self.assertFalse(uwb["attached"])
        self.assertEqual(uwb["feasibility_tier"], "high_cost_specialized")

    def test_fetch_all_attached(self):
        reg = IntegrationRegistry()
        reg.register(DummyAdapter("sys_1", is_attached=True))
        reg.register(DummyAdapter("sys_2", is_attached=False))

        records = reg.fetch_all(
            start_utc="2023-07-25T14:00:00Z",
            end_utc="2023-07-25T14:05:00Z",
            only_attached=True,
        )
        self.assertIn("sys_1", records)
        self.assertNotIn("sys_2", records)
        self.assertEqual(len(records["sys_1"]), 1)
        self.assertEqual(records["sys_1"][0].values["test_signal"], 42.0)


if __name__ == "__main__":
    unittest.main()
