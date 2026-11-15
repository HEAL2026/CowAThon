"""Barn Climate & THI monitoring adapter and offline mock.

Owner: @uiobio (Lei)
Provides:
- `indoor_temp_c`: Ambient indoor barn temperature in °C.
- `indoor_rh_pct`: Indoor relative humidity percentage (0-100%).
- `indoor_thi`: Temperature-Humidity Index (NRC formula).

Invariant:
- Barn-wide system: `cow_id` is None per CONTRACT.md §1 convention.
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


class MockBarnClimateAdapter(BaseAdapter):
    """Synthetic adapter simulating indoor barn climate stations (Munters FarmConnect / Fancom)."""

    def __init__(self, is_attached: bool = True) -> None:
        super().__init__(is_attached=is_attached)
        self._metadata = SystemMetadata(
            adapter_id="barn_climate_munters",
            name="Munters FarmConnect Barn Climate & THI",
            vendor="Munters",
            system_category="barn_climate",
            signals=["indoor_temp_c", "indoor_rh_pct", "indoor_thi"],
            cadence="1_min",
            is_animal_level=False,  # Farm/barn-wide: cow_id is None
            cost_profile=CostProfile(
                annual_cost_per_head_usd=4.5,
                hardware_setup_cost_usd=1800.0,
                feasibility_tier=FeasibilityTier.RECOMMENDED,
                recommended_min_herd_size=20,
                roi_summary="Extremely high ROI for small farms. Automated fan/soaker actuation prevents heat-induced milk drops.",
            ),
            documentation_url="https://www.munters.com/en/munters/products/controllers/farmconnect/",
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
            message="Serving synthetic barn climate & THI telemetry",
        )

    def fetch_window(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
    ) -> List[ObservationRecord]:
        if not self._is_attached:
            return []

        records: List[ObservationRecord] = []

        try:
            start_dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
        except Exception:
            return []

        step_s = 60
        current_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())
        max_steps = 1440
        steps_count = 0

        while current_ts <= end_ts and steps_count < max_steps:
            current_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
            ts_str = current_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            hour_utc = current_dt.hour + current_dt.minute / 60.0

            # Diurnal temperature cycle: peak around 15:00 UTC (10:00 local) through late afternoon
            temp_c = round(21.0 + 6.5 * math.sin((hour_utc - 8) * (2 * math.pi / 24)), 2)
            # RH inverse to temp
            rh_pct = round(max(35.0, min(95.0, 75.0 - 25.0 * math.sin((hour_utc - 8) * (2 * math.pi / 24)))), 1)
            # NRC THI calculation: (1.8 * T + 32) - (0.55 - 0.0055 * RH) * (1.8 * T - 26)
            thi = round((1.8 * temp_c + 32.0) - (0.55 - 0.0055 * rh_pct) * (1.8 * temp_c - 26.0), 1)

            records.append(
                ObservationRecord(
                    cow_id=None,  # Barn-level
                    ts_utc=ts_str,
                    values={
                        "indoor_temp_c": temp_c,
                        "indoor_rh_pct": rh_pct,
                        "indoor_thi": thi,
                    },
                    imputation_flags={
                        "indoor_temp_c": False,
                        "indoor_rh_pct": False,
                        "indoor_thi": False,
                    },
                    age_seconds={
                        "indoor_temp_c": 0.0,
                        "indoor_rh_pct": 0.0,
                        "indoor_thi": 0.0,
                    },
                    is_synthetic=True,
                )
            )

            current_ts += step_s
            steps_count += 1

        return records
