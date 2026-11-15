"""Ultra-Wideband (UWB) Real-Time Location System adapter and offline mock.

Owner: @uiobio (Lei)
Provides:
- `uwb_x_m`: Barn X coordinate in meters.
- `uwb_y_m`: Barn Y coordinate in meters.
- `uwb_z_m`: Barn Z elevation in meters.
- `out_of_pen`: Boolean flag indicating when cow has exited pen (e.g. for milking).
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


class MockUwbLocationAdapter(BaseAdapter):
    """Synthetic adapter simulating indoor UWB anchor-tag tracking (CowView / Ubisense)."""

    def __init__(self, is_attached: bool = False) -> None:
        # Default detached for small farms due to high infrastructure cost
        super().__init__(is_attached=is_attached)
        self._metadata = SystemMetadata(
            adapter_id="uwb_location_ubisense",
            name="Ubisense / CowView Real-Time Barn UWB Tracking",
            vendor="Ubisense",
            system_category="uwb_location",
            signals=["uwb_x_m", "uwb_y_m", "uwb_z_m", "out_of_pen"],
            cadence="15_s",
            is_animal_level=True,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=85.0,
                hardware_setup_cost_usd=24000.0,
                feasibility_tier=FeasibilityTier.HIGH_COST_SPECIALIZED,
                recommended_min_herd_size=150,
                roi_summary="Specialized high-density anchor infrastructure. Highly accurate for research and spatial heatmaps, but economically prohibitive for typical small herds (<100 cows).",
            ),
            documentation_url="https://www.ubisense.com/solutions/livestock-monitoring/",
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
                message="Integration detached (high-cost specialized hardware)",
            )
        return AdapterHealth(
            adapter_id=self._metadata.adapter_id,
            status=HealthStatus.MOCKED,
            is_attached=True,
            is_healthy=True,
            is_synthetic=True,
            message="Serving synthetic UWB localization records",
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

        # 1-minute step for aggregated window fetch
        step_s = 60
        current_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())
        max_steps = 720
        steps_count = 0

        while current_ts <= end_ts and steps_count < max_steps:
            current_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
            ts_str = current_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Milking trips (04-05h and 15-16h local = 09-10h and 20-21h UTC)
            is_milking_trip = current_dt.hour in (9, 20)

            for cow in cows:
                cow_num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1

                if is_milking_trip:
                    # Out of pen state: null coordinates, out_of_pen = True
                    records.append(
                        ObservationRecord(
                            cow_id=cow,
                            ts_utc=ts_str,
                            values={
                                "uwb_x_m": None,
                                "uwb_y_m": None,
                                "uwb_z_m": None,
                                "out_of_pen": True,
                            },
                            imputation_flags={
                                "uwb_x_m": False,
                                "uwb_y_m": False,
                                "uwb_z_m": False,
                                "out_of_pen": False,
                            },
                            age_seconds={"uwb_x_m": 0.0, "uwb_y_m": 0.0, "uwb_z_m": 0.0, "out_of_pen": 0.0},
                            is_synthetic=True,
                        )
                    )
                else:
                    # Barn pen dimensions: 32m x 20m
                    base_x = 4.0 + (cow_num * 2.8) % 24.0
                    base_y = 3.0 + (cow_num * 1.7) % 14.0
                    wander = 1.2 * math.sin((current_ts / 300.0) + cow_num)
                    x_m = round(base_x + wander, 2)
                    y_m = round(base_y + wander * 0.8, 2)
                    z_m = 1.25

                    records.append(
                        ObservationRecord(
                            cow_id=cow,
                            ts_utc=ts_str,
                            values={
                                "uwb_x_m": x_m,
                                "uwb_y_m": y_m,
                                "uwb_z_m": z_m,
                                "out_of_pen": False,
                            },
                            imputation_flags={
                                "uwb_x_m": False,
                                "uwb_y_m": False,
                                "uwb_z_m": False,
                                "out_of_pen": False,
                            },
                            age_seconds={"uwb_x_m": 0.0, "uwb_y_m": 0.0, "uwb_z_m": 0.0, "out_of_pen": 0.0},
                            is_synthetic=True,
                        )
                    )

            current_ts += step_s
            steps_count += 1

        return records
