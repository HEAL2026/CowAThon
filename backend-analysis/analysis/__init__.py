"""Backend Analysis package for Challenge 1 (MMCows)."""

from .env_thermal import calculate_thi, categorize_thi_strain, calculate_thermal_load
from .cbt_strain import calculate_cbt_strain_score, detect_temperature_spikes
from .behavior import calculate_activity_index, calculate_rumination_proxy, classify_posture_state
from .risk_scorer import MultimodalRiskScorer
from .baselines import evaluate_baselines_vs_multimodal
from .evaluation import run_group_cross_validation
from .cow_day_features import aggregate_cow_day_features
from .tiered_baselines import compute_tiered_baselines
from .health_index import compute_health_index
from .mastitis_risk import evaluate_acute_mastitis_risk

__all__ = [
    "calculate_thi",
    "categorize_thi_strain",
    "calculate_thermal_load",
    "calculate_cbt_strain_score",
    "detect_temperature_spikes",
    "calculate_activity_index",
    "calculate_rumination_proxy",
    "classify_posture_state",
    "MultimodalRiskScorer",
    "evaluate_baselines_vs_multimodal",
    "run_group_cross_validation",
    "aggregate_cow_day_features",
    "compute_tiered_baselines",
    "compute_health_index",
    "evaluate_acute_mastitis_risk",
]
