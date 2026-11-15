"""End-to-end analysis pipeline execution.

Runs:
1. Feature extraction (THI, CBT strain, IMU activity, rumination proxy).
2. Stationary reference hardware detection (e.g. T13/T14).
3. Multimodal watch-list risk scoring and confidence estimation.
4. Group-aware animal-disjoint cross-validation benchmarking against single-sensor baselines.
5. Empirical ground-truth behavior validation when annotated windows are present (2023-07-25).
6. Output payload generation for backend-visualization and frontend consumption.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import pandas as pd

from .env_thermal import calculate_thi, categorize_thi_strain, calculate_thermal_load
from .cbt_strain import calculate_cbt_strain_score, detect_temperature_spikes
from .behavior import (
    calculate_activity_index,
    classify_posture_state,
    calculate_rumination_proxy,
    validate_behavior_against_ground_truth,
    detect_stationary_hardware_candidate,
)
from .risk_scorer import MultimodalRiskScorer
from .baselines import evaluate_baselines_vs_multimodal
from .cow_day_features import aggregate_cow_day_features
from .tiered_baselines import compute_tiered_baselines
from .health_index import compute_health_index
from .mastitis_risk import evaluate_acute_mastitis_risk


def write_schema_sidecar(
    df: pd.DataFrame,
    out_dir: Path,
    name: str,
    cadence: str,
    keys: list[str],
) -> Path:
    """Write <name>.schema.json sidecar matching canonical cleaning contract."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sidecar = {
        "table": name,
        "cadence": cadence,
        "keys": keys,
        "rows": int(len(df)),
        "columns": {
            c: {
                "dtype": str(df[c].dtype),
                "null_count": int(df[c].isna().sum()),
            }
            for c in df.columns
        },
    }
    path = out_dir / f"{name}.schema.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, sort_keys=True)
    return path


def run_analysis_pipeline(
    df: pd.DataFrame,
    output_dir: Path | str | None = None,
    n_cv_splits: int = 5,
    seed: int = 0,
    is_synthetic: bool = False,
) -> dict[str, Any]:
    """Execute the full backend analysis pipeline.

    Args:
        df: Input DataFrame with joined observation records (e.g. joined_1min.parquet).
        output_dir: Optional directory to save output JSON/parquet artifacts.
        n_cv_splits: Number of folds for animal-disjoint cross-validation.
        seed: Random seed for deterministic reproducibility.
        is_synthetic: Whether data is synthetic fixture fallback.

    Returns:
        Dictionary containing cow summaries, time series, and benchmark results.
    """
    df_proc = df.copy()

    # 1. Environmental THI
    if "indoor_thi" in df_proc.columns:
        df_proc["thi_category"] = categorize_thi_strain(df_proc["indoor_thi"])
    elif "thi" in df_proc.columns:
        df_proc["thi_category"] = categorize_thi_strain(df_proc["thi"])
    elif "indoor_temp_c" in df_proc.columns and "indoor_rh_pct" in df_proc.columns:
        df_proc["indoor_thi"] = calculate_thi(df_proc["indoor_temp_c"], df_proc["indoor_rh_pct"])
        df_proc["thi_category"] = categorize_thi_strain(df_proc["indoor_thi"])
    elif "temp_c" in df_proc.columns and "rh_pct" in df_proc.columns:
        df_proc["thi"] = calculate_thi(df_proc["temp_c"], df_proc["rh_pct"])
        df_proc["thi_category"] = categorize_thi_strain(df_proc["thi"])

    # 2. CBT Strain (with rectal_temp_c fallback from external sources)
    cbt_col = "cbt_c" if "cbt_c" in df_proc.columns else (
        "cbt" if "cbt" in df_proc.columns else (
            "rectal_temp_c" if "rectal_temp_c" in df_proc.columns else (
                "rectal_temp" if "rectal_temp" in df_proc.columns else None
            )
        )
    )
    if cbt_col:
        df_proc["cbt_strain_score"] = calculate_cbt_strain_score(df_proc[cbt_col])

    # 3. Behavioral IMU Features & Hardware Candidate Detection
    if "activity_index" not in df_proc.columns:
        df_proc["activity_index"] = calculate_activity_index(df_proc)

    # Detect stationary hardware candidates (T13/T14 on posts)
    is_hardware = detect_stationary_hardware_candidate(df_proc)
    df_proc["is_stationary_hardware"] = is_hardware

    if "posture_state" not in df_proc.columns or is_hardware.any():
        df_proc["posture_state"] = classify_posture_state(
            df_proc["activity_index"],
            is_stationary_hardware=is_hardware,
        )

    if "rumination_proxy" not in df_proc.columns:
        df_proc["rumination_proxy"] = calculate_rumination_proxy(df_proc)

    # 4. Multimodal Risk Scoring
    scorer = MultimodalRiskScorer()
    scored_records = [scorer.score_record(row) for _, row in df_proc.iterrows()]
    scored_df = pd.DataFrame(scored_records)

    # Join risk scores into df_proc
    df_proc["watch_risk_score"] = scored_df["watch_risk_score"]
    df_proc["risk_category"] = scored_df["risk_category"]
    df_proc["confidence_score"] = scored_df["confidence_score"]

    # 5. Daily Aggregation, Tiered Baselines, Health Index & Acute Mastitis Risk (S5–S7)
    cow_day_df = aggregate_cow_day_features(df_proc)
    live_cow_days = (
        cow_day_df[~cow_day_df["is_stationary_hardware"]].copy()
        if "is_stationary_hardware" in cow_day_df.columns
        else cow_day_df
    )
    baselines_by_cow = compute_tiered_baselines(pd.DataFrame(), live_cow_days)

    auto_flags: list[dict[str, Any]] = []

    # 6. Group Summaries per Animal (Latest Status)
    cow_summaries: dict[str, Any] = {}
    for cow_id, group in df_proc.groupby("cow_id"):
        cid = str(cow_id)
        latest_row = group.sort_values("ts_utc").iloc[-1]
        score_info = scorer.score_record(latest_row)

        cbt_val = latest_row.get("cbt_c") if latest_row.get("cbt_c") is not None else latest_row.get("cbt")
        thi_val = latest_row.get("indoor_thi") if latest_row.get("indoor_thi") is not None else latest_row.get("thi")
        milk_val = latest_row.get("milk_yield_kg") if latest_row.get("milk_yield_kg") is not None else latest_row.get("milk_yield")
        is_hw = bool(latest_row.get("is_stationary_hardware", False))

        c_base = baselines_by_cow.get(cid, {})
        h_info = compute_health_index(c_base) if not is_hw else {"health_index": None, "vitality_tier": "hardware", "components": {}}
        m_info = evaluate_acute_mastitis_risk(c_base, all_cows_baseline_info=baselines_by_cow) if not is_hw else {
            "mastitis_risk": 0.0,
            "rule_score": 0.0,
            "anomaly_score": 0.0,
            "top_contributing_signals": ["Stationary reference hardware tag"],
            "auto_flag": None,
        }

        if m_info.get("auto_flag"):
            auto_flags.append(m_info["auto_flag"])

        cow_summaries[cid] = {
            "cow_id": cid,
            "latest_ts_utc": str(latest_row.get("ts_utc", "")),
            "watch_risk_score": score_info["watch_risk_score"],
            "risk_category": score_info["risk_category"],
            "confidence_score": score_info["confidence_score"],
            "health_index": h_info["health_index"],
            "vitality_tier": h_info["vitality_tier"],
            "vitality_components": h_info["components"],
            "acute_mastitis_risk": m_info["mastitis_risk"],
            "mastitis_rule_score": m_info["rule_score"],
            "mastitis_anomaly_score": m_info["anomaly_score"],
            "mastitis_top_signals": m_info["top_contributing_signals"],
            "baseline_tier": c_base.get("primary_baseline_tier", "literature_prior") if not is_hw else "none",
            "baseline_confidence": c_base.get("overall_baseline_confidence", 0.0) if not is_hw else 0.0,
            "metrics": {
                "cbt_c": round(float(cbt_val), 2) if cbt_val is not None and not pd.isna(cbt_val) else None,
                "cbt_strain_score": round(float(latest_row.get("cbt_strain_score", 0.0)), 1),
                "ambient_thi": round(float(thi_val), 1) if thi_val is not None and not pd.isna(thi_val) else None,
                "thi_category": str(latest_row.get("thi_category", "unknown")),
                "activity_index": round(float(latest_row.get("activity_index", 0.0)), 3),
                "posture_state": str(latest_row.get("posture_state", "unknown")),
                "rumination_proxy": round(float(latest_row.get("rumination_proxy", 0.0)), 1),
                "daily_milk_yield_kg": round(float(milk_val), 1) if milk_val is not None and not pd.isna(milk_val) else None,
                "milk_drop_pct": round(float(latest_row.get("milk_drop_pct", 0.0)), 1),
                "out_of_pen": bool(latest_row.get("out_of_pen", False)),
                "is_stationary_hardware": is_hw,
            },
            "modalities_present": score_info["modalities_present"],
            "missing_modalities": score_info["missing_modalities"],
            "contributing_factors": score_info["contributing_factors"],
            "recommended_actions": score_info["recommended_actions"],
            "is_model_suggestion": True,
            "is_synthetic": is_synthetic,
        }

    # 7. Animal-Disjoint Cross-Validation Benchmarks (filter out hardware tags from model CV)
    cv_df = df_proc.loc[~df_proc["is_stationary_hardware"]].copy() if "is_stationary_hardware" in df_proc.columns else df_proc
    n_live_cows = int(cv_df["cow_id"].nunique()) if "cow_id" in cv_df.columns else 0

    if n_live_cows < 3:
        # Herd size floor: Below 3 distinct animals, animal-disjoint group splitting cannot form robust folds
        benchmarks = {
            "dataset": "MMCows Challenge 1",
            "evaluation_protocol": f"insufficient_animals_for_cv (n={n_live_cows})",
            "n_groups": n_live_cows,
            "n_splits": 0,
            "cv_unavailable": True,
            "cv_unavailable_reason": f"Need at least 3 distinct animal IDs for group cross-validation; found {n_live_cows}.",
            "baselines": {},
            "multimodal_model": {},
            "is_synthetic": is_synthetic,
        }
        # Gracefully degrade confidence on undersized cohorts
        for cid, summary in cow_summaries.items():
            if not summary["metrics"].get("is_stationary_hardware", False):
                summary["confidence_score"] = round(min(summary["confidence_score"], 0.60), 2)
                summary["contributing_factors"].append(
                    f"Small herd cohort (n={n_live_cows}): animal-disjoint cross-validation skipped"
                )
    else:
        # Adaptive splitting: clamp fold count to available herd size (e.g. 4-fold for 4 cows)
        effective_splits = min(n_cv_splits, n_live_cows)
        if effective_splits == n_live_cows:
            protocol_name = f"leave_one_animal_out (n={n_live_cows})"
        else:
            protocol_name = f"group_kfold_{effective_splits} (n={n_live_cows})"

        try:
            benchmarks = evaluate_baselines_vs_multimodal(
                cv_df,
                target_col="is_elevated_risk",
                group_col="cow_id",
                n_splits=effective_splits,
                seed=seed,
            )
            benchmarks["evaluation_protocol"] = protocol_name
            benchmarks["is_synthetic"] = is_synthetic
            benchmarks["n_splits"] = effective_splits
            benchmarks["cv_unavailable"] = False
        except Exception as exc:
            benchmarks = {
                "dataset": "MMCows Challenge 1",
                "evaluation_protocol": f"error_during_cv (n={n_live_cows})",
                "n_groups": n_live_cows,
                "n_splits": 0,
                "cv_unavailable": True,
                "cv_unavailable_reason": str(exc),
                "baselines": {},
                "multimodal_model": {},
                "is_synthetic": is_synthetic,
            }

    # 7. Ground-truth behavior concordance validation
    behavior_eval = validate_behavior_against_ground_truth(df_proc)
    benchmarks["behavior_ground_truth_validation"] = behavior_eval

    # 8. Write outputs if directory provided
    if output_dir is not None:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        summary_file = out_path / "cow_risk_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(cow_summaries, f, indent=2)

        flags_file = out_path / "auto_flags.json"
        with open(flags_file, "w", encoding="utf-8") as f:
            json.dump(auto_flags, f, indent=2)

        benchmark_file = out_path / "benchmark_results.json"
        with open(benchmark_file, "w", encoding="utf-8") as f:
            json.dump(benchmarks, f, indent=2)

        timeseries_file = out_path / "analyzed_timeseries.parquet"
        df_proc.to_parquet(timeseries_file, index=False)
        write_schema_sidecar(df_proc, out_path, "analyzed_timeseries", "1m", ["cow_id", "ts_utc"])

        if len(cow_day_df) > 0:
            cow_day_file = out_path / "cow_day_features.parquet"
            cow_day_df.to_parquet(cow_day_file, index=False)
            write_schema_sidecar(cow_day_df, out_path, "cow_day_features", "1d", ["cow_id", "date"])

    return {
        "cow_summaries": cow_summaries,
        "auto_flags": auto_flags,
        "benchmarks": benchmarks,
        "analyzed_df": df_proc,
        "cow_day_df": cow_day_df,
        "tiered_baselines": baselines_by_cow,
    }
