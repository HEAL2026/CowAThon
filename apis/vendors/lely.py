"""Lely Horizon API integration adapter and data normalizer.

Maps Lely Horizon REST API & ICAR ADE machine telemetry to mmcows schema:
- Astronaut AMS & rotary carousel visits (/milkvisits, /milkvisitrobotdata)
- Qwes collar rumination & activity (/ruminations, /activities)
- Barn climate telemetry (/climate)
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


def compute_thi(temp_c: float, rh_pct: float) -> float:
    """Standard dairy Temperature-Humidity Index formula (NRC / Kibler):
    THI = 0.8 * T + (RH / 100) * (T - 14.4) + 46.3
    """
    return round(0.8 * temp_c + (rh_pct / 100.0) * (temp_c - 14.4) + 46.3, 2)


class LelyHorizonAdapter(BaseAdapter):
    """Adapter for Lely Horizon Cloud API (OAS3 / ICAR ADE standard)."""

    def __init__(
        self,
        is_attached: bool = True,
        api_base_url: str = "https://api-integration.lely.com/v1",
        farm_id: str = "FARM-LELY-01",
    ) -> None:
        super().__init__(is_attached=is_attached)
        self.api_base_url = api_base_url
        self.farm_id = farm_id
        self._metadata = SystemMetadata(
            adapter_id="lely_horizon",
            name="Lely Horizon Cloud & Astronaut / Qwes Telemetry",
            vendor="Lely Industries N.V.",
            system_category="milking_and_collar",
            signals=[
                "milk_yield_kg",
                "milk_duration_sec",
                "peak_flow_rate_kg_min",
                "cond_lf_ms_cm",
                "cond_lr_ms_cm",
                "cond_rf_ms_cm",
                "cond_rr_ms_cm",
                "cond_max_ms_cm",
                "rumination_minutes",
                "eating_minutes",
                "activity_index",
                "indoor_temp_c",
                "indoor_rh_pct",
                "indoor_thi",
            ],
            cadence="per_visit_and_15min",
            is_animal_level=True,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=48.0,
                hardware_setup_cost_usd=45000.0,
                feasibility_tier=FeasibilityTier.RECOMMENDED,
                recommended_min_herd_size=60,
                roi_summary="Automated milking box and Qwes rumination collar integration. Early mastitis detection via 4-quarter conductivity.",
            ),
            documentation_url="https://api-integration.lely.com/swagger/v1/swagger.json",
        )

    @property
    def metadata(self) -> SystemMetadata:
        return self._metadata

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            adapter_id="lely_horizon",
            status=HealthStatus.ATTACHED if self._is_attached else HealthStatus.DETACHED,
            is_attached=self._is_attached,
            is_healthy=self._is_attached,
            is_synthetic=True,
            message="Connected to Lely Horizon Cloud mock stream" if self._is_attached else "Detached",
        )

    def fetch_window(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
    ) -> List[ObservationRecord]:
        """Fetch and normalize Lely Horizon telemetry for the specified window."""
        if not self._is_attached:
            return []

        cows = cow_ids or [f"C{i:02d}" for i in range(1, 11)]
        records: List[ObservationRecord] = []

        try:
            start_dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
        except Exception:
            return []

        # 1. Milking visits (twice daily ~09:30 and ~20:30 UTC)
        cur_day = datetime(start_dt.year, start_dt.month, start_dt.day, tzinfo=timezone.utc)
        while cur_day.timestamp() <= end_dt.timestamp():
            for m_hour in [9, 20]:
                session_dt = datetime(cur_day.year, cur_day.month, cur_day.day, m_hour, 30, tzinfo=timezone.utc)
                if start_dt <= session_dt <= end_dt:
                    ts_str = session_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    for cow in cows:
                        num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
                        raw_payload = self._mock_lely_raw_milkvisit(cow, ts_str, num)
                        norm_rec = self.normalize_milkvisit(raw_payload)
                        records.append(norm_rec)

            cur_day = datetime.fromtimestamp(cur_day.timestamp() + 86400, tz=timezone.utc)

        # 2. Collar & Rumination (2-hour buckets)
        step_s = 7200
        cur_ts = start_dt.timestamp()
        while cur_ts < end_dt.timestamp():
            b_dt = datetime.fromtimestamp(cur_ts, tz=timezone.utc)
            ts_str = b_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            for cow in cows:
                num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
                raw_collar = self._mock_lely_raw_collar(cow, ts_str, num)
                norm_collar = self.normalize_collar(raw_collar)
                records.append(norm_collar)
            cur_ts += step_s

        # 3. Barn Climate (1-hour intervals)
        step_clim = 3600
        cur_ts = start_dt.timestamp()
        while cur_ts < end_dt.timestamp():
            c_dt = datetime.fromtimestamp(cur_ts, tz=timezone.utc)
            ts_str = c_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            raw_clim = self._mock_lely_raw_climate(ts_str)
            norm_clim = self.normalize_climate(raw_clim)
            records.append(norm_clim)
            cur_ts += step_clim

        return records

    # --- Raw Mock Generators (emulating Lely Swagger payload shapes) ---
    def _mock_lely_raw_milkvisit(self, cow_id: str, ts_utc: str, cow_num: int) -> Dict[str, Any]:
        """Raw Lely Horizon GET /milkvisits JSON payload representation."""
        stall_id = f"ASTRONAUT-{(cow_num % 3) + 1:02d}"
        yield_val = round(12.0 + (cow_num % 4) * 1.5, 2)
        base_cond = round(4.85 + (cow_num % 3) * 0.15, 2)
        return {
            "animal_id": cow_id,
            "visit_datetime": ts_utc,
            "device_id": stall_id,
            "device_type": "Astronaut_A5",
            "milk_yield_kg": yield_val,
            "milking_duration_seconds": 380 + (cow_num * 10) % 120,
            "box_time_seconds": 450 + (cow_num * 10) % 120,
            "peak_flow_rate_kg_min": round(3.8 + (cow_num % 3) * 0.4, 2),
            "average_flow_rate_kg_min": round(2.2 + (cow_num % 3) * 0.2, 2),
            "dead_milking_time_seconds": 15,
            "conductivity_lf": base_cond,
            "conductivity_lr": round(base_cond + 0.05, 2),
            "conductivity_rf": round(base_cond - 0.05, 2),
            "conductivity_rr": round(base_cond + 0.10, 2),
            "temperature_c": round(38.6 + 0.1 * (cow_num % 2), 2),
            "blood_detected": False,
            "mqc_scc_indication": "normal",
        }

    def _mock_lely_raw_collar(self, cow_id: str, ts_utc: str, cow_num: int) -> Dict[str, Any]:
        """Raw Lely Horizon GET /ruminations & /activities JSON payload."""
        hour = int(ts_utc[11:13]) if len(ts_utc) >= 13 else 12
        is_night = hour < 6 or hour >= 22
        rum_min = 65.0 if is_night else 35.0
        eat_min = 15.0 if is_night else 40.0
        act_score = 0.15 if is_night else 0.45
        return {
            "animal_id": cow_id,
            "timestamp": ts_utc,
            "sensor_type": "Qwes_HR",
            "rumination_minutes_2h": rum_min,
            "eating_minutes_2h": eat_min,
            "inactivity_minutes_2h": 120.0 - (rum_min + eat_min),
            "activity_relative_score": act_score,
        }

    def _mock_lely_raw_climate(self, ts_utc: str) -> Dict[str, Any]:
        """Raw Lely Horizon GET /climate JSON payload."""
        hour = int(ts_utc[11:13]) if len(ts_utc) >= 13 else 12
        temp_c = round(19.0 + 5.0 * math.sin((hour - 8) / 24.0 * 2 * math.pi), 1)
        rh_pct = round(65.0 - 15.0 * math.sin((hour - 8) / 24.0 * 2 * math.pi), 1)
        return {
            "station_id": "LELY-CLIMATE-01",
            "timestamp": ts_utc,
            "temperature_c": temp_c,
            "relative_humidity_pct": rh_pct,
            "thi": compute_thi(temp_c, rh_pct),
        }

    # --- Normalizers into mmcows / ObservationRecord schema ---
    @staticmethod
    def normalize_milkvisit(raw: Dict[str, Any]) -> ObservationRecord:
        """Reprocess raw Lely milkvisit into standard ObservationRecord."""
        cond_lf = float(raw.get("conductivity_lf", 5.0))
        cond_lr = float(raw.get("conductivity_lr", 5.0))
        cond_rf = float(raw.get("conductivity_rf", 5.0))
        cond_rr = float(raw.get("conductivity_rr", 5.0))
        cond_max = max(cond_lf, cond_lr, cond_rf, cond_rr)

        values = {
            "source_adapter": "lely_horizon",
            "unit_id": raw.get("device_id", "ASTRONAUT-01"),
            "milk_yield_kg": float(raw.get("milk_yield_kg", 0.0)),
            "milk_duration_sec": int(raw.get("milking_duration_seconds", 0)),
            "box_time_sec": int(raw.get("box_time_seconds", 0)),
            "peak_flow_rate_kg_min": float(raw.get("peak_flow_rate_kg_min", 0.0)),
            "avg_flow_rate_kg_min": float(raw.get("average_flow_rate_kg_min", 0.0)),
            "cond_lf_ms_cm": cond_lf,
            "cond_lr_ms_cm": cond_lr,
            "cond_rf_ms_cm": cond_rf,
            "cond_rr_ms_cm": cond_rr,
            "cond_max_ms_cm": cond_max,
            "milk_temp_c": float(raw.get("temperature_c", 38.6)),
        }
        return ObservationRecord(
            cow_id=raw.get("animal_id"),
            ts_utc=raw.get("visit_datetime", ""),
            values=values,
            is_synthetic=True,
        )

    @staticmethod
    def normalize_collar(raw: Dict[str, Any]) -> ObservationRecord:
        """Reprocess raw Lely collar telemetry into standard ObservationRecord."""
        rum_2h = float(raw.get("rumination_minutes_2h", 0.0))
        eat_2h = float(raw.get("eating_minutes_2h", 0.0))
        act_score = float(raw.get("activity_relative_score", 0.2))

        # Map relative score to neck_imu_magnitude_mean proxy (m/s^2 baseline ~1.2 - 2.8)
        acc_proxy = round(1.2 + act_score * 3.0, 2)
        is_lying = 1 if rum_2h > 45.0 else 0

        values = {
            "source_adapter": "lely_horizon",
            "rumination_minutes": rum_2h,
            "eating_minutes": eat_2h,
            "activity_index": act_score,
            "neck_imu_magnitude_mean": acc_proxy,
            "lying": is_lying,
        }
        return ObservationRecord(
            cow_id=raw.get("animal_id"),
            ts_utc=raw.get("timestamp", ""),
            values=values,
            is_synthetic=True,
        )

    @staticmethod
    def normalize_climate(raw: Dict[str, Any]) -> ObservationRecord:
        """Reprocess raw Lely climate telemetry into standard ObservationRecord."""
        t_c = float(raw.get("temperature_c", 20.0))
        rh = float(raw.get("relative_humidity_pct", 55.0))
        thi = float(raw.get("thi", compute_thi(t_c, rh)))

        values = {
            "source_adapter": "lely_horizon",
            "indoor_temp_c": t_c,
            "indoor_rh_pct": rh,
            "indoor_thi": thi,
        }
        return ObservationRecord(
            cow_id=None,
            ts_utc=raw.get("timestamp", ""),
            values=values,
            is_synthetic=True,
        )
