"""S7: Acute Mastitis Risk Scorer.

Strictly non-diagnostic risk framing:
mastitis_risk = 0.6 * rule_score + 0.4 * anomaly_score

- rule_score: EWMA + CUSUM change detection on available mastitis channels:
  - conductivity (up)
  - SCC (up)
  - daily milk yield (down)
  - lying duration (down)
  - CBT (up)
  - rumination / feeding proxy (down)
- anomaly_score: Unsupervised Isolation Forest on standardized feature z-vector.
- Both components and top contributing signals kept visible.
- Risk >= threshold (70.0) generates an auto-flag payload.
- Explicitly NO supervised mastitis classifier and NO chronic forecasting.
"""

from __future__ import annotations
from typing import Any, Sequence
import numpy as np
import pandas as pd

# Metric weights and alarm directions for the rule score
# direction: +1 means higher is abnormal; -1 means lower is abnormal
MASTITIS_CHANNELS: dict[str, tuple[float, int]] = {
    "conductivity_max": (0.30, +1),
    "scc_mean": (0.25, +1),
    "daily_milk_yield_kg": (0.25, -1),
    "cbt_mean": (0.20, +1),
    "lying_time_min": (0.15, -1),
    "rumination_proxy_mean": (0.15, -1),
}


def compute_ewma_cusum_alarm(
    values: Sequence[float],
    direction: int,
    alpha: float = 0.4,
    cusum_slack: float = 0.5,
) -> float:
    """Compute EWMA + CUSUM composite alarm intensity (0–100) for a z-score sequence."""
    if len(values) == 0:
        return 0.0

    ewma = 0.0
    cusum = 0.0

    for z in values:
        if z is None or pd.isna(z):
            continue
        # Unfavorable deviation
        dev = max(0.0, float(z) * direction)
        ewma = alpha * dev + (1.0 - alpha) * ewma
        cusum = max(0.0, cusum + (dev - cusum_slack))

    # Scale to 0-100 score
    intensity = min(100.0, ewma * 30.0 + cusum * 20.0)
    return float(intensity)


def compute_anomaly_score_isolation_forest(
    z_vectors: np.ndarray,
    target_idx: int = -1,
) -> float:
    """Compute unsupervised anomaly score (0–100) on z-score vectors.

    Uses IsolationForest when scikit-learn is present; falls back gracefully
    to robust normalized Euclidean/Mahalanobis distance.
    """
    if z_vectors.size == 0:
        return 0.0

    target_vec = z_vectors[target_idx]
    # Replace NaNs with 0 (baseline)
    clean_vec = np.nan_to_num(target_vec, nan=0.0)

    try:
        from sklearn.ensemble import IsolationForest

        # If we have cohort observations, fit on cohort
        if len(z_vectors) >= 5:
            clean_matrix = np.nan_to_num(z_vectors, nan=0.0)
            clf = IsolationForest(n_estimators=50, contamination=0.15, random_state=42)
            clf.fit(clean_matrix)
            score_raw = clf.decision_function(clean_vec.reshape(1, -1))[0]
        else:
            # Synthetic background around origin
            rng = np.random.default_rng(42)
            bg = rng.normal(0.0, 1.0, size=(40, len(clean_vec)))
            clf = IsolationForest(n_estimators=50, contamination=0.15, random_state=42)
            clf.fit(bg)
            score_raw = clf.decision_function(clean_vec.reshape(1, -1))[0]

        # Invert score: lower decision function means higher anomaly
        anomaly = np.clip((0.15 - score_raw) * 200.0, 0.0, 100.0)
        return float(round(anomaly, 1))
    except ImportError:
        # Robust distance fallback
        dist = np.sqrt(np.mean(clean_vec ** 2))
        anomaly = np.clip(dist * 28.0, 0.0, 100.0)
        return float(round(anomaly, 1))


def evaluate_acute_mastitis_risk(
    cow_baseline_info: dict[str, Any],
    all_cows_baseline_info: dict[str, dict[str, Any]] | None = None,
    risk_threshold: float = 70.0,
) -> dict[str, Any]:
    """Compute acute mastitis risk score, breakdown, and auto-flag.

    Args:
        cow_baseline_info: Baseline dict for a single cow containing metrics.
        all_cows_baseline_info: Optional herd-level baseline dict for cohort anomaly context.
        risk_threshold: Threshold above which an auto-flag is generated (default: 70.0).

    Returns:
        Dictionary with mastitis_risk, rule_score, anomaly_score, top signals, and auto_flag.
    """
    metrics = cow_baseline_info.get("metrics", {})
    cow_id = str(cow_baseline_info.get("cow_id", "unknown"))

    # 1. Rule Score: EWMA + CUSUM on available channels
    rule_score_num = 0.0
    weight_sum = 0.0
    signal_contributions: list[tuple[str, float, str]] = []

    z_list = []
    for m, (weight, direction) in MASTITIS_CHANNELS.items():
        m_info = metrics.get(m)
        if m_info is None:
            continue
        z = m_info.get("effective_z_score")
        if z is None or pd.isna(z):
            continue

        z_float = float(z)
        z_list.append(z_float)

        # Single-point or historical sequence
        alarm = compute_ewma_cusum_alarm([z_float], direction=direction)
        rule_score_num += alarm * weight
        weight_sum += weight

        # Document signal description
        if direction > 0 and z_float > 0.8:
            desc = f"{m.replace('_', ' ').title()} elevated (z={z_float:+.1f})"
            signal_contributions.append((m, alarm * weight, desc))
        elif direction < 0 and z_float < -0.8:
            desc = f"{m.replace('_', ' ').title()} depressed (z={z_float:+.1f})"
            signal_contributions.append((m, alarm * weight, desc))

    rule_score = round(rule_score_num / weight_sum, 1) if weight_sum > 0 else 0.0

    # 2. Anomaly Score: Isolation Forest on z-vector
    if all_cows_baseline_info:
        cohort_vectors = []
        for c_info in all_cows_baseline_info.values():
            c_metrics = c_info.get("metrics", {})
            vec = [
                c_metrics.get(m, {}).get("effective_z_score", 0.0) or 0.0
                for m in MASTITIS_CHANNELS.keys()
            ]
            cohort_vectors.append(vec)
        cohort_matrix = np.array(cohort_vectors, dtype=float)
        cur_vec = np.array([
            metrics.get(m, {}).get("effective_z_score", 0.0) or 0.0
            for m in MASTITIS_CHANNELS.keys()
        ], dtype=float)
        anomaly_score = compute_anomaly_score_isolation_forest(
            np.vstack([cohort_matrix, cur_vec]),
            target_idx=-1,
        )
    else:
        cur_vec = np.array([
            metrics.get(m, {}).get("effective_z_score", 0.0) or 0.0
            for m in MASTITIS_CHANNELS.keys()
        ], dtype=float)
        anomaly_score = compute_anomaly_score_isolation_forest(cur_vec.reshape(1, -1), target_idx=0)

    # 3. Composite Acute Mastitis Risk
    mastitis_risk = round(0.6 * rule_score + 0.4 * anomaly_score, 1)

    # 4. Top contributing signals
    signal_contributions.sort(key=lambda x: x[1], reverse=True)
    top_signals = [item[2] for item in signal_contributions[:3]]
    if not top_signals:
        top_signals = ["All monitored channels within expected baseline variance"]

    # 5. Auto-flag structure if >= threshold
    auto_flag = None
    if mastitis_risk >= risk_threshold:
        auto_flag = {
            "cow_id": cow_id,
            "flag_type": "auto_mastitis_watch",
            "risk_score": mastitis_risk,
            "rule_score": rule_score,
            "anomaly_score": anomaly_score,
            "threshold": risk_threshold,
            "top_contributing_signals": top_signals,
            "recommended_actions": [
                "Perform California Mastitis Test (CMT) & foremilk check at next milking",
                "Inspect udder quarter swelling, heat, or abnormal milk consistency",
                "Log observation in farm health event records",
            ],
            "is_model_suggestion": True,
        }

    return {
        "mastitis_risk": mastitis_risk,
        "rule_score": rule_score,
        "anomaly_score": anomaly_score,
        "top_contributing_signals": top_signals,
        "auto_flag": auto_flag,
        "is_model_suggestion": True,
    }
