"""Rumen Bolus Core Body Temperature adapter and offline mock.

Owner: @uiobio (Lei)
Provides:
- `cbt_c`: Core body temperature in degrees Celsius (canonical MMCows/cleaning unit).
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


class MockCbtBolusAdapter(BaseAdapter):
    """Synthetic adapter simulating reticulorumen temperature boluses (SmaXtec / Moocall)."""

    def __init__(self, is_attached: bool = True) -> None:
        super().__init__(is_attached=is_attached)
        self._metadata = SystemMetadata(
            adapter_id="cbt_bolus_smaxtec",
            name="SmaXtec Reticulorumen Thermal Bolus",
            vendor="SmaXtec",
            system_category="bolus_temperature",
            signals=["cbt_c"],
            cadence="1_min",
            is_animal_level=True,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=42.0,
                hardware_setup_cost_usd=1500.0,
                feasibility_tier=FeasibilityTier.OPTIONAL,
                recommended_min_herd_size=50,
                roi_summary="High diagnostic precision for early systemic inflammation, but recurring bolus replacement costs can be heavy for small herds.",
            ),
            documentation_url="https://smaxtec.com/en/system/",
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
            message="Serving synthetic rumen bolus CBT records",
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

        # Step by minute
        step_s = 60
        current_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        # Cap output records to avoid exploding memory in large windows
        max_steps = 1440  # up to 24 hours of 1-min data per query
        steps_count = 0

        while current_ts <= end_ts and steps_count < max_steps:
            current_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
            ts_str = current_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            hour_utc = current_dt.hour + current_dt.minute / 60.0

            for cow in cows:
                cow_num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
                # Realistic circadian temperature rhythm: peak late afternoon (16-18h local), nadir morning (05-07h)
                circadian = 0.4 * math.sin((hour_utc - 10) * (2 * math.pi / 24))
                # Cow baseline offset
                base_cbt = 38.6 + (cow_num % 4) * 0.15
                # Periodic water drinking dips (temperature drops briefly after drinking)
                drinking_drop = -0.6 if (int(current_ts / 3600) + cow_num) % 8 == 0 and current_dt.minute < 10 else 0.0

                cbt = round(base_cbt + circadian + drinking_drop, 2)
                records.append(
                    ObservationRecord(
                        cow_id=cow,
                        ts_utc=ts_str,
                        values={"cbt_c": cbt},
                        imputation_flags={"cbt_c": False},
                        age_seconds={"cbt_c": 0.0},
                        is_synthetic=True,
                    )
                )

            current_ts += step_s
            steps_count += 1

        return records
