"""Collar IMU Activity, Rumination & Barometric pressure adapter and offline mock.

Owner: @uiobio (Lei)
Provides:
- `neck_imu_magnitude_mean`: 1-minute mean acceleration magnitude in m/s².
- `neck_imu_magnitude_std`: 1-minute standard deviation of acceleration magnitude in m/s².
- `collar_pressure_hpa`: Ambient atmospheric pressure measured at collar in hPa.
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


class MockCollarImuAdapter(BaseAdapter):
    """Synthetic adapter simulating neck collar activity & rumination tags (Nedap CowControl / Allflex SenseHub)."""

    def __init__(self, is_attached: bool = True) -> None:
        super().__init__(is_attached=is_attached)
        self._metadata = SystemMetadata(
            adapter_id="collar_imu_nedap",
            name="Nedap CowControl / Allflex SenseHub Neck Collar",
            vendor="Nedap",
            system_category="collar_imu",
            signals=["neck_imu_magnitude_mean", "neck_imu_magnitude_std", "collar_pressure_hpa"],
            cadence="sub_second_aggregated_1m",
            is_animal_level=True,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=35.0,
                hardware_setup_cost_usd=1600.0,
                feasibility_tier=FeasibilityTier.RECOMMENDED,
                recommended_min_herd_size=30,
                roi_summary="Industry workhorse. Rumination drop precedes clinical mastitis symptoms by 24-48 hours.",
            ),
            documentation_url="https://www.nedap-livestockmanagement.com/dairy-farming/cowcontrol/smarttag-neck/",
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
            message="Serving synthetic collar IMU telemetry",
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

        step_s = 60
        current_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())
        max_steps = 1440
        steps_count = 0

        while current_ts <= end_ts and steps_count < max_steps:
            current_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
            ts_str = current_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            minute_of_day = current_dt.hour * 60 + current_dt.minute

            for cow in cows:
                cow_num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1

                # Active vs resting behavior rhythms
                active_phase = math.sin((minute_of_day + cow_num * 55) * (2 * math.pi / 180))
                # Basal acceleration ~ 9.8 m/s² (gravity vector) plus activity vibration
                base_mag = 9.81 + 0.15 * max(0.0, active_phase)
                std_mag = 0.08 + 0.35 * max(0.0, active_phase)

                # Milking walk activity spikes
                if current_dt.hour in (9, 20):
                    base_mag += 0.8
                    std_mag += 0.7

                mag_mean = round(base_mag, 3)
                mag_std = round(std_mag, 3)
                pressure_hpa = round(993.5 + 2.0 * math.sin(current_ts / 86400.0), 1)

                records.append(
                    ObservationRecord(
                        cow_id=cow,
                        ts_utc=ts_str,
                        values={
                            "neck_imu_magnitude_mean": mag_mean,
                            "neck_imu_magnitude_std": mag_std,
                            "collar_pressure_hpa": pressure_hpa,
                        },
                        imputation_flags={
                            "neck_imu_magnitude_mean": False,
                            "neck_imu_magnitude_std": False,
                            "collar_pressure_hpa": False,
                        },
                        age_seconds={
                            "neck_imu_magnitude_mean": 0.0,
                            "neck_imu_magnitude_std": 0.0,
                            "collar_pressure_hpa": 0.0,
                        },
                        is_synthetic=True,
                    )
                )

            current_ts += step_s
            steps_count += 1

        return records
