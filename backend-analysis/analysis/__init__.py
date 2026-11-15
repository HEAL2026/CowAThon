"""Backend Analysis package for Challenge 1 (MMCows)."""

from .env_thermal import calculate_thi, categorize_thi_strain, calculate_thermal_load
from .cbt_strain import calculate_cbt_strain_score, detect_temperature_spikes
from .behavior import calculate_activity_index, calculate_rumination_proxy, classify_posture_state
from .risk_scorer import MultimodalRiskScorer
from .baselines import evaluate_baselines_vs_multimodal
from .evaluation import run_group_cross_validation

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
]
