"""Outdoor Hyperlocal Weather Station adapter and offline mock.

Owner: @uiobio (Lei)
Provides:
- Outdoor weather telemetry in standard SI units matching MMCows & cleaning CONTRACT.md §5:
  `outdoor_temp_c`, `outdoor_dewpoint_c`, `outdoor_rh_pct`, `outdoor_wind_mps`,
  `outdoor_gust_mps`, `outdoor_pressure_hpa`, `outdoor_precip_mm`, `outdoor_uv`, `outdoor_solar_wm2`.

Invariant:
- Farm-level system: `cow_id` is None.
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


class MockWeatherStationAdapter(BaseAdapter):
    """Synthetic adapter simulating on-farm weather stations (Davis Vantage Pro2 / Tomorrow.io API)."""

    def __init__(self, is_attached: bool = True) -> None:
        super().__init__(is_attached=is_attached)
        self._metadata = SystemMetadata(
            adapter_id="weather_station_tomorrow_io",
            name="Tomorrow.io / Davis On-Farm Micro-Weather Station",
            vendor="Tomorrow.io",
            system_category="weather",
            signals=[
                "outdoor_temp_c",
                "outdoor_dewpoint_c",
                "outdoor_rh_pct",
                "outdoor_wind_mps",
                "outdoor_gust_mps",
                "outdoor_pressure_hpa",
                "outdoor_precip_mm",
                "outdoor_uv",
                "outdoor_solar_wm2",
            ],
            cadence="5_min",
            is_animal_level=False,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=2.0,
                hardware_setup_cost_usd=600.0,
                feasibility_tier=FeasibilityTier.RECOMMENDED,
                recommended_min_herd_size=20,
                roi_summary="Negligible per-head cost. Enables forward-looking heat risk forecasting 24-72 hours in advance.",
            ),
            documentation_url="https://www.tomorrow.io/agriculture/",
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
            message="Serving synthetic on-farm weather feeds",
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

        step_s = 300  # 5-min cadence
        current_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())
        max_steps = 288
        steps_count = 0

        while current_ts <= end_ts and steps_count < max_steps:
            current_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
            ts_str = current_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            hour_utc = current_dt.hour + current_dt.minute / 60.0

            # Outdoor ambient temperature in summer (July Midwest)
            temp_c = round(23.5 + 7.0 * math.sin((hour_utc - 8) * (2 * math.pi / 24)), 2)
            rh_pct = round(max(30.0, min(98.0, 78.0 - 32.0 * math.sin((hour_utc - 8) * (2 * math.pi / 24)))), 1)
            dewpoint_c = round(temp_c - ((100 - rh_pct) / 5.0), 2)
            solar_wm2 = max(0.0, round(850.0 * math.sin((hour_utc - 6) * (math.pi / 14)), 1)) if 6.0 <= hour_utc <= 20.0 else 0.0
            uv_index = round(solar_wm2 / 100.0, 1)
            wind_mps = round(2.5 + 1.2 * math.sin(current_ts / 1800.0), 2)
            gust_mps = round(wind_mps + 1.8, 2)
            pressure_hpa = round(1008.2 + 1.5 * math.cos(current_ts / 86400.0), 1)

            records.append(
                ObservationRecord(
                    cow_id=None,
                    ts_utc=ts_str,
                    values={
                        "outdoor_temp_c": temp_c,
                        "outdoor_dewpoint_c": dewpoint_c,
                        "outdoor_rh_pct": rh_pct,
                        "outdoor_wind_mps": wind_mps,
                        "outdoor_gust_mps": gust_mps,
                        "outdoor_pressure_hpa": pressure_hpa,
                        "outdoor_precip_mm": 0.0,
                        "outdoor_uv": uv_index,
                        "outdoor_solar_wm2": solar_wm2,
                    },
                    imputation_flags={k: False for k in self._metadata.signals},
                    age_seconds={k: 0.0 for k in self._metadata.signals},
                    is_synthetic=True,
                )
            )

            current_ts += step_s
            steps_count += 1

        return records
