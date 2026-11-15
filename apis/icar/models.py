"""ICAR ADE (Animal Data Exchange) domain models for S1 mock vendor APIs.

Owner: @uiobio (Lei)
Provides:
- ICAR ADE standard resource representations (animal.id, eventDateTime, unitCode).
- Data models for replay feeds and stateful manual/flag/backtrace entries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def now_utc_iso() -> str:
    """Return current UTC timestamp formatted as ISO-8601 string ending with Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Animal:
    """ICAR ADE Animal profile."""
    animal_id: str                      # ICAR animal.id (e.g. "C01")
    official_tag: str                   # e.g. "US-001-C01"
    parity: int                         # Lactation number
    days_in_milk: int                   # DIM
    pen_number: int                     # Barn housing pen
    reproductive_status: str            # pregnant, open, bred, fresh
    is_synthetic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "animal": {"id": self.animal_id, "officialTag": self.official_tag},
            "parity": self.parity,
            "daysInMilk": self.days_in_milk,
            "penNumber": self.pen_number,
            "reproductiveStatus": self.reproductive_status,
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class LocationObservation:
    """ICAR ADE Real-Time Location observation."""
    animal_id: str
    event_datetime: str
    x_m: Optional[float]
    y_m: Optional[float]
    z_m: Optional[float]
    in_pen: bool
    zone_id: str
    unit_code: str = "UWB-ANCHOR-01"
    is_synthetic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "animal": {"id": self.animal_id},
            "eventDateTime": self.event_datetime,
            "unitCode": self.unit_code,
            "location": {
                "x_m": self.x_m,
                "y_m": self.y_m,
                "z_m": self.z_m,
                "in_pen": self.in_pen,
                "zone_id": self.zone_id,
            },
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class ImuObservation:
    """ICAR ADE Collar Kinematics & Pressure observation."""
    animal_id: str
    event_datetime: str
    accel_magnitude_mean: float
    accel_magnitude_std: float
    collar_pressure_hpa: float
    unit_code: str = "COLLAR-TAG-01"
    is_synthetic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "animal": {"id": self.animal_id},
            "eventDateTime": self.event_datetime,
            "unitCode": self.unit_code,
            "kinematics": {
                "accelMagnitudeMean_mps2": self.accel_magnitude_mean,
                "accelMagnitudeStd_mps2": self.accel_magnitude_std,
                "collarPressure_hpa": self.collar_pressure_hpa,
            },
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class BehaviorBucket:
    """Aggregated behavior telemetry bucket (default 2-hour window)."""
    animal_id: str
    start_time: str
    end_time: str
    duration_minutes: int
    lying_minutes: float
    feeding_minutes: float
    rumination_proxy: float
    activity_index: float
    behavior_mode: str
    is_synthetic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "animal": {"id": self.animal_id},
            "period": {
                "startTime": self.start_time,
                "endTime": self.end_time,
                "durationMinutes": self.duration_minutes,
            },
            "metrics": {
                "lyingMinutes": round(self.lying_minutes, 1),
                "feedingMinutes": round(self.feeding_minutes, 1),
                "ruminationProxy": round(self.rumination_proxy, 3),
                "activityIndex": round(self.activity_index, 3),
                "predominantBehaviorMode": self.behavior_mode,
            },
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class MilkVisit:
    """ICAR ADE Milking Visit observation."""
    animal_id: str
    event_datetime: str
    unit_code: str                     # Milking stall / robot ID (e.g. "STALL-02")
    yield_kg: float                    # Measured milk weight in kg
    duration_sec: int                  # Attachment duration
    conductivity_ms_cm: float          # Composite electrical conductivity proxy
    peak_flow_rate_kg_min: float       # Milk flow rate
    cond_lf_ms_cm: float = 4.8         # Left Front quarter conductivity (mS/cm)
    cond_lr_ms_cm: float = 4.9         # Left Rear quarter conductivity (mS/cm)
    cond_rf_ms_cm: float = 4.8         # Right Front quarter conductivity (mS/cm)
    cond_rr_ms_cm: float = 5.0         # Right Rear quarter conductivity (mS/cm)
    cond_max_ms_cm: float = 5.0        # Peak quarter conductivity (mS/cm)
    is_synthetic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "animal": {"id": self.animal_id},
            "eventDateTime": self.event_datetime,
            "unitCode": self.unit_code,
            "milking": {
                "yield_kg": self.yield_kg,
                "duration_s": self.duration_sec,
                "conductivity_ms_cm": self.conductivity_ms_cm,
                "peakFlowRate_kg_min": self.peak_flow_rate_kg_min,
                "quarterConductivity": {
                    "cond_lf_ms_cm": self.cond_lf_ms_cm,
                    "cond_lr_ms_cm": self.cond_lr_ms_cm,
                    "cond_rf_ms_cm": self.cond_rf_ms_cm,
                    "cond_rr_ms_cm": self.cond_rr_ms_cm,
                    "cond_max_ms_cm": self.cond_max_ms_cm,
                },
            },
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class EnvironmentObservation:
    """Barn and local weather climate observation."""
    event_datetime: str
    station_id: str
    indoor_temp_c: float
    indoor_rh_pct: float
    indoor_thi: float
    outdoor_temp_c: float
    outdoor_rh_pct: float
    outdoor_solar_wm2: float
    is_synthetic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eventDateTime": self.event_datetime,
            "stationId": self.station_id,
            "indoorClimate": {
                "temperature_c": self.indoor_temp_c,
                "relativeHumidity_pct": self.indoor_rh_pct,
                "thi": self.indoor_thi,
            },
            "outdoorClimate": {
                "temperature_c": self.outdoor_temp_c,
                "relativeHumidity_pct": self.outdoor_rh_pct,
                "solarRadiation_wm2": self.outdoor_solar_wm2,
            },
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class BodyTempObservation:
    """Rumen thermal bolus CBT observation."""
    animal_id: str
    event_datetime: str
    temperature_c: float
    unit_code: str = "BOLUS-01"
    is_synthetic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "animal": {"id": self.animal_id},
            "eventDateTime": self.event_datetime,
            "unitCode": self.unit_code,
            "bodyTemperature_c": self.temperature_c,
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class HealthEvent:
    """Historical or active health event log."""
    animal_id: str
    event_datetime: str
    event_type: str                     # e.g. "elevated_cbt_warning", "mastitis_history"
    severity: str                       # "advisory", "watch", "priority"
    source: str                         # "model_rule", "sensor_threshold", "herd_record"
    details: str
    is_synthetic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "animal": {"id": self.animal_id},
            "eventDateTime": self.event_datetime,
            "eventType": self.event_type,
            "severity": self.severity,
            "source": self.source,
            "details": self.details,
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class ManualEntry:
    """Operator manual entry for pregnancy, DIM, parity, bedding, or sanitation."""
    entry_id: str
    entry_type: str                     # "pregnancy", "dim", "parity", "bedding", "sanitation"
    animal_id: Optional[str]            # Optional (null for pen-wide bedding or stall sanitation)
    event_datetime: str
    details: Dict[str, Any]
    recorded_by: str = "operator"
    kind: Optional[str] = None          # For sanitation: "end_of_session" or "between_cows"

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.details)
        k = self.kind or d.get("kind")
        if k and "kind" not in d:
            d["kind"] = k
        return {
            "entryId": self.entry_id,
            "entryType": self.entry_type,
            "animalId": self.animal_id,
            "eventDateTime": self.event_datetime,
            "details": d,
            "recordedBy": self.recorded_by,
            "kind": k,
        }


@dataclass
class SanitationRecord:
    """ICAR ADE Milking Unit Sanitation observation with kind (docs/backtrace_spec.md §2, §3.3)."""
    unit_id: str                       # e.g. "U1", "STALL-01"
    sanitized_at: str                  # ISO-8601 UTC timestamp
    session_id: str                    # e.g. "2023-07-21_PM"
    kind: str = "end_of_session"       # "end_of_session" or "between_cows"
    is_synthetic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unitId": self.unit_id,
            "unit_id": self.unit_id,
            "sanitizedAt": self.sanitized_at,
            "sanitized_at": self.sanitized_at,
            "sessionId": self.session_id,
            "session_id": self.session_id,
            "kind": self.kind,
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class RestingSpot:
    """ICAR backtrace resting spot resource (docs/backtrace_spec.md §3.2, §6)."""
    spot_id: str
    center_x_m: float
    center_y_m: float
    radius_m: float = 1.5
    n_flagged: int = 0
    flagged_cows: List[str] = field(default_factory=list)
    dwell_min_by_flagged: Dict[str, float] = field(default_factory=dict)
    successors: List[Dict[str, Any]] = field(default_factory=list)
    until_bedding_change_utc: Optional[str] = None
    provenance: str = "real"
    n_bouts: int = 0
    n_cows: int = 0
    dwell_min: float = 0.0
    is_synthetic: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spot_id": self.spot_id,
            "spotId": self.spot_id,
            "center_x_m": self.center_x_m,
            "center_y_m": self.center_y_m,
            "radius_m": self.radius_m,
            "n_flagged": self.n_flagged,
            "flagged_cows": self.flagged_cows,
            "dwell_min_by_flagged": self.dwell_min_by_flagged,
            "successors": self.successors,
            "until_bedding_change_utc": self.until_bedding_change_utc,
            "provenance": self.provenance,
            "n_bouts": self.n_bouts,
            "n_cows": self.n_cows,
            "dwell_min": self.dwell_min,
            "is_synthetic": self.is_synthetic,
        }


@dataclass
class FlagRecord:
    """Manual or automated watch-list flag tracking."""
    flag_id: str
    animal_id: str
    flag_type: str                      # "manual" or "auto"
    flagged_at_utc: str
    status: str                         # "active", "cleared", "investigating"
    reason: str
    flagged_by: str                     # "vet", "operator", "model_acute_rule", etc.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "flagId": self.flag_id,
            "animalId": self.animal_id,
            "flagType": self.flag_type,
            "flaggedAtUtc": self.flagged_at_utc,
            "status": self.status,
            "reason": self.reason,
            "flaggedBy": self.flagged_by,
        }


@dataclass
class BacktraceRun:
    """Backtrace outbreak investigation run record."""
    run_id: str
    target_animal_id: str
    initiated_at_utc: str
    status: str                         # "completed", "running", "failed"
    lookback_days: int
    summary: Dict[str, Any]
    target_animal_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        targets = self.target_animal_ids or ([self.target_animal_id] if self.target_animal_id else [])
        d: Dict[str, Any] = {
            "runId": self.run_id,
            "targetAnimalId": self.target_animal_id,
            "targetAnimalIds": targets,
            "initiatedAtUtc": self.initiated_at_utc,
            "status": self.status,
            "lookbackDays": self.lookback_days,
            "summary": self.summary,
        }
        for key in (
            "investigation_window",
            "flagged_cows",
            "resources",
            "exposed_cows",
            "route",
            "provenance",
            "is_model_suggestion",
            "is_synthetic",
        ):
            if key in self.summary:
                d[key] = self.summary[key]
        return d
