"""S7: Dairy Health Vitality Index (0–100).

Composite health vitality score constructed from 3 core physiological vitality components
(summing to 100 points):
- Behavior Vitality (0–35 points): Lying duration (max 20 pts) + feeding duration (max 15 pts)
- Production Vitality (0–35 points): Daily milk yield z-score deviation
- Thermal Vitality (0–30 points): Core body temperature (CBT) fever elevation

Core factors determine the index.
- Never renormalises on missing modalities: absent components emit score=None and
  provenance="absent", decreasing coverage and confidence rather than inflating the index.
- Herd context (barn-level THI) explains behavioral deviations as a confounder
  (heat_confounded=True) rather than penalizing individual animals.
- Optional factors (conductivity, SCC, bedding window, feeding duration) remain in
  corroborating evidence and never alter the health index.
- Non-clinical monitoring framing: all outputs are decision support / model suggestions.
"""

from __future__ import annotations
from typing import Any, Optional


def compute_health_index(
    baseline_info: dict[str, Any],
    herd_context: Optional[dict[str, Any]] = None,
    corroborating_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Compute 0–100 Dairy Health Vitality Index from tiered baseline z-scores.

    Args:
        baseline_info: Dictionary containing 'metrics' with effective_z_score entries,
            and optional baseline confidence.
        herd_context: Optional dictionary containing barn-level environmental context
            (thi_mean, thi_max, hours_thi_above_72, heat_confounded).
        corroborating_data: Optional dictionary with non-index corroborating evidence
            (milk_tests, bedding_window, feeding_duration_min).

    Returns:
        Dictionary with overall health_index, vitality_tier, coverage, confidence,
        component breakdown with provenance, herd_context, and corroborating blocks.
    """
    metrics = baseline_info.get("metrics", {})

    # Helper to retrieve effective z-score and metric dict
    def get_metric_info(metric_name: str) -> tuple[float | None, dict[str, Any] | None]:
        m = metrics.get(metric_name)
        if m is not None:
            z = m.get("effective_z_score")
            return (float(z) if z is not None else None, m)
        return (None, None)

    # ---------------------------------------------------------
    # 1. Behavior Vitality (0–35 points)
    # Lying duration (max 20 points) + Feeding duration (max 15 points)
    # ---------------------------------------------------------
    z_lying, m_lying = get_metric_info("clf_lying_time_min")
    lying_input_name = "clf_lying_time_min"
    if z_lying is None:
        z_lying, m_lying = get_metric_info("lying_time_min")
        lying_input_name = "lying_time_min"

    z_feed, m_feed = get_metric_info("clf_feeding_time_min")
    feed_input_name = "clf_feeding_time_min"
    if z_feed is None:
        z_feed, m_feed = get_metric_info("feeding_time_min")
        feed_input_name = "feeding_time_min"

    behavior_inputs: list[str] = []
    behavior_provenances: list[str] = []
    behavior_base_avail = 0.0
    behavior_penalty = 0.0

    if z_lying is not None:
        behavior_inputs.append(lying_input_name)
        behavior_provenances.append("real_classifier" if "clf" in lying_input_name else "real_sensor")
        behavior_base_avail += 20.0
        if z_lying < 0.0:
            behavior_penalty += min(20.0, abs(z_lying) * 10.0)

    if z_feed is not None:
        behavior_inputs.append(feed_input_name)
        behavior_provenances.append("real_classifier" if "clf" in feed_input_name else "real_sensor")
        behavior_base_avail += 15.0
        if z_feed < 0.0:
            behavior_penalty += min(15.0, abs(z_feed) * 7.5)

    if not behavior_inputs:
        comp_behavior = {
            "score": None,
            "weight": 35.0,
            "z_lying": None,
            "z_feeding": None,
            "inputs_used": [],
            "provenance": "absent",
        }
    else:
        score_b = round(max(0.0, behavior_base_avail - behavior_penalty), 1)
        if all(p == "real_classifier" for p in behavior_provenances):
            prov_b = "real_classifier"
        elif all(p == "real_sensor" for p in behavior_provenances):
            prov_b = "real_sensor"
        else:
            prov_b = "multimodal_real"

        comp_behavior = {
            "score": score_b,
            "weight": 35.0,
            "z_lying": round(z_lying, 2) if z_lying is not None else None,
            "z_feeding": round(z_feed, 2) if z_feed is not None else None,
            "inputs_used": behavior_inputs,
            "provenance": prov_b,
        }

    # ---------------------------------------------------------
    # 2. Production Vitality (0–35 points)
    # Penalized by daily milk yield drop below rolling baseline
    # ---------------------------------------------------------
    z_yield, m_yield = get_metric_info("daily_milk_yield_kg")
    if z_yield is None:
        z_yield, m_yield = get_metric_info("milk_yield_kg")

    if z_yield is None:
        comp_production = {
            "score": None,
            "weight": 35.0,
            "z_yield": None,
            "inputs_used": [],
            "provenance": "absent",
        }
    else:
        prod_penalty = min(35.0, abs(z_yield) * 17.5) if z_yield < 0.0 else 0.0
        score_p = round(max(0.0, 35.0 - prod_penalty), 1)
        comp_production = {
            "score": score_p,
            "weight": 35.0,
            "z_yield": round(z_yield, 2),
            "inputs_used": ["daily_milk_yield_kg"],
            "provenance": "real_sensor",
        }

    # ---------------------------------------------------------
    # 3. Thermal Vitality (0–30 points)
    # Penalized by elevated CBT fever (z > 0)
    # ---------------------------------------------------------
    z_cbt, m_cbt = get_metric_info("cbt_mean")
    if z_cbt is None:
        z_cbt, m_cbt = get_metric_info("cbt_c")

    if z_cbt is None:
        comp_thermal = {
            "score": None,
            "weight": 30.0,
            "z_cbt": None,
            "inputs_used": [],
            "provenance": "absent",
        }
    else:
        thermal_penalty = min(30.0, z_cbt * 12.0) if z_cbt > 0.0 else 0.0
        score_t = round(max(0.0, 30.0 - thermal_penalty), 1)
        comp_thermal = {
            "score": score_t,
            "weight": 30.0,
            "z_cbt": round(z_cbt, 2),
            "inputs_used": ["cbt_mean"],
            "provenance": "real_sensor",
        }

    # ---------------------------------------------------------
    # Coverage & Confidence (Explicit missing modalities, no renormalisation)
    # ---------------------------------------------------------
    core_components = [comp_behavior, comp_production, comp_thermal]
    valid_components = [c for c in core_components if c["score"] is not None]
    coverage = round(len(valid_components) / 3.0, 2)

    b_conf = float(
        baseline_info.get("overall_baseline_confidence", baseline_info.get("confidence", 1.0))
    )
    confidence = round(b_conf * coverage, 2)

    # Health Index composite sum (no weight redistribution)
    if not valid_components:
        total_score: float | None = None
        vitality_tier = "insufficient_data"
    else:
        total_score = round(sum(c["score"] for c in valid_components if c["score"] is not None), 1)
        if total_score >= 80.0:
            vitality_tier = "thriving"
        elif total_score >= 60.0:
            vitality_tier = "stable_monitoring"
        elif total_score >= 40.0:
            vitality_tier = "moderate_strain"
        else:
            vitality_tier = "acute_attention"

    # ---------------------------------------------------------
    # Herd Context (Barn-level THI, confounder for behavior)
    # ---------------------------------------------------------
    h_ctx = herd_context or baseline_info.get("herd_context", {})
    thi_mean = h_ctx.get("thi_mean")
    thi_max = h_ctx.get("thi_max")
    hours_above_72 = float(h_ctx.get("hours_thi_above_72", 0.0))
    heat_conf = bool(
        h_ctx.get(
            "heat_confounded",
            (hours_above_72 > 0.0 or (thi_mean is not None and thi_mean >= 72.0)),
        )
    )

    herd_context_out = {
        "thi_mean": round(float(thi_mean), 1) if thi_mean is not None else None,
        "thi_max": round(float(thi_max), 1) if thi_max is not None else None,
        "hours_thi_above_72": round(hours_above_72, 2),
        "heat_confounded": heat_conf,
    }

    # ---------------------------------------------------------
    # Corroborating Evidence (Never alters health_index)
    # ---------------------------------------------------------
    c_data = corroborating_data or baseline_info.get("corroborating", {})

    # Milk tests (cond_max, scc_kcells_ml)
    m_tests = c_data.get("milk_tests", {})
    cond_max = m_tests.get("cond_max")
    scc_val = m_tests.get("scc_kcells_ml")
    if cond_max is None and metrics.get("conductivity_max"):
        cond_max = metrics["conductivity_max"].get("current_value")
    if scc_val is None and metrics.get("scc_mean"):
        scc_val = metrics["scc_mean"].get("current_value")

    prov_milk = m_tests.get("provenance")
    if prov_milk is None:
        prov_milk = "synthetic" if (cond_max is not None or scc_val is not None) else "absent"

    # Bedding window
    b_win = c_data.get("bedding_window", {})
    zone_id = b_win.get("zone_id")
    changed_at = b_win.get("changed_at")
    prov_bedding = b_win.get("provenance")
    if prov_bedding is None:
        prov_bedding = "synthetic" if (changed_at is not None or zone_id is not None) else "absent"

    # Feeding duration
    feed_val = None
    if m_feed and m_feed.get("current_value") is not None:
        feed_val = m_feed.get("current_value")
    elif c_data.get("feeding_duration_min", {}).get("value") is not None:
        feed_val = c_data["feeding_duration_min"]["value"]

    prov_feed = "real_classifier" if feed_val is not None else "absent"

    corroborating_out = {
        "milk_tests": {
            "cond_max": round(float(cond_max), 2) if cond_max is not None else None,
            "scc_kcells_ml": round(float(scc_val), 1) if scc_val is not None else None,
            "provenance": prov_milk,
        },
        "bedding_window": {
            "zone_id": str(zone_id) if zone_id is not None else None,
            "changed_at": str(changed_at) if changed_at is not None else None,
            "provenance": prov_bedding,
        },
        "feeding_duration_min": {
            "value": round(float(feed_val), 1) if feed_val is not None else None,
            "provenance": prov_feed,
        },
    }

    # Backward-compatible scalar vitalities for existing visualization consumers
    legacy_components = {
        "thermal_vitality": comp_thermal["score"] if comp_thermal["score"] is not None else 0.0,
        "behavior_vitality": comp_behavior["score"] if comp_behavior["score"] is not None else 0.0,
        "activity_vitality": 0.0,
        "production_vitality": comp_production["score"] if comp_production["score"] is not None else 0.0,
    }

    return {
        "health_index": total_score,
        "vitality_tier": vitality_tier,
        "coverage": coverage,
        "confidence": confidence,
        "components": {
            "behavior": comp_behavior,
            "production": comp_production,
            "thermal": comp_thermal,
            **legacy_components,
        },
        "vitality_components": legacy_components,
        "herd_context": herd_context_out,
        "corroborating": corroborating_out,
        "is_model_suggestion": True,
    }
