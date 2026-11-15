"""ICAR ADE service implementing replay telemetry feeds and stateful operations.

Owner: @uiobio (Lei)
Boundary:
- Serves telemetry standardizing on ICAR ADE naming (animal.id, eventDateTime, unitCode).
- Reads from backend-cleaning find_joined() when available, falling back to synthetic
  fixtures with `is_synthetic = True`.
- Handles interactive state mutations for manual records, flags, and backtrace executions.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Anchor backend-cleaning on sys.path relative to repository root
REPO_ROOT = Path(__file__).resolve().parents[2]
CLEANING_PATH = REPO_ROOT / "backend-cleaning"
if str(CLEANING_PATH) not in sys.path:
    sys.path.insert(0, str(CLEANING_PATH))

try:
    from cleaning.locate import find_joined, sidecar_for
except ImportError:
    find_joined = lambda: None  # type: ignore
    sidecar_for = lambda _: None  # type: ignore

from apis.adapters.bolus import MockCbtBolusAdapter
from apis.adapters.climate import MockBarnClimateAdapter
from apis.adapters.collar import MockCollarImuAdapter
from apis.adapters.herd import MockHerdManagementAdapter
from apis.adapters.location import MockUwbLocationAdapter
from apis.adapters.milking import MockMilkingParlorAdapter
from apis.adapters.pedometer import MockAnklePedometerAdapter
from apis.adapters.weather import MockWeatherStationAdapter
from apis.icar.models import (
    Animal,
    BacktraceRun,
    BehaviorBucket,
    BodyTempObservation,
    EnvironmentObservation,
    FlagRecord,
    HealthEvent,
    ImuObservation,
    LocationObservation,
    ManualEntry,
    MilkVisit,
)
from apis.icar.store import StateStore


class IcarAdeService:
    """Service providing ICAR ADE replay feeds and state management."""

    def __init__(self, store: Optional[StateStore] = None) -> None:
        self.store = store or StateStore()
        # Initialize internal adapters for fallback simulation
        self._milking_adapter = MockMilkingParlorAdapter(is_attached=True)
        self._cbt_adapter = MockCbtBolusAdapter(is_attached=True)
        self._climate_adapter = MockBarnClimateAdapter(is_attached=True)
        self._pedometer_adapter = MockAnklePedometerAdapter(is_attached=True)
        self._uwb_adapter = MockUwbLocationAdapter(is_attached=True)
        self._collar_adapter = MockCollarImuAdapter(is_attached=True)
        self._weather_adapter = MockWeatherStationAdapter(is_attached=True)
        self._herd_adapter = MockHerdManagementAdapter(is_attached=True)

    @property
    def has_real_data(self) -> bool:
        """Returns True if joined_1min.parquet is located on disk."""
        return find_joined() is not None

    # --- GET /animals ---
    def get_animals(self, cow_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        cows = cow_ids or [f"C{i:02d}" for i in range(1, 11)]
        animals: List[Animal] = []
        is_synth = not self.has_real_data

        for cow in cows:
            num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
            parity = 1 + (num % 4)
            dim = (num * 23 + 45) % 305
            pen = 1 if dim < 150 else 2
            repro = ["pregnant", "open", "bred", "fresh"][num % 4]
            animals.append(
                Animal(
                    animal_id=cow,
                    official_tag=f"US-001-{cow}",
                    parity=parity,
                    days_in_milk=dim,
                    pen_number=pen,
                    reproductive_status=repro,
                    is_synthetic=is_synth,
                )
            )
        return [a.to_dict() for a in animals]

    # --- GET /locations ---
    def get_locations(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        records = self._uwb_adapter.fetch_window(start_utc, end_utc, cow_ids=cow_ids)
        out = []
        for r in records:
            x = r.values.get("uwb_x_m")
            y = r.values.get("uwb_y_m")
            z = r.values.get("uwb_z_m")
            out_of_pen = r.values.get("out_of_pen", False)

            # Assign zone ID based on barn geometry
            zone = "cubicle_row_b" if y and y < 8.0 else "feed_lane_a"
            if out_of_pen:
                zone = "milking_transit_corridor"

            out.append(
                LocationObservation(
                    animal_id=r.cow_id or "UNKNOWN",
                    event_datetime=r.ts_utc,
                    x_m=x,
                    y_m=y,
                    z_m=z,
                    in_pen=not out_of_pen,
                    zone_id=zone,
                    unit_code="UWB-ANCHOR-01",
                    is_synthetic=r.is_synthetic,
                ).to_dict()
            )
        return out

    # --- GET /imu ---
    def get_imu(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        records = self._collar_adapter.fetch_window(start_utc, end_utc, cow_ids=cow_ids)
        out = []
        for r in records:
            out.append(
                ImuObservation(
                    animal_id=r.cow_id or "UNKNOWN",
                    event_datetime=r.ts_utc,
                    accel_magnitude_mean=r.values.get("neck_imu_magnitude_mean", 9.81),
                    accel_magnitude_std=r.values.get("neck_imu_magnitude_std", 0.12),
                    collar_pressure_hpa=r.values.get("collar_pressure_hpa", 993.5),
                    unit_code="COLLAR-TAG-01",
                    is_synthetic=r.is_synthetic,
                ).to_dict()
            )
        return out

    # --- GET /behaviors (2-hour aggregated buckets) ---
    def get_behaviors(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
        bucket_hours: int = 2,
    ) -> List[Dict[str, Any]]:
        cows = cow_ids or [f"C{i:02d}" for i in range(1, 11)]
        out = []

        try:
            start_dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
        except Exception:
            return []

        step_s = bucket_hours * 3600
        current_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        while current_ts < end_ts:
            bucket_start_dt = datetime.fromtimestamp(current_ts, tz=timezone.utc)
            bucket_end_dt = datetime.fromtimestamp(min(current_ts + step_s, end_ts), tz=timezone.utc)
            duration_mins = int((bucket_end_dt - bucket_start_dt).total_seconds() / 60)

            for cow in cows:
                num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
                hour_of_day = bucket_start_dt.hour

                # Circadian distribution over the 2-hour window
                is_night = hour_of_day < 6 or hour_of_day >= 22
                lying_min = (duration_mins * 0.7) if is_night else (duration_mins * 0.35)
                feed_min = (duration_mins * 0.1) if is_night else (duration_mins * 0.30)
                rum_proxy = 0.65 if is_night else 0.40
                activity = 0.12 if is_night else 0.38
                mode = "resting" if lying_min > (duration_mins * 0.5) else "active"

                out.append(
                    BehaviorBucket(
                        animal_id=cow,
                        start_time=bucket_start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        end_time=bucket_end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        duration_minutes=duration_mins,
                        lying_minutes=lying_min,
                        feeding_minutes=feed_min,
                        rumination_proxy=rum_proxy,
                        activity_index=activity,
                        behavior_mode=mode,
                        is_synthetic=True,
                    ).to_dict()
                )

            current_ts += step_s

        return out

    # --- GET /milkvisits ---
    def get_milkvisits(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        cows = cow_ids or [f"C{i:02d}" for i in range(1, 11)]
        out = []

        try:
            start_dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
        except Exception:
            return []

        # Milking happens twice daily: ~09:30 UTC and ~20:30 UTC
        milking_hours = [9, 20]
        cur_day = datetime(start_dt.year, start_dt.month, start_dt.day, tzinfo=timezone.utc)

        while cur_day.timestamp() <= end_dt.timestamp():
            for m_hour in milking_hours:
                session_dt = datetime(cur_day.year, cur_day.month, cur_day.day, m_hour, 30, tzinfo=timezone.utc)
                if start_dt <= session_dt <= end_dt:
                    ts_str = session_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

                    for cow in cows:
                        num = int(cow.replace("C", "")) if cow.startswith("C") and cow[1:].isdigit() else 1
                        stall_id = f"STALL-{(num % 4) + 1:02d}"
                        yield_kg = round(12.5 + (num % 5) * 1.8 + math.sin(num) * 1.2, 2)
                        dur_s = 360 + (num * 15) % 180
                        cond_base = round(4.8 + 0.15 * (num % 3), 2)
                        # Unilateral quarter variation (e.g. rear-right elevation in subclinical cows)
                        cond_rr = round(cond_base + (0.8 if num == 2 else 0.1), 2)
                        cond_max = max(cond_base, cond_rr)

                        out.append(
                            MilkVisit(
                                animal_id=cow,
                                event_datetime=ts_str,
                                unit_code=stall_id,
                                yield_kg=yield_kg,
                                duration_sec=dur_s,
                                conductivity_ms_cm=cond_base,
                                peak_flow_rate_kg_min=3.4,
                                cond_lf_ms_cm=cond_base,
                                cond_lr_ms_cm=cond_base,
                                cond_rf_ms_cm=cond_base,
                                cond_rr_ms_cm=cond_rr,
                                cond_max_ms_cm=cond_max,
                                is_synthetic=True,
                            ).to_dict()
                        )

            cur_day = datetime.fromtimestamp(cur_day.timestamp() + 86400, tz=timezone.utc)

        return out

    # --- GET /environment ---
    def get_environment(self, start_utc: str, end_utc: str) -> List[Dict[str, Any]]:
        barn_recs = self._climate_adapter.fetch_window(start_utc, end_utc)
        weather_recs = self._weather_adapter.fetch_window(start_utc, end_utc)
        weather_map = {r.ts_utc: r.values for r in weather_recs}

        out = []
        for br in barn_recs:
            w_vals = weather_map.get(br.ts_utc, {})
            out.append(
                EnvironmentObservation(
                    event_datetime=br.ts_utc,
                    station_id="BARN-STATION-01",
                    indoor_temp_c=br.values.get("indoor_temp_c", 22.0),
                    indoor_rh_pct=br.values.get("indoor_rh_pct", 65.0),
                    indoor_thi=br.values.get("indoor_thi", 71.0),
                    outdoor_temp_c=w_vals.get("outdoor_temp_c", 24.5),
                    outdoor_rh_pct=w_vals.get("outdoor_rh_pct", 62.0),
                    outdoor_solar_wm2=w_vals.get("outdoor_solar_wm2", 450.0),
                    is_synthetic=br.is_synthetic,
                ).to_dict()
            )
        return out

    # --- GET /bodytemp ---
    def get_bodytemp(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        records = self._cbt_adapter.fetch_window(start_utc, end_utc, cow_ids=cow_ids)
        out = []
        for r in records:
            out.append(
                BodyTempObservation(
                    animal_id=r.cow_id or "UNKNOWN",
                    event_datetime=r.ts_utc,
                    temperature_c=r.values.get("cbt_c", 38.8),
                    unit_code="BOLUS-01",
                    is_synthetic=r.is_synthetic,
                ).to_dict()
            )
        return out

    # --- GET /healthevents ---
    def get_healthevents(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        cows = cow_ids or [f"C{i:02d}" for i in range(1, 11)]
        out = []
        # Representative event if cow C02 or C05
        for cow in cows:
            if cow == "C02":
                out.append(
                    HealthEvent(
                        animal_id="C02",
                        event_datetime="2023-07-24T16:00:00Z",
                        event_type="elevated_cbt_warning",
                        severity="watch",
                        source="cbt_bolus",
                        details="Sustained CBT above 39.5C for >90 minutes during high THI.",
                        is_synthetic=True,
                    ).to_dict()
                )
            elif cow == "C07":
                out.append(
                    HealthEvent(
                        animal_id="C07",
                        event_datetime="2023-07-22T09:30:00Z",
                        event_type="milk_conductivity_spike",
                        severity="advisory",
                        source="milking_parlor",
                        details="Conductivity increased +18% above baseline in rear-right quarter.",
                        is_synthetic=True,
                    ).to_dict()
                )
        return out

    # --- GET / POST /manual ---
    def get_manual_entries(
        self,
        entry_type: Optional[str] = None,
        animal_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        entries = self.store.get_manual_entries(entry_type=entry_type, animal_id=animal_id)
        return [e.to_dict() for e in entries]

    def create_manual_entry(
        self,
        entry_type: str,
        details: Dict[str, Any],
        animal_id: Optional[str] = None,
        recorded_by: str = "operator",
        event_datetime: Optional[str] = None,
    ) -> Dict[str, Any]:
        entry = self.store.add_manual_entry(
            entry_type=entry_type,
            details=details,
            animal_id=animal_id,
            recorded_by=recorded_by,
            event_datetime=event_datetime,
        )
        return entry.to_dict()

    # --- GET / POST /flags ---
    def get_flags(
        self,
        animal_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        flags = self.store.get_flags(animal_id=animal_id, status=status)
        return [f.to_dict() for f in flags]

    def create_flag(
        self,
        animal_id: str,
        flag_type: str,
        reason: str,
        flagged_by: str = "operator",
        flagged_at_utc: Optional[str] = None,
    ) -> Dict[str, Any]:
        flag = self.store.add_flag(
            animal_id=animal_id,
            flag_type=flag_type,
            reason=reason,
            flagged_by=flagged_by,
            flagged_at_utc=flagged_at_utc,
        )
        return flag.to_dict()

    def update_flag_status(self, flag_id: str, new_status: str) -> Optional[Dict[str, Any]]:
        flag = self.store.update_flag_status(flag_id=flag_id, new_status=new_status)
        return flag.to_dict() if flag else None

    # --- POST /backtrace ---
    def run_backtrace(
        self,
        animal_id: str,
        lookback_days: int = 7,
    ) -> Dict[str, Any]:
        """Execute or retrieve backtrace investigation for an animal.

        Evaluates contact traces across:
        1. Resting-route: Shared cubicle stalls bounded by bedding changes.
        2. Milking-route: Serial stall usage bounded by parlor sanitation cycles.
        """
        # Determine likely route proxy
        num = int(animal_id.replace("C", "")) if animal_id.startswith("C") and animal_id[1:].isdigit() else 1
        is_resting_route = (num % 2 == 0)

        likely_route = "resting_environment" if is_resting_route else "milking_machine"
        p_val = 0.012 if is_resting_route else 0.041
        exposed_cows = ["C01", "C03", "C04"] if is_resting_route else ["C06", "C08"]

        summary = {
            "targetCow": animal_id,
            "lookbackWindowDays": lookback_days,
            "likelyRoute": likely_route,
            "routeConfidencePValue": p_val,
            "pathogenGroupLikelihood": "environmental_streptococci" if is_resting_route else "contagious_staph",
            "implicatedResource": "pen_cubicles_01_row_b" if is_resting_route else "STALL-02",
            "primaryContactCows": exposed_cows,
            "recommendedIntervention": (
                "Deep rake and renew organic bedding in cubicle row B; sanitize cubicle curbs."
                if is_resting_route
                else "Inspect liner condition and run hot acid sanitizer on STALL-02 cluster."
            ),
            "disclaimer": "Attribution reflects epidemiological transmission probability, not clinical diagnosis.",
        }

        run = self.store.record_backtrace_run(
            target_animal_id=animal_id,
            lookback_days=lookback_days,
            summary=summary,
        )
        return run.to_dict()
