"""S6: Tiered baselines with cold-start progression.

Progression hierarchy:
1. Tier 1 (own_history): Individual cow history >= 7 days.
2. Tier 2 (blended): Individual cow history 1 <= n < 7 days; blended w = n / (n + k) (k=3).
3. Tier 3 (cohort): Cohort by parity x lactation stage (DIM < 60d, 60-180d, > 180d).
4. Tier 4 (literature_prior): Dairy veterinary literature defaults.

Provides baseline_tier, baseline_confidence, and threshold widening factor
(low confidence widens thresholds, never hides the cow).
"""

from __future__ import annotations
from typing import Any, Optional
import numpy as np
import pandas as pd

# Literature priors for dairy cows (mean, std)
LITERATURE_PRIORS: dict[str, tuple[float, float]] = {
    "cbt_mean": (38.80, 0.25),
    "daily_milk_yield_kg": (30.0, 4.5),
    "lying_time_min": (660.0, 80.0),
    "rumination_proxy_mean": (50.0, 12.0),
    "activity_index_mean": (0.150, 0.050),
    "conductivity_max": (5.5, 0.4),
    "scc_mean": (100.0, 40.0),
}


def get_lactation_stage_bin(dim: int | float | None) -> str:
    """Bin days in milk (DIM) into canonical lactation stages."""
    if dim is None or pd.isna(dim):
        return "mid"
    dim_val = float(dim)
    if dim_val < 60:
        return "early"
    elif dim_val <= 180:
        return "mid"
    else:
        return "late"


def compute_tiered_baselines(
    historical_cow_days: pd.DataFrame,
    current_cow_days: pd.DataFrame,
    metrics: tuple[str, ...] = (
        "cbt_mean",
        "daily_milk_yield_kg",
        "lying_time_min",
        "rumination_proxy_mean",
        "activity_index_mean",
        "conductivity_max",
        "scc_mean",
    ),
    blend_k: float = 3.0,
) -> dict[str, dict[str, Any]]:
    """Compute tiered baseline parameters and z-scores for current cow-day records.

    Args:
        historical_cow_days: DataFrame of historical daily records (may be empty for cold-start).
        current_cow_days: DataFrame of current daily observations to evaluate.
        metrics: Tuple of feature metric column names.
        blend_k: Prior blending constant k (default: 3).

    Returns:
        Dictionary keyed by cow_id with baseline parameters and z-scores.
    """
    results: dict[str, dict[str, Any]] = {}

    # Build cohort lookup from available data
    cohort_stats: dict[tuple[int, str], dict[str, tuple[float, float]]] = {}
    combined_df = (
        pd.concat([historical_cow_days, current_cow_days], ignore_index=True)
        if len(historical_cow_days) > 0
        else current_cow_days.copy()
    )

    if len(combined_df) > 0:
        if "parity" not in combined_df.columns:
            combined_df["parity"] = 2
        if "dim" not in combined_df.columns:
            combined_df["dim"] = 120
        combined_df["stage"] = combined_df["dim"].apply(get_lactation_stage_bin)

        for (parity, stage), group in combined_df.groupby(["parity", "stage"]):
            stats: dict[str, tuple[float, float]] = {}
            for m in metrics:
                if m in group.columns and group[m].notna().sum() >= 2:
                    s = group[m].dropna()
                    std_val = float(s.std())
                    stats[m] = (float(s.mean()), std_val if std_val > 1e-4 else LITERATURE_PRIORS.get(m, (0.0, 1.0))[1])
            cohort_stats[(int(parity), str(stage))] = stats

    for cow_id, cur_group in current_cow_days.groupby("cow_id"):
        cid = str(cow_id)
        latest_row = cur_group.iloc[-1]
        parity = int(latest_row.get("parity", 2))
        stage = get_lactation_stage_bin(latest_row.get("dim", 120))
        cohort_key = (parity, stage)

        cow_history = (
            historical_cow_days[historical_cow_days["cow_id"] == cid]
            if len(historical_cow_days) > 0 and "cow_id" in historical_cow_days.columns
            else pd.DataFrame()
        )
        n_days = len(cow_history)

        cow_metrics_result: dict[str, Any] = {}
        observed_tiers: list[str] = []
        observed_confs: list[float] = []

        for m in metrics:
            val = latest_row.get(m)
            has_val = val is not None and not pd.isna(val)

            val_float = float(val) if has_val else None

            # 1. Check history days with valid measurement for this metric
            m_history = cow_history[m].dropna() if len(cow_history) > 0 and m in cow_history.columns else pd.Series(dtype=float)
            n_m = len(m_history)

            tier: str
            confidence: float
            mu: float
            sigma: float

            cohort_pair = cohort_stats.get(cohort_key, {}).get(m)
            lit_mu, lit_sigma = LITERATURE_PRIORS.get(m, (0.0, 1.0))

            if n_m >= 7:
                # Tier 1: own_history
                tier = "own_history"
                confidence = min(1.0, 0.70 + 0.04 * n_m)
                mu = float(m_history.mean())
                s_val = float(m_history.std())
                sigma = s_val if s_val > 1e-4 else lit_sigma
            elif n_m >= 1:
                # Tier 2: blended
                tier = "blended"
                confidence = 0.50 + 0.05 * n_m
                w = n_m / (n_m + blend_k)
                own_mu = float(m_history.mean())
                own_std = float(m_history.std()) if len(m_history) > 1 else lit_sigma
                prior_mu = cohort_pair[0] if cohort_pair else lit_mu
                prior_std = cohort_pair[1] if cohort_pair else lit_sigma
                mu = w * own_mu + (1.0 - w) * prior_mu
                sigma = w * own_std + (1.0 - w) * prior_std
            elif cohort_pair is not None:
                # Tier 3: cohort
                tier = "cohort"
                confidence = 0.40
                mu, sigma = cohort_pair
            else:
                # Tier 4: literature_prior
                tier = "literature_prior"
                confidence = 0.25
                mu, sigma = lit_mu, lit_sigma

            if sigma < 1e-4:
                sigma = 1.0

            # Threshold widening factor (low confidence widens thresholds)
            threshold_multiplier = round(1.0 + (1.0 - confidence) * 0.8, 2)

            # Normalized z-score
            z_score = None
            if val_float is not None:
                raw_z = (val_float - mu) / sigma
                # Scaled by threshold multiplier
                z_score = round(raw_z / threshold_multiplier, 2)

            cow_metrics_result[m] = {
                "observed_value": round(val_float, 2) if val_float is not None else None,
                "baseline_mean": round(mu, 2),
                "baseline_std": round(sigma, 2),
                "baseline_tier": tier,
                "baseline_confidence": round(confidence, 2),
                "threshold_multiplier": threshold_multiplier,
                "effective_z_score": z_score,
            }

            if has_val:
                observed_tiers.append(tier)
                observed_confs.append(confidence)

        if observed_confs:
            min_conf = min(observed_confs)
            primary_tier = observed_tiers[observed_confs.index(min_conf)]
        else:
            min_conf = 0.25
            primary_tier = "literature_prior"

        results[cid] = {
            "cow_id": cid,
            "primary_baseline_tier": primary_tier,
            "overall_baseline_confidence": round(min_conf, 2),
            "threshold_multiplier": round(1.0 + (1.0 - min_conf) * 0.8, 2),
            "metrics": cow_metrics_result,
        }

    return results
