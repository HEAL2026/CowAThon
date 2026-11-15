"""Merck Animal Health / Allflex SenseHub Dairy API adapter and normalizer.

Maps SenseHub Dairy REST API & DataFlow II telemetry to mmcows schema:
- cSense Flex collars & eSense Flex ear tags (/activities, /health-monitoring)
- FreeFlow parlor & rotary carousel milk meters (/milk-sessions)
- In-Barn Climate & THI monitoring (/climate/ambient)
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


class SenseHubAdapter(BaseAdapter):
    """Adapter for Merck Animal Health SenseHub Cloud API."""

    def __init__(
        self,
        is_attached: bool = True,
        api_base_url: str = "https://api.sensehub.merck.com/v1",
        herd_id: str = "HERD-SENSEHUB-01",
    ) -> None:
        super().__init__(is_attached=is_attached)
        self.api_base_url = api_base_url
        self.herd_id = herd_id
        self._metadata = SystemMetadata(
            adapter_id="merck_sensehub",
            name="SenseHub Dairy (cSense / eSense / FreeFlow)",
            vendor="Merck Animal Health / Allflex Livestock Intelligence",
            system_category="collar_ear_milking",
            signals=[
                "rumination_minutes",
                "eating_minutes",
                "resting_minutes",
                "activity_index",
                "panting_minutes",
                "milk_yield_kg",
                "milk_duration_sec",
                "peak_flow_rate_kg_min",
                "conductivity_ms_cm",
                "cond_lf_ms_cm",
                "cond_lr_ms_cm",
                "cond_rf_ms_cm",
                "cond_rr_ms_cm",
                "indoor_temp_c",
                "indoor_rh_pct",
                "indoor_thi",
            ],
            cadence="per_visit_and_20min",
            is_animal_level=True,
            cost_profile=CostProfile(
                annual_cost_per_head_usd=42.0,
                hardware_setup_cost_usd=12000.0,
                feasibility_tier=FeasibilityTier.RECOMMENDED,
                recommended_min_herd_size=50,
                roi_summary="cSense/eSense rumination and heat monitoring paired with FreeFlow parlor yield meters.",
            ),
            documentation_url="https://www.allflex.global/dairy/monitoring/",
        )

    @property
    def metadata(self) -> SystemMetadata:
        return self._metadata

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            adapter_id="merck_sensehub",
            status=HealthStatus.ATTACHED if self._is_attached else HealthStatus.DETACHED,
            is_attached=self._is_attached,
            is_healthy=self._is_attached,
            is_synthetic=True,
            message="Connected to SenseHub Dairy Cloud mock stream" if self._is_attached else "Detached",
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

        # 1. Rotary Milking Sessions (~09:30 and ~20:30 UTC)
        cur_day = datetime(start_dt.year, start_dt.month, start_dt.day, tzinfo=timezone.utc)
        while cur_day.timestamp() <= end_dt.timestamp():
            for m_hour in [9, 20]:
                session_dt = datetime(cur_day.year, cur_day.month, cur_day.day, m_hour, 30, tzinfo=timezone.utc)
                if start_dt <= session_dt <= end_dt:
                    ts_str = session_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    for cow in cows:
                        num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
                        raw_payload = self._mock_sensehub_raw_milking(cow, ts_str, num)
                        norm_rec = self.normalize_milking(raw_payload)
                        records.append(norm_rec)
            cur_day = datetime.fromtimestamp(cur_day.timestamp() + 86400, tz=timezone.utc)

        # 2. Activity / Rumination telemetry (2-hour buckets)
        step_s = 7200
        cur_ts = start_dt.timestamp()
        while cur_ts < end_dt.timestamp():
            b_dt = datetime.fromtimestamp(cur_ts, tz=timezone.utc)
            ts_str = b_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            for cow in cows:
                num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
                raw_act = self._mock_sensehub_raw_activity(cow, ts_str, num)
                norm_act = self.normalize_activity(raw_act)
                records.append(norm_act)
            cur_ts += step_s

        # 3. Ambient Barn Climate (1-hour intervals)
        step_clim = 3600
        cur_ts = start_dt.timestamp()
        while cur_ts < end_dt.timestamp():
            c_dt = datetime.fromtimestamp(cur_ts, tz=timezone.utc)
            ts_str = c_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            raw_clim = self._mock_sensehub_raw_climate(ts_str)
            norm_clim = self.normalize_climate(raw_clim)
            records.append(norm_clim)
            cur_ts += step_clim

        return records

    # --- Raw Mock Generators ---
    def _mock_sensehub_raw_milking(self, cow_id: str, ts_utc: str, cow_num: int) -> Dict[str, Any]:
        """Raw FreeFlow rotary parlor session JSON payload."""
        stall_id = f"ROTARY-BAIL-{(cow_num * 3) % 24 + 1:02d}"
        yield_kg = round(13.2 + (cow_num % 5) * 1.4, 2)
        cond_base = round(4.90 + 0.12 * (cow_num % 3), 2)
        return {
            "cow_id": cow_id,
            "milking_time": ts_utc,
            "parlor_stall_id": stall_id,
            "meter_type": "FreeFlow_Optical",
            "yield_kg": yield_kg,
            "duration_sec": 390 + (cow_num * 12) % 150,
            "flow_rate_peak_kg_min": round(4.1 + (cow_num % 4) * 0.3, 2),
            "conductivity_ms_cm": cond_base,
            "cond_lf": round(cond_base - 0.05, 2),
            "cond_lr": round(cond_base + 0.05, 2),
            "cond_rf": round(cond_base, 2),
            "cond_rr": round(cond_base + 0.10, 2),
            "temperature_c": round(38.7 + 0.1 * (cow_num % 2), 2),
        }

    def _mock_sensehub_raw_activity(self, cow_id: str, ts_utc: str, cow_num: int) -> Dict[str, Any]:
        """Raw SenseHub GET /activities JSON payload."""
        hour = int(ts_utc[11:13]) if len(ts_utc) >= 13 else 12
        is_night = hour < 6 or hour >= 22
        rum_min = 60.0 if is_night else 30.0
        eat_min = 10.0 if is_night else 45.0
        rest_min = 45.0 if is_night else 25.0
        act_score = 15.0 if is_night else 55.0
        return {
            "cow_id": cow_id,
            "timestamp_utc": ts_utc,
            "device_model": "cSense_Flex",
            "rumination_minutes_2h": rum_min,
            "eating_minutes_2h": eat_min,
            "resting_minutes_2h": rest_min,
            "activity_score": act_score,
            "panting_minutes_2h": 4.5 if not is_night else 0.5,
            "heat_index_prob": round(0.05 + 0.02 * (cow_num % 4), 3),
        }

    def _mock_sensehub_raw_climate(self, ts_utc: str) -> Dict[str, Any]:
        """Raw SenseHub GET /climate/ambient JSON payload."""
        hour = int(ts_utc[11:13]) if len(ts_utc) >= 13 else 12
        temp_c = round(21.0 + 4.5 * math.sin((hour - 8) / 24.0 * 2 * math.pi), 1)
        rh_pct = round(60.0 - 12.0 * math.sin((hour - 8) / 24.0 * 2 * math.pi), 1)
        return {
            "sensor_id": "SENSEHUB-BARN-THI-01",
            "timestamp_utc": ts_utc,
            "temp_c": temp_c,
            "rh_percent": rh_pct,
            "thi": compute_thi(temp_c, rh_pct),
        }

    # --- Normalizers ---
    @staticmethod
    def normalize_milking(raw: Dict[str, Any]) -> ObservationRecord:
        cond_lf = float(raw.get("cond_lf", raw.get("conductivity_ms_cm", 5.0)))
        cond_lr = float(raw.get("cond_lr", raw.get("conductivity_ms_cm", 5.0)))
        cond_rf = float(raw.get("cond_rf", raw.get("conductivity_ms_cm", 5.0)))
        cond_rr = float(raw.get("cond_rr", raw.get("conductivity_ms_cm", 5.0)))
        cond_max = max(cond_lf, cond_lr, cond_rf, cond_rr)

        values = {
            "source_adapter": "merck_sensehub",
            "unit_id": raw.get("parlor_stall_id", "ROTARY-01"),
            "milk_yield_kg": float(raw.get("yield_kg", 0.0)),
            "milk_duration_sec": int(raw.get("duration_sec", 0)),
            "peak_flow_rate_kg_min": float(raw.get("flow_rate_peak_kg_min", 0.0)),
            "conductivity_ms_cm": float(raw.get("conductivity_ms_cm", cond_max)),
            "cond_lf_ms_cm": cond_lf,
            "cond_lr_ms_cm": cond_lr,
            "cond_rf_ms_cm": cond_rf,
            "cond_rr_ms_cm": cond_rr,
            "cond_max_ms_cm": cond_max,
            "milk_temp_c": float(raw.get("temperature_c", 38.6)),
        }
        return ObservationRecord(
            cow_id=raw.get("cow_id"),
            ts_utc=raw.get("milking_time", ""),
            values=values,
            is_synthetic=True,
        )

    @staticmethod
    def normalize_activity(raw: Dict[str, Any]) -> ObservationRecord:
        rum_2h = float(raw.get("rumination_minutes_2h", 0.0))
        eat_2h = float(raw.get("eating_minutes_2h", 0.0))
        rest_2h = float(raw.get("resting_minutes_2h", 0.0))
        act_score = float(raw.get("activity_score", 30.0))

        norm_act_idx = round(act_score / 100.0, 3)
        acc_proxy = round(1.2 + norm_act_idx * 3.2, 2)
        is_lying = 1 if rest_2h > 35.0 else 0

        values = {
            "source_adapter": "merck_sensehub",
            "rumination_minutes": rum_2h,
            "eating_minutes": eat_2h,
            "resting_minutes": rest_2h,
            "activity_index": norm_act_idx,
            "panting_minutes": float(raw.get("panting_minutes_2h", 0.0)),
            "neck_imu_magnitude_mean": acc_proxy,
            "lying": is_lying,
        }
        return ObservationRecord(
            cow_id=raw.get("cow_id"),
            ts_utc=raw.get("timestamp_utc", ""),
            values=values,
            is_synthetic=True,
        )

    @staticmethod
    def normalize_climate(raw: Dict[str, Any]) -> ObservationRecord:
        t_c = float(raw.get("temp_c", 20.0))
        rh = float(raw.get("rh_percent", 55.0))
        thi = float(raw.get("thi", compute_thi(t_c, rh)))

        values = {
            "source_adapter": "merck_sensehub",
            "indoor_temp_c": t_c,
            "indoor_rh_pct": rh,
            "indoor_thi": thi,
        }
        return ObservationRecord(
            cow_id=None,
            ts_utc=raw.get("timestamp_utc", ""),
            values=values,
            is_synthetic=True,
        )
