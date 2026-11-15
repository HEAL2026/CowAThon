"""
Data structures and schema definitions for visualization payloads.
Alignd with MMCows raw schema and backend-analysis CONTRACT.md.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class CowLocationPoint:
    cow_id: str
    display_name: str
    uwb_x_m: float
    uwb_y_m: float
    zone: str
    activity_state: str
    out_of_pen: bool
    risk_status: str
    risk_score: float
    factors: List[str]
    on_watch_list: bool
    vet_flagged: bool
    is_instrumented: bool = True
    missing_modalities: List[str] = field(default_factory=list)


@dataclass
class BarnZone:
    zone_id: str
    zone_type: str
    cow_count: int
    capacity: int
    mean_idling_minutes: float


@dataclass
class HeatmapGrid:
    resolution_m: float
    width: int
    height: int
    density_matrix: List[List[float]]


@dataclass
class BarnOverviewPayload:
    ts_utc: str
    barn_id: str
    indoor_thi: float
    indoor_temp_c: float
    indoor_humidity_pct: float
    is_synthetic: bool
    cows: List[Dict[str, Any]]
    zones: List[Dict[str, Any]]
    heatmap_grid: Dict[str, Any]


@dataclass
class TimeseriesPoint:
    ts_utc: str
    cbt_c: Optional[float]
    cbt_c_is_imputed: bool
    neck_imu_magnitude_mean: Optional[float]
    neck_imu_magnitude_mean_is_imputed: bool
    daily_milk_yield_kg: Optional[float]
    daily_milk_yield_kg_is_imputed: bool
    lying: Optional[int]
    indoor_thi: Optional[float]
    indoor_thi_is_imputed: bool
    out_of_pen: bool


@dataclass
class CowTimeseriesPayload:
    cow_id: str
    data_range: Dict[str, str]
    summary: Dict[str, Any]
    timeseries: List[Dict[str, Any]]
    resting_history: List[Dict[str, Any]]
    co_resting_cows: List[Dict[str, Any]]


@dataclass
class StallInfo:
    stall_number: int
    state: str
    current_cow_id: Optional[str]
    session_yield_kg: Optional[float]
    flow_rate_kg_min: Optional[float]
    last_completed_cycle: Optional[Dict[str, Any]]


@dataclass
class MilkingStallsPayload:
    ts_utc: str
    parlor_id: str
    stalls: List[Dict[str, Any]]


@dataclass
class WatchListItem:
    cow_id: str
    flag_type: str
    risk_category: str
    watch_risk_score: float
    watch_reason: str
    confidence: float
    modalities_present: List[str]
    modalities_missing: List[str]
    missing_modality_impact: str
    recommended_action: str
    is_model_suggestion: bool = True


@dataclass
class WatchListPayload:
    ts_utc: str
    items: List[Dict[str, Any]]


@dataclass
class BenchmarkSummaryPayload:
    dataset: str
    evaluation_protocol: str
    n_groups: int
    n_splits: int
    baselines: Dict[str, Any]
    multimodal_model: Dict[str, Any]
    multimodal_lift_over_env_baseline_auc: float
    multimodal_lift_over_cbt_baseline_auc: float
    cv_unavailable: bool = False
    is_synthetic: bool = False


@dataclass
class SystemIntegrationItem:
    adapter_id: str
    name: str
    attached: bool
    cadence: str
    annual_cost_per_head_usd: float
    feasibility_tier: str
    signals: List[str]
    is_synthetic: bool


@dataclass
class IntegrationsFeasibilityPayload:
    systems: List[Dict[str, Any]]
