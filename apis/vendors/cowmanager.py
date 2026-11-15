"""CowManager API adapter and ear sensor normalizer.

Maps CowManager Cloud API (v2) ear sensor telemetry to mmcows schema:
- Ear sensor behavioral classification: rumination, eating, resting, active, high active (/cows/{id}/behavior)
- Dual-sensor ear skin surface temperature mapped to CBT proxy (/cows/{id}/temperature)
- Health alerts and heat detection flags (/cows/{id}/alerts)
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional

from apis.base import (
    AdapterHealth,
    BaseAdapter,
    CostProfile,
    FeasibilityTier,
    HealthStatus,
    ObservationRecord,
    SystemMetadata,
)


class CowManagerAdapter(BaseAdapter):
    """Adapter for CowManager Cloud API v2 (Ear Tag Sensors)."""

    def __init__(
        self,
        is_attached: bool = True,
        api_base_url: str = "https://api.cowmanager.com/v2",
        farm_code: str = "COWMAN-FARM-01",
    ) -> None:
        super().__init__(is_attached=is_attached)
        self.api_base_url = api_base_url
        self.farm_code = farm_code
        self._metadata = SystemMetadata(
            adapter_id="cowmanager",
            name="CowManager Ear Tag Sensor (Nutrition, Health, Fertility)",
            vendor="CowManager B.V.",
            system_category="ear_tag_monitoring",
            signals=[
                "rumination_minutes",
                "eating_minutes",
                "resting_minutes",
                "active_minutes",
                "high_active_minutes",
                "activity_index",
                "ear_temp_c",
                "cbt_c",
                "lying",
            ],
            cadence="15min_and_hourly",
            is_animal_level=True,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=36.0,
                hardware_setup_cost_usd=1500.0,
                feasibility_tier=FeasibilityTier.RECOMMENDED,
                recommended_min_herd_size=30,
                roi_summary="Ear tag monitoring for health, rumination and ear temperature fever alerts.",
            ),
            documentation_url="https://www.cowmanager.com/",
        )

    @property
    def metadata(self) -> SystemMetadata:
        return self._metadata

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            adapter_id="cowmanager",
            status=HealthStatus.ATTACHED if self._is_attached else HealthStatus.DETACHED,
            is_attached=self._is_attached,
            is_healthy=self._is_attached,
            is_synthetic=True,
            message="Connected to CowManager Cloud API mock stream" if self._is_attached else "Detached",
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

        # 1-hour ear sensor telemetry intervals
        step_s = 3600
        cur_ts = start_dt.timestamp()

        while cur_ts < end_dt.timestamp():
            b_dt = datetime.fromtimestamp(cur_ts, tz=timezone.utc)
            ts_str = b_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            for cow in cows:
                num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
                raw_ear = self._mock_cowmanager_raw(cow, ts_str, num)
                norm_rec = self.normalize_ear_sensor(raw_ear)
                records.append(norm_rec)

            cur_ts += step_s

        return records

    # --- Raw Mock Generator ---
    def _mock_cowmanager_raw(self, cow_id: str, ts_utc: str, cow_num: int) -> Dict[str, Any]:
        """Raw CowManager GET /api/v2/cows/{id}/behavior JSON payload."""
        hour = int(ts_utc[11:13]) if len(ts_utc) >= 13 else 12
        is_night = hour < 6 or hour >= 22

        rum_min = 28.0 if is_night else 12.0
        eat_min = 5.0 if is_night else 22.0
        rest_min = 22.0 if is_night else 10.0
        active_min = 5.0 if is_night else 14.0
        high_act_min = 0.0 if is_night else 2.0

        # Ear skin temperature: baselines ~32 - 36 °C, varies with circadian rhythm and ambient temp
        ear_temp = round(33.2 + 1.2 * math.sin((hour - 10) / 24.0 * 2 * math.pi) + 0.1 * (cow_num % 3), 2)

        return {
            "cow_id": cow_id,
            "timestamp_utc": ts_utc,
            "tag_id": f"CM-TAG-{cow_num:03d}",
            "interval_minutes": 60,
            "behavior": {
                "rumination_minutes": rum_min,
                "eating_minutes": eat_min,
                "resting_minutes": rest_min,
                "active_minutes": active_min,
                "high_active_minutes": high_act_min,
            },
            "temperature": {
                "ear_surface_temp_c": ear_temp,
                "temperature_status": "normal",
            },
            "alerts": {
                "health_status": "healthy",
                "heat_alert": False,
            },
        }

    # --- Normalizer ---
    @staticmethod
    def normalize_ear_sensor(
        raw: Dict[str, Any],
        indoor_temp_c: Optional[float] = 20.0,
    ) -> ObservationRecord:
        """Reprocess raw CowManager ear sensor data into mmcows schema.

        Maps:
        - Ear surface temperature to calibrated CBT core temperature proxy:
          cbt_c_est = ear_surface_temp_c + 0.18 * max(0.0, 25.0 - indoor_temp_c) + offset
        - Behavioral modes into activity_index and lying flag.
        """
        beh = raw.get("behavior", {})
        temp = raw.get("temperature", {})

        rum_min = float(beh.get("rumination_minutes", 0.0))
        eat_min = float(beh.get("eating_minutes", 0.0))
        rest_min = float(beh.get("resting_minutes", 0.0))
        act_min = float(beh.get("active_minutes", 0.0))
        high_act_min = float(beh.get("high_active_minutes", 0.0))
        tot_min = max(1.0, rum_min + eat_min + rest_min + act_min + high_act_min)

        # Activity index scaled 0.0 - 1.0
        act_idx = round((act_min + 2.0 * high_act_min) / tot_min, 3)
        acc_proxy = round(1.15 + act_idx * 3.5, 2)

        # Lying flag: resting > 20 min in an hour
        is_lying = 1 if rest_min >= 20.0 else 0

        # Core Body Temperature (CBT) proxy estimation from ear skin temperature
        ear_temp = float(temp.get("ear_surface_temp_c", 33.5))
        amb = indoor_temp_c if indoor_temp_c is not None else 20.0
        cbt_proxy = round(38.6 + (ear_temp - 33.5) * 0.45 - (amb - 20.0) * 0.05, 2)

        values = {
            "source_adapter": "cowmanager",
            "rumination_minutes": rum_min,
            "eating_minutes": eat_min,
            "resting_minutes": rest_min,
            "active_minutes": act_min,
            "high_active_minutes": high_act_min,
            "activity_index": act_idx,
            "neck_imu_magnitude_mean": acc_proxy,
            "lying": is_lying,
            "ear_temp_c": ear_temp,
            "cbt_c": cbt_proxy,
        }

        return ObservationRecord(
            cow_id=raw.get("cow_id"),
            ts_utc=raw.get("timestamp_utc", ""),
            values=values,
            imputation_flags={"cbt_c": True},
            age_seconds={"cbt_c": 0.0},
            is_synthetic=True,
        )
