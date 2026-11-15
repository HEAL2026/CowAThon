"""S7: Dairy Health Index (0–100).

Composite health vitality score constructed from multi-system z-score deviations:
- Thermal Vitality (0–25 points)
- Rumination & Posture Vitality (0–25 points)
- Activity & Kinetic Vitality (0–25 points)
- Production Vitality (0–25 points)

Total health index ranges from 0 (severe multi-system disruption) to 100 (optimal vitality).
All component scores remain explicitly visible in the payload.
"""

from __future__ import annotations
from typing import Any
import numpy as np


def compute_health_index(
    baseline_info: dict[str, Any],
) -> dict[str, Any]:
    """Compute 0–100 Dairy Health Vitality Index from tiered baseline z-scores.

    Args:
        baseline_info: Dictionary containing 'metrics' with effective_z_score entries.

    Returns:
        Dictionary with overall health_index, component breakdown, and vitality tier.
    """
    metrics = baseline_info.get("metrics", {})

    # Helper to retrieve effective z-score
    def get_z(metric_name: str) -> float | None:
        m = metrics.get(metric_name)
        if m is not None:
            return m.get("effective_z_score")
        return None

    # 1. Thermal Vitality (0–25 points)
    # Penalized by elevated CBT (fever / heat strain)
    z_cbt = get_z("cbt_mean")
    thermal_penalty = 0.0
    if z_cbt is not None and z_cbt > 0.0:
        thermal_penalty = min(25.0, z_cbt * 10.0)
    thermal_vitality = max(0.0, 25.0 - thermal_penalty)

    # 2. Posture & Feeding Behavior Vitality (0–25 points)
    # Penalized by abnormal lying duration drop or depressed feeding duration
    z_lying = get_z("lying_time_min")
    if z_lying is None:
        z_lying = get_z("clf_lying_time_min")
    z_feed = get_z("clf_feeding_time_min")

    behavior_penalty = 0.0
    if z_lying is not None and z_lying < 0.0:
        behavior_penalty += min(15.0, abs(z_lying) * 7.5)
    if z_feed is not None and z_feed < 0.0:
        behavior_penalty += min(10.0, abs(z_feed) * 5.0)
    behavior_vitality = max(0.0, 25.0 - behavior_penalty)

    # 3. Activity & Kinetic Vitality (0–25 points)
    # Penalized by severe lethargy or extreme agitation
    z_act = get_z("activity_index_mean")
    act_penalty = 0.0
    if z_act is not None:
        if z_act < -1.0:
            act_penalty = min(25.0, abs(z_act) * 10.0)
        elif z_act > 2.5:
            act_penalty = min(15.0, (z_act - 2.5) * 6.0)
    activity_vitality = max(0.0, 25.0 - act_penalty)

    # 4. Production Vitality (0–25 points)
    # Penalized by milk yield drop below baseline
    z_yield = get_z("daily_milk_yield_kg")
    prod_penalty = 0.0
    if z_yield is not None and z_yield < 0.0:
        prod_penalty = min(25.0, abs(z_yield) * 12.5)
    production_vitality = max(0.0, 25.0 - prod_penalty)

    # Composite sum
    total_score = round(
        thermal_vitality + behavior_vitality + activity_vitality + production_vitality,
        1,
    )

    # Qualitative category
    if total_score >= 80.0:
        vitality_tier = "thriving"
    elif total_score >= 60.0:
        vitality_tier = "stable_monitoring"
    elif total_score >= 40.0:
        vitality_tier = "moderate_strain"
    else:
        vitality_tier = "acute_attention"

    return {
        "health_index": total_score,
        "vitality_tier": vitality_tier,
        "components": {
            "thermal_vitality": round(thermal_vitality, 1),
            "behavior_vitality": round(behavior_vitality, 1),
            "activity_vitality": round(activity_vitality, 1),
            "production_vitality": round(production_vitality, 1),
        },
    }
