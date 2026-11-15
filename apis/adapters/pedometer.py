"""Ankle Pedometer & Rest Monitoring adapter and offline mock.

Owner: @uiobio (Lei)
Provides:
- `lying`: Binary posture indicator (1 = lying down, 0 = standing/walking).
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


class MockAnklePedometerAdapter(BaseAdapter):
    """Synthetic adapter simulating leg-mounted activity/lying monitors (IceRobotics / Nedap SmartTag Leg)."""

    def __init__(self, is_attached: bool = True) -> None:
        super().__init__(is_attached=is_attached)
        self._metadata = SystemMetadata(
            adapter_id="ankle_pedometer_nedap",
            name="Nedap SmartTag Leg / IceRobotics Pedometer",
            vendor="Nedap",
            system_category="ankle_pedometer",
            signals=["lying"],
            cadence="1_min",
            is_animal_level=True,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=28.0,
                hardware_setup_cost_usd=950.0,
                feasibility_tier=FeasibilityTier.RECOMMENDED,
                recommended_min_herd_size=30,
                roi_summary="Highly effective for lameness and estrus detection. Lying bout duration provides robust early welfare alarms.",
            ),
            documentation_url="https://www.nedap-livestockmanagement.com/dairy-farming/cowcontrol/leg-tags/",
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
            message="Serving synthetic ankle lying state records",
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
                # Dairy cows lie down ~10-14 hours per day in 60-90 min bouts.
                # Simulate realistic lying bouts alternating per cow
                bout_period = 180 + (cow_num * 13) % 40  # 3-hour cycle
                bout_phase = (minute_of_day + cow_num * 47) % bout_period
                # Lying for ~55% of the bout cycle
                is_lying = 1 if bout_phase < (bout_period * 0.55) else 0

                # Never lying during milking trips (around 04-05h and 15-16h local = ~09-10h and 20-21h UTC)
                if current_dt.hour in (9, 20):
                    is_lying = 0

                records.append(
                    ObservationRecord(
                        cow_id=cow,
                        ts_utc=ts_str,
                        values={"lying": is_lying},
                        imputation_flags={"lying": False},
                        age_seconds={"lying": 0.0},
                        is_synthetic=True,
                    )
                )

            current_ts += step_s
            steps_count += 1

        return records
