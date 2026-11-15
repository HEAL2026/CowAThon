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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Anchor backend-cleaning and backend-analysis on sys.path relative to repository root
REPO_ROOT = Path(__file__).resolve().parents[2]
CLEANING_PATH = REPO_ROOT / "backend-cleaning"
if str(CLEANING_PATH) not in sys.path:
    sys.path.insert(0, str(CLEANING_PATH))

ANALYSIS_PATH = REPO_ROOT / "backend-analysis"
if str(ANALYSIS_PATH) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_PATH))

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
    RestingSpot,
    SanitationRecord,
)
from apis.icar.store import StateStore


def _read_cleaning_table(rel_path: str) -> Optional[Any]:
    """Safely load parquet table from backend-cleaning/data with None fallback."""
    try:
        import pandas as pd
        path = CLEANING_PATH / "data" / rel_path
        if path.is_file():
            return pd.read_parquet(path)
    except Exception:
        pass
    return None


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
        kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        entry = self.store.add_manual_entry(
            entry_type=entry_type,
            details=details,
            animal_id=animal_id,
            recorded_by=recorded_by,
            event_datetime=event_datetime,
            kind=kind,
        )
        return entry.to_dict()

    # --- GET / POST /sanitation ---
    def get_sanitation_records(
        self,
        unit_id: Optional[str] = None,
        kind: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        records = self.store.get_sanitation_records(unit_id=unit_id, kind=kind, session_id=session_id)
        return [r.to_dict() for r in records]

    def create_sanitation_record(
        self,
        unit_id: str,
        sanitized_at: str,
        session_id: str,
        kind: str = "end_of_session",
        is_synthetic: bool = True,
    ) -> Dict[str, Any]:
        record = self.store.add_sanitation_record(
            unit_id=unit_id,
            sanitized_at=sanitized_at,
            session_id=session_id,
            kind=kind,
            is_synthetic=is_synthetic,
        )
        return record.to_dict()

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

    def create_flags(
        self,
        animal_ids: List[str],
        flag_type: str,
        reason: str,
        flagged_by: str = "operator",
        flagged_at_utc: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        flags = self.store.add_flags(
            animal_ids=animal_ids,
            flag_type=flag_type,
            reason=reason,
            flagged_by=flagged_by,
            flagged_at_utc=flagged_at_utc,
        )
        return [f.to_dict() for f in flags]

    def update_flag_status(self, flag_id: str, new_status: str) -> Optional[Dict[str, Any]]:
        flag = self.store.update_flag_status(flag_id=flag_id, new_status=new_status)
        return flag.to_dict() if flag else None

    # --- POST /backtrace ---
    def run_backtrace(
        self,
        animal_id: Union[str, List[str]],
        lookback_days: int = 7,
    ) -> Dict[str, Any]:
        """Execute or retrieve backtrace investigation for single or multiple animals (spec v2).

        Loads real tables (lying_bouts.parquet, resting_spots.parquet, milking_log.parquet,
        sanitation.parquet, bedding_synthetic.parquet) from backend-cleaning/data/ and delegates
        to backend-analysis S11 backtrace contract, falling back to deterministic synthetic tracing if offline.
        Surfaces spec v2 Section 6 resources (resting_spots carrying spot_id and milking_units)
        and preserves legacy ICAR backwards compatibility.
        """
        raw_targets = [animal_id] if isinstance(animal_id, str) else list(animal_id)
        target_cows: List[str] = []
        for item in raw_targets:
            if isinstance(item, list):
                target_cows.extend([str(x) for x in item])
            elif item is not None:
                target_cows.append(str(item))
        if not target_cows:
            target_cows = ["C02"]
        primary_target = str(target_cows[0])

        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        window_start_iso = (now_utc - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. Load real and synthetic tables from backend-cleaning/data/
        lying_bouts_df = _read_cleaning_table("processed/lying_bouts.parquet")
        resting_spots_df = _read_cleaning_table("processed/resting_spots.parquet")
        milking_log_df = _read_cleaning_table("synthetic/milking_log.parquet")
        sanitation_df = _read_cleaning_table("synthetic/sanitation.parquet")
        bedding_df = _read_cleaning_table("synthetic/bedding_synthetic.parquet")

        has_real_bouts = lying_bouts_df is not None and len(lying_bouts_df) > 0
        has_real_spots = resting_spots_df is not None and len(resting_spots_df) > 0

        # 2. Attempt delegation to backend-analysis S11 backtrace
        res = None
        try:
            from analysis.backtrace import backtrace as analysis_backtrace

            active_flags = self.store.get_flags(status="active")
            flags_input: List[Dict[str, Any]] = []
            seen_cows = set()

            for cow in target_cows:
                target_flag = next((f for f in active_flags if f.animal_id == cow), None)
                target_ts = target_flag.flagged_at_utc if target_flag else now_iso
                flags_input.append({
                    "cow_id": cow,
                    "animal_id": cow,
                    "dx_utc": target_ts,
                    "timestamp": target_ts,
                })
                seen_cows.add(cow)

            for f in active_flags:
                if f.animal_id not in seen_cows:
                    flags_input.append({
                        "cow_id": f.animal_id,
                        "animal_id": f.animal_id,
                        "dx_utc": f.flagged_at_utc,
                        "timestamp": f.flagged_at_utc,
                    })
                    seen_cows.add(f.animal_id)

            res = analysis_backtrace(
                flags=flags_input,
                lying_bouts_df=lying_bouts_df,
                milking_log_df=milking_log_df,
                sanitation_df=sanitation_df,
                bedding_df=bedding_df,
                lookback_hours=lookback_days * 24,
            )
        except Exception:
            res = None

        # 3. Construct resting_spots resource layer (docs/backtrace_spec.md §3.2, §6)
        resting_spots: List[Dict[str, Any]] = []
        if res and "resources" in res and isinstance(res["resources"], dict) and res["resources"].get("resting_spots"):
            resting_spots = res["resources"]["resting_spots"]
        elif has_real_spots:
            # Assign bouts to resting spots using assign_spots or spatial distance
            b_assigned = None
            if has_real_bouts:
                try:
                    from cleaning.bouts import assign_spots
                    b_assigned = assign_spots(lying_bouts_df, resting_spots_df)
                except Exception:
                    b_assigned = None

            until_bedding_iso = "2023-07-28T14:00:00Z"
            if bedding_df is not None and "changed_at" in bedding_df.columns and len(bedding_df) > 0:
                try:
                    until_bedding_iso = pd.to_datetime(bedding_df["changed_at"]).max().strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    pass

            for _, spot_row in resting_spots_df.iterrows():
                sid = str(spot_row["spot_id"])
                cx = round(float(spot_row["center_x_m"]), 2)
                cy = round(float(spot_row["center_y_m"]), 2)
                rad = float(spot_row.get("radius_m", 1.5))
                n_bouts = int(spot_row.get("n_bouts", 0))
                n_cows = int(spot_row.get("n_cows", 0))
                dwell_min = float(spot_row.get("dwell_min", 0.0))

                fcows: List[str] = []
                dwell_by_f: Dict[str, float] = {}
                successors: List[Dict[str, Any]] = []

                if has_real_bouts and b_assigned is not None:
                    spot_bouts = lying_bouts_df[b_assigned == sid].sort_values("start_utc").reset_index(drop=True)
                    f_bouts = spot_bouts[spot_bouts["cow_id"].isin(target_cows)]
                    fcows = sorted(list(f_bouts["cow_id"].unique()))
                    for cid, grp in f_bouts.groupby("cow_id"):
                        dwell_by_f[str(cid)] = round(float(grp["duration_min"].sum()), 1)

                    seen_succ = set()
                    for idx, row in spot_bouts.iterrows():
                        if row["cow_id"] in target_cows:
                            t_end = row["end_utc"]
                            rank = 1
                            for j in range(idx + 1, min(idx + 6, len(spot_bouts))):
                                next_bout = spot_bouts.iloc[j]
                                nid = str(next_bout["cow_id"])
                                if nid not in target_cows and nid not in seen_succ:
                                    try:
                                        lag = (next_bout["start_utc"] - t_end).total_seconds() / 3600.0
                                    except Exception:
                                        lag = 1.0
                                    if 0 <= lag <= 72.0:
                                        successors.append({
                                            "cow_id": nid,
                                            "rank": rank,
                                            "lag_h": round(float(lag), 1),
                                            "w": round(2.0 ** (-(rank - 1)), 2),
                                        })
                                        seen_succ.add(nid)
                                        rank += 1
                else:
                    fcows = [c for c in target_cows if sid in ("spot_01", "spot_02")]
                    dwell_by_f = {c: 120.0 for c in fcows}

                spot_obj = RestingSpot(
                    spot_id=sid,
                    center_x_m=cx,
                    center_y_m=cy,
                    radius_m=rad,
                    n_flagged=len(fcows),
                    flagged_cows=fcows,
                    dwell_min_by_flagged=dwell_by_f,
                    successors=successors,
                    until_bedding_change_utc=until_bedding_iso,
                    provenance="real",
                    n_bouts=n_bouts,
                    n_cows=n_cows,
                    dwell_min=dwell_min,
                    is_synthetic=False,
                )
                resting_spots.append(spot_obj.to_dict())
        else:
            # Deterministic synthetic 5-spot fallback around y ≈ 0 (spec v2 Section 3.2, 6)
            canonical_spots = [
                ("spot_01", 0.06, -0.00, 10, 41206.0),
                ("spot_02", -2.82, 0.02, 10, 35503.0),
                ("spot_03", 4.33, -0.04, 10, 16635.0),
                ("spot_04", 2.55, -0.02, 10, 11804.0),
                ("spot_05", -1.16, 0.02, 2, 410.0),
            ]
            for sid, cx, cy, nc, dw in canonical_spots:
                fcows = [c for c in target_cows if sid in ("spot_01", "spot_02")]
                spot_obj = RestingSpot(
                    spot_id=sid,
                    center_x_m=cx,
                    center_y_m=cy,
                    radius_m=1.5,
                    n_flagged=len(fcows),
                    flagged_cows=fcows,
                    dwell_min_by_flagged={c: 120.0 for c in fcows},
                    successors=[],
                    until_bedding_change_utc="2023-07-28T14:00:00Z",
                    provenance="synthetic",
                    n_bouts=50,
                    n_cows=nc,
                    dwell_min=dw,
                    is_synthetic=True,
                )
                resting_spots.append(spot_obj.to_dict())

        # 4. Construct milking_units resource layer (docs/backtrace_spec.md §3.3, §6)
        milking_units: List[Dict[str, Any]] = []
        if res and "resources" in res and isinstance(res["resources"], dict) and res["resources"].get("milking_units"):
            milking_units = res["resources"]["milking_units"]
        elif milking_log_df is not None and len(milking_log_df) > 0:
            all_units = sorted(milking_log_df["unit_id"].unique().tolist())
            for uid in all_units:
                u_milks = milking_log_df[milking_log_df["unit_id"] == uid]
                u_flagged = u_milks[u_milks["cow_id"].isin(target_cows)]
                fcows = sorted(u_flagged["cow_id"].unique().tolist())
                sessions = sorted(u_flagged["session_id"].unique().tolist())

                # Check between-cow sanitation on this unit
                sanitized_between = False
                if sanitation_df is not None and "kind" in sanitation_df.columns:
                    u_san = sanitation_df[(sanitation_df["unit_id"] == uid) & (sanitation_df["kind"] == "between_cows")]
                    sanitized_between = len(u_san) > 0

                u_successors: List[Dict[str, Any]] = []
                seen_succ_u = set()
                for sid in sessions:
                    s_milks = u_milks[u_milks["session_id"] == sid].sort_values("order_in_session").reset_index(drop=True)
                    is_clean_sess = False
                    if sanitation_df is not None and "kind" in sanitation_df.columns:
                        s_san = sanitation_df[
                            (sanitation_df["unit_id"] == uid)
                            & (sanitation_df["session_id"] == sid)
                            & (sanitation_df["kind"] == "between_cows")
                        ]
                        is_clean_sess = len(s_san) > 0

                    for idx, row in s_milks.iterrows():
                        if row["cow_id"] in target_cows:
                            rank = 1
                            for j in range(idx + 1, len(s_milks)):
                                next_row = s_milks.iloc[j]
                                nid = str(next_row["cow_id"])
                                if nid not in target_cows and nid not in seen_succ_u:
                                    w = 0.0 if is_clean_sess else round(2.0 ** (-(rank - 1)), 2)
                                    u_successors.append({
                                        "cow_id": nid,
                                        "rank": rank,
                                        "session_id": sid,
                                        "w": w,
                                    })
                                    seen_succ_u.add(nid)
                                    rank += 1

                milking_units.append({
                    "unit_id": str(uid),
                    "n_flagged": len(fcows),
                    "flagged_cows": fcows,
                    "sessions": sessions,
                    "successors": u_successors,
                    "sanitized_between": sanitized_between,
                    "provenance": "synthetic",
                    "is_synthetic": True,
                })
        else:
            for s in range(1, 5):
                uid = f"U{s}"
                fcows = [c for c in target_cows if s == 2]
                milking_units.append({
                    "unit_id": uid,
                    "n_flagged": len(fcows),
                    "flagged_cows": fcows,
                    "sessions": ["2023-07-29_PM"],
                    "successors": [],
                    "sanitized_between": (s != 2),
                    "provenance": "synthetic",
                    "is_synthetic": True,
                })

        # 5. Route attribution and p-values
        if res:
            route = res.get("likely_route", "resting_environment")
            route_p_vals = res.get("route_p_values") or res.get("p_values") or {}
            p_rest = float(route_p_vals.get("resting_p_value", route_p_vals.get("resting_route", 0.02)))
            p_milk = float(route_p_vals.get("milking_p_value", route_p_vals.get("milking_equipment", 0.50)))
            p_val = min(p_rest, p_milk)
            z_rest = float(res.get("z_rest", 1.59 if "resting" in route else 0.0))
            z_milk = float(res.get("z_milk", 2.13 if "milking" in route else 0.0))
            exposed_raw = res.get("exposed_cows") or res.get("high_risk_contacts") or []
            exposed_cows = [
                {
                    "cow_id": c["cow_id"] if isinstance(c, dict) else str(c),
                    "e": float(c.get("exposure_score", 0.8)) if isinstance(c, dict) else 0.8,
                    "e_rest": float(c.get("resting_score", 0.8)) if isinstance(c, dict) else 0.8,
                    "e_milk": float(c.get("milking_score", 0.0)) if isinstance(c, dict) else 0.0,
                    "tier": "high" if (isinstance(c, dict) and c.get("exposure_score", 0.8) >= 0.5) else "moderate",
                    "primary_route": route,
                    "via": c.get("via", []) if isinstance(c, dict) else [],
                }
                for c in exposed_raw
            ]
        else:
            num = int(primary_target.replace("C", "")) if primary_target.startswith("C") and primary_target[1:].isdigit() else 1
            is_resting_route = (num % 2 == 0)
            route = "resting_environment" if is_resting_route else "milking_machine"
            p_rest = 0.012 if is_resting_route else 0.45
            p_milk = 0.45 if is_resting_route else 0.041
            p_val = min(p_rest, p_milk)
            z_rest = 1.59 if is_resting_route else -0.34
            z_milk = -0.34 if is_resting_route else 2.13
            exposed_ids = ["C01", "C03", "C04"] if is_resting_route else ["C06", "C08"]
            exposed_cows = [
                {
                    "cow_id": cid,
                    "e": 0.8,
                    "e_rest": 0.8 if is_resting_route else 0.0,
                    "e_milk": 0.0 if is_resting_route else 0.8,
                    "tier": "high",
                    "primary_route": route,
                    "via": [],
                }
                for cid in exposed_ids
            ]

        # Canonical route name
        likely_route_canonical = "resting_area" if "resting" in route else ("milking_equipment" if "milking" in route else route)

        # 6. Investigation window & flagged cows per Section 6
        investigation_window = {
            "start_utc": window_start_iso,
            "end_utc": now_iso,
            "anchor": "flagged_at",
        }
        flagged_cows_spec = [
            {
                "cow_id": c,
                "role": "index" if i == 0 else "secondary",
                "flagged_at": now_iso,
            }
            for i, c in enumerate(target_cows)
        ]

        route_spec = {
            "likely_route": likely_route_canonical,
            "z_rest": round(z_rest, 2),
            "z_milk": round(z_milk, 2),
            "p_rest": round(p_rest, 3),
            "p_milk": round(p_milk, 3),
            "p_floor": 0.012,
            "n_permutations": 200 if res else 0,
        }

        provenance_spec = {
            "lying_bouts": "real" if has_real_bouts else "synthetic",
            "milking_log": "synthetic",
            "sanitation": "synthetic",
            "bedding": "synthetic",
        }

        contact_cow_ids = [c["cow_id"] for c in exposed_cows]

        primary_resource_label = (
            f"Resting Spot {resting_spots[0]['spot_id']} (x={resting_spots[0]['center_x_m']}m, y={resting_spots[0]['center_y_m']}m, r=1.5m)"
            if resting_spots and "resting" in route
            else (milking_units[0]["unit_id"] if milking_units and "milking" in route else "STALL-01")
        )

        recommended_actions = (
            [
                "Deep clean and apply lime/disinfectant bedding powder to implicated 1.5m resting circles; replace organic bedding.",
                "Verify stall curb cleanliness and ensure proper bedding drainage.",
            ]
            if "resting" in route
            else [
                "Inspect teat cup liner condition and vacuum stability on implicated milking units.",
                "Enforce automatic cluster backflush / hot water acid disinfection between milkings.",
            ]
        )

        is_synth = not (has_real_bouts and has_real_spots)

        summary = {
            # Spec v2 Section 6 root schema
            "investigation_window": investigation_window,
            "flagged_cows": flagged_cows_spec,
            "resources": {
                "resting_spots": resting_spots,
                "milking_units": milking_units,
            },
            "exposed_cows": exposed_cows,
            "route": route_spec,
            "provenance": provenance_spec,
            "is_model_suggestion": True,
            "is_synthetic": is_synth,
            # Legacy backwards-compatibility keys
            "targetCow": primary_target,
            "targetCows": target_cows,
            "lookbackWindowDays": lookback_days,
            "likelyRoute": route,
            "likely_route": likely_route_canonical,
            "routeConfidencePValue": p_val,
            "pathogenGroupLikelihood": (
                res.get("pathogen_group_likelihood")
                if res
                else ("environmental_streptococci" if "resting" in route else "contagious_staph")
            ),
            "implicatedResource": primary_resource_label,
            "implicatedRestingCircles": resting_spots,
            "primaryContactCows": contact_cow_ids,
            "recommendedIntervention": recommended_actions[0],
            "recommended_actions": recommended_actions,
            "disclaimer": "Attribution reflects epidemiological transmission probability, not clinical diagnosis.",
            "delegatedToAnalysis": bool(res is not None),
            "analysisResult": res if res else {},
        }

        run = self.store.record_backtrace_run(
            target_animal_id=primary_target,
            target_animal_ids=target_cows,
            lookback_days=lookback_days,
            summary=summary,
        )
        return run.to_dict()
