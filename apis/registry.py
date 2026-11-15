"""System Registry for farm monitoring and management integrations.

Owner: @uiobio (Lei)
Boundary:
- Manages discovered and installed adapters.
- Allows operators to attach or detach integrations without application restart.
- Exports integration feasibility metadata matching backend-visualization/CONTRACT.md §3.5
  to power small-farm decision support.
- Coordinates multi-system windowed fetches.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from apis.base import AdapterHealth, BaseAdapter, FeasibilityTier, ObservationRecord


class IntegrationRegistry:
    """Central registry of external system integrations and active attachments."""

    def __init__(self) -> None:
        self._adapters: Dict[str, BaseAdapter] = {}

    def register(self, adapter: BaseAdapter) -> None:
        """Register an adapter instance.

        Raises:
            ValueError: If an adapter with the same id is already registered.
        """
        adapter_id = adapter.metadata.adapter_id
        if adapter_id in self._adapters:
            raise ValueError(f"Adapter '{adapter_id}' is already registered.")
        self._adapters[adapter_id] = adapter

    def unregister(self, adapter_id: str) -> Optional[BaseAdapter]:
        """Unregister an adapter by id."""
        return self._adapters.pop(adapter_id, None)

    def get(self, adapter_id: str) -> Optional[BaseAdapter]:
        """Get an adapter by id."""
        return self._adapters.get(adapter_id)

    def list_adapters(self) -> List[BaseAdapter]:
        """Return all registered adapters in stable registration order."""
        return list(self._adapters.values())

    def list_attached_adapters(self) -> List[BaseAdapter]:
        """Return all currently attached adapters."""
        return [a for a in self._adapters.values() if a.is_attached]

    def attach(self, adapter_id: str) -> bool:
        """Attach an adapter by id.

        Returns True if found and attached, False if not found.
        """
        adapter = self.get(adapter_id)
        if adapter:
            adapter.attach()
            return True
        return False

    def detach(self, adapter_id: str) -> bool:
        """Detach an adapter by id.

        Returns True if found and detached, False if not found.
        """
        adapter = self.get(adapter_id)
        if adapter:
            adapter.detach()
            return True
        return False

    def health_summary(self) -> List[Dict[str, Any]]:
        """Return health status dictionaries for all registered adapters."""
        return [adapter.health().to_dict() for adapter in self._adapters.values()]

    def to_feasibility_payload(self) -> Dict[str, Any]:
        """Generate payload formatted for backend-visualization/CONTRACT.md §3.5 (/api/integrations).

        Matches the schema:
        {
          "systems": [
            {
              "adapter_id": "collar_imu_vital",
              "name": "Neck IMU Activity & Rumination",
              "attached": true,
              "cadence": "sub_second_aggregated_1m",
              "annual_cost_per_head_usd": 35.0,
              "feasibility_tier": "recommended",
              "signals": ["neck_imu_magnitude_mean", ...],
              "is_synthetic": true,
              "vendor": "Nedap CowControl",
              "roi_summary": "..."
            }
          ]
        }
        """
        systems = []
        for adapter in self._adapters.values():
            meta = adapter.metadata
            health = adapter.health()
            systems.append({
                "adapter_id": meta.adapter_id,
                "name": meta.name,
                "vendor": meta.vendor,
                "attached": adapter.is_attached,
                "cadence": meta.cadence,
                "annual_cost_per_head_usd": meta.cost_profile.annual_cost_per_head_usd,
                "hardware_setup_cost_usd": meta.cost_profile.hardware_setup_cost_usd,
                "feasibility_tier": meta.cost_profile.feasibility_tier.value,
                "signals": list(meta.signals),
                "is_synthetic": health.is_synthetic,
                "roi_summary": meta.cost_profile.roi_summary,
            })
        return {"systems": systems}

    def fetch_all(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
        only_attached: bool = True,
    ) -> Dict[str, List[ObservationRecord]]:
        """Fetch records from registered adapters within a time window.

        Args:
            start_utc: Window start ISO string
            end_utc: Window end ISO string
            cow_ids: Optional list of cow IDs
            only_attached: If True, only query attached adapters.

        Returns:
            Dictionary mapping adapter_id -> List[ObservationRecord]
        """
        results: Dict[str, List[ObservationRecord]] = {}
        for adapter in self._adapters.values():
            if only_attached and not adapter.is_attached:
                continue
            meta = adapter.metadata
            results[meta.adapter_id] = adapter.fetch_window(
                start_utc=start_utc,
                end_utc=end_utc,
                cow_ids=cow_ids,
            )
        return results


def create_default_registry(attach_all: bool = False) -> IntegrationRegistry:
    """Instantiate and populate an IntegrationRegistry with realistic mock adapters.

    Args:
        attach_all: If True, attach all adapters including specialized RTLS.
                    If False (default), high-cost specialized systems (e.g. UWB)
                    are detached by default to reflect small-farm feasibility.
    """
    from apis.adapters.bolus import MockCbtBolusAdapter
    from apis.adapters.climate import MockBarnClimateAdapter
    from apis.adapters.collar import MockCollarImuAdapter
    from apis.adapters.herd import MockHerdManagementAdapter
    from apis.adapters.location import MockUwbLocationAdapter
    from apis.adapters.milking import MockMilkingParlorAdapter
    from apis.adapters.pedometer import MockAnklePedometerAdapter
    from apis.adapters.weather import MockWeatherStationAdapter

    registry = IntegrationRegistry()
    registry.register(MockMilkingParlorAdapter(is_attached=True))
    registry.register(MockCbtBolusAdapter(is_attached=True))
    registry.register(MockBarnClimateAdapter(is_attached=True))
    registry.register(MockAnklePedometerAdapter(is_attached=True))
    # UWB RTLS is high cost, detached by default for small farms unless attach_all=True
    registry.register(MockUwbLocationAdapter(is_attached=attach_all))
    registry.register(MockCollarImuAdapter(is_attached=True))
    registry.register(MockWeatherStationAdapter(is_attached=True))
    registry.register(MockHerdManagementAdapter(is_attached=True))

    return registry

