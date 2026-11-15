"""Milking Parlor & Automated Milking System adapter and offline mock.

Owner: @uiobio (Lei)
Provides:
- `milk_yield_kg`: Daily milk yield in kg (canonical MMCows/cleaning unit).
- `dim`: Days in milk (lactation stage integer).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List, Optional

from apis.base import (
    AdapterHealth,
    BaseAdapter,
    CostProfile,
    FeasibilityTier,
    HealthStatus,
    ObservationRecord,
    SystemMetadata,
)


class MockMilkingParlorAdapter(BaseAdapter):
    """Synthetic adapter simulating electronic milk meters (DeLaval / GEA / Lely)."""

    def __init__(self, is_attached: bool = True) -> None:
        super().__init__(is_attached=is_attached)
        self._metadata = SystemMetadata(
            adapter_id="milking_parlor_delaval",
            name="DeLaval DelPro Automated Milk Metering",
            vendor="DeLaval",
            system_category="milking",
            signals=["milk_yield_kg", "dim"],
            cadence="daily",
            is_animal_level=True,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=18.0,
                hardware_setup_cost_usd=12000.0,
                feasibility_tier=FeasibilityTier.RECOMMENDED,
                recommended_min_herd_size=40,
                roi_summary="Essential for production tracking. Early yield drop detection pays back within 14 months.",
            ),
            documentation_url="https://www.delaval.com/en-us/our-solutions/herd-management/",
        )

    @property
    def metadata(self) -> SystemMetadata:
        return self._metadata

    def health(self) -> AdapterHealth:
        if not self._is_attached:
            return AdapterHealth(
                adapter_id=self._metadata.adapter_id,
                status=HealthStatus.DETACHED,
                is_attached=False,
                is_healthy=False,
                is_synthetic=True,
                message="Integration detached by operator",
            )
        return AdapterHealth(
            adapter_id=self._metadata.adapter_id,
            status=HealthStatus.MOCKED,
            is_attached=True,
            is_healthy=True,
            is_synthetic=True,
            message="Serving synthetic milk parlor records",
        )

    def fetch_window(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
    ) -> List[ObservationRecord]:
        if not self._is_attached:
            return []

        cows = cow_ids or [f"C{i:02d}" for i in range(1, 11)]
        records: List[ObservationRecord] = []

        try:
            start_dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
        except Exception:
            return []

        # Yield one record per cow per day within window
        current_dt = datetime(start_dt.year, start_dt.month, start_dt.day, 12, 0, tzinfo=timezone.utc)
        while current_dt <= end_dt:
            ts_str = current_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            day_idx = current_dt.timetuple().tm_yday

            for cow in cows:
                # Deterministic synthetic variation per cow
                cow_num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
                base_yield = 26.0 + (cow_num % 7) * 2.2
                # Seasonal/day fluctuation
                yield_kg = round(base_yield + math.sin((day_idx + cow_num) * 0.3) * 3.5, 2)
                dim = 50 + (cow_num * 17 + day_idx) % 220

                records.append(
                    ObservationRecord(
                        cow_id=cow,
                        ts_utc=ts_str,
                        values={"milk_yield_kg": max(12.0, yield_kg), "dim": dim},
                        imputation_flags={"milk_yield_kg": False, "dim": False},
                        age_seconds={"milk_yield_kg": 0.0, "dim": 0.0},
                        is_synthetic=True,
                    )
                )

            # Advance by 1 day (86400 seconds)
            current_dt = datetime.fromtimestamp(current_dt.timestamp() + 86400, tz=timezone.utc)

        return records
