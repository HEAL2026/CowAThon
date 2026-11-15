"""End-to-end analysis pipeline execution.

Runs:
1. Feature extraction (THI, CBT strain, IMU activity, rumination proxy).
2. Multimodal watch-list risk scoring and confidence estimation.
3. Group-aware animal-disjoint cross-validation benchmarking against single-sensor baselines.
4. Output payload generation for backend-visualization and frontend consumption.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import pandas as pd

from .env_thermal import calculate_thi, categorize_thi_strain, calculate_thermal_load
from .cbt_strain import calculate_cbt_strain_score, detect_temperature_spikes
from .behavior import calculate_activity_index, classify_posture_state, calculate_rumination_proxy
from .risk_scorer import MultimodalRiskScorer
from .baselines import evaluate_baselines_vs_multimodal


def run_analysis_pipeline(
    df: pd.DataFrame,
    output_dir: Path | str | None = None,
    n_cv_splits: int = 5,
    seed: int = 0,
) -> dict[str, Any]:
    """Execute the full backend analysis pipeline.

    Args:
        df: Input DataFrame with joined observation records.
        output_dir: Optional directory to save output JSON/parquet artifacts.
        n_cv_splits: Number of folds for animal-disjoint cross-validation.
        seed: Random seed for deterministic reproducibility.

    Returns:
        Dictionary containing cow summaries, time series, and benchmark results.
    """
    df_proc = df.copy()

    # 1. Environmental THI
    if "thi" not in df_proc.columns and "temp_c" in df_proc.columns and "rh_pct" in df_proc.columns:
        df_proc["thi"] = calculate_thi(df_proc["temp_c"], df_proc["rh_pct"])
    if "thi" in df_proc.columns:
        df_proc["thi_category"] = categorize_thi_strain(df_proc["thi"])

    # 2. CBT Strain
    if "cbt" in df_proc.columns:
        df_proc["cbt_strain_score"] = calculate_cbt_strain_score(df_proc["cbt"])

    # 3. Behavioral IMU Features
    if "activity_index" not in df_proc.columns:
        df_proc["activity_index"] = calculate_activity_index(df_proc)
    if "posture_state" not in df_proc.columns:
        df_proc["posture_state"] = classify_posture_state(df_proc["activity_index"])
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

    # 5. Group Summaries per Animal (Latest Status)
    cow_summaries: dict[str, Any] = {}
    for cow_id, group in df_proc.groupby("cow_id"):
        latest_row = group.sort_values("ts_utc").iloc[-1]
        score_info = scorer.score_record(latest_row)

        cow_summaries[str(cow_id)] = {
            "cow_id": str(cow_id),
            "latest_ts_utc": str(latest_row.get("ts_utc", "")),
            "watch_risk_score": score_info["watch_risk_score"],
            "risk_category": score_info["risk_category"],
            "confidence_score": score_info["confidence_score"],
            "metrics": {
                "cbt_c": round(float(latest_row["cbt"]), 2) if "cbt" in latest_row and not pd.isna(latest_row["cbt"]) else None,
                "cbt_strain_score": round(float(latest_row.get("cbt_strain_score", 0.0)), 1),
                "ambient_thi": round(float(latest_row["thi"]), 1) if "thi" in latest_row and not pd.isna(latest_row["thi"]) else None,
                "thi_category": str(latest_row.get("thi_category", "unknown")),
                "activity_index": round(float(latest_row.get("activity_index", 0.0)), 3),
                "rumination_proxy": round(float(latest_row.get("rumination_proxy", 0.0)), 1),
                "daily_milk_yield_kg": round(float(latest_row["milk_yield"]), 1) if "milk_yield" in latest_row and not pd.isna(latest_row["milk_yield"]) else None,
                "milk_drop_pct": round(float(latest_row.get("milk_drop_pct", 0.0)), 1),
            },
            "modalities_present": score_info["modalities_present"],
            "missing_modalities": score_info["missing_modalities"],
            "contributing_factors": score_info["contributing_factors"],
            "recommended_actions": score_info["recommended_actions"],
            "is_model_suggestion": True,
        }

    # 6. Animal-Disjoint Cross-Validation Benchmarks
    benchmarks = evaluate_baselines_vs_multimodal(
        df_proc,
        target_col="is_elevated_risk",
        group_col="cow_id",
        n_splits=n_cv_splits,
        seed=seed,
    )

    # 7. Write outputs if directory provided
    if output_dir is not None:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        summary_file = out_path / "cow_risk_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(cow_summaries, f, indent=2)

        benchmark_file = out_path / "benchmark_results.json"
        with open(benchmark_file, "w", encoding="utf-8") as f:
            json.dump(benchmarks, f, indent=2)

        # Export timeseries parquet
        timeseries_file = out_path / "analyzed_timeseries.parquet"
        df_proc.to_parquet(timeseries_file, index=False)

    return {
        "cow_summaries": cow_summaries,
        "benchmarks": benchmarks,
        "analyzed_df": df_proc,
    }
