"""Herd Management Software core adapter and offline mock.

Owner: @uiobio (Lei)
Provides:
- Cow demographic and lactation records: `parity`, `days_in_milk`, `reproductive_status`,
  `pen_number`, `mastitis_history_count`.
"""

from __future__ import annotations

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


class MockHerdManagementAdapter(BaseAdapter):
    """Synthetic adapter simulating herd management software (VAS PULSE / DairyComp 305 / BoviSync)."""

    def __init__(self, is_attached: bool = True) -> None:
        super().__init__(is_attached=is_attached)
        self._metadata = SystemMetadata(
            adapter_id="herd_management_vas_pulse",
            name="VAS PULSE / DairyComp 305 Herd Management Core",
            vendor="Valley Agricultural Software (VAS)",
            system_category="herd_management",
            signals=[
                "parity",
                "days_in_milk",
                "reproductive_status",
                "pen_number",
                "mastitis_history_count",
            ],
            cadence="daily_sync",
            is_animal_level=True,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=12.0,
                hardware_setup_cost_usd=0.0,
                feasibility_tier=FeasibilityTier.RECOMMENDED,
                recommended_min_herd_size=25,
                roi_summary="Universal dairy management backbone. Integrates veterinary events, breeding records, and milk production.",
            ),
            documentation_url="https://vas.com/pulse/",
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
            message="Serving synthetic herd management records",
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

        # Daily sync records at 06:00 UTC
        current_dt = datetime(start_dt.year, start_dt.month, start_dt.day, 6, 0, tzinfo=timezone.utc)
        repro_states = ["pregnant", "open", "bred", "fresh"]

        while current_dt <= end_dt:
            ts_str = current_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            day_idx = current_dt.timetuple().tm_yday

            for cow in cows:
                cow_num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
                parity = 1 + (cow_num % 4)
                dim = (cow_num * 23 + day_idx) % 305
                repro = repro_states[(cow_num + day_idx // 30) % len(repro_states)]
                pen = 1 if dim < 150 else 2
                mastitis_cases = 1 if cow_num in (2, 7) else 0

                records.append(
                    ObservationRecord(
                        cow_id=cow,
                        ts_utc=ts_str,
                        values={
                            "parity": parity,
                            "days_in_milk": dim,
                            "reproductive_status": repro,
                            "pen_number": pen,
                            "mastitis_history_count": mastitis_cases,
                        },
                        imputation_flags={k: False for k in self._metadata.signals},
                        age_seconds={k: 0.0 for k in self._metadata.signals},
                        is_synthetic=True,
                    )
                )

            current_dt = datetime.fromtimestamp(current_dt.timestamp() + 86400, tz=timezone.utc)

        return records
