"""CLI runner for MMCows multi-modal backend analysis pipeline.

Ingests real MMCows joined 1-minute Parquet data
(backend-cleaning/data/processed/joined_1min.parquet) or falls back gracefully
to deterministic synthetic fixtures when the 11 GB dataset is not on disk.

Exports:
- cow_risk_summary.json
- benchmark_results.json
- analyzed_timeseries.parquet

Usage:
    python3 -m analysis.run
    python3 -m analysis.run --parquet path/to/joined_1min.parquet --out data/output
    python3 -m analysis.run --cows C01,C02,C03
"""

from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence
import pandas as pd

from .pipeline import run_analysis_pipeline
from .fixtures import generate_synthetic_mmcows_data
from .backtrace_eval import evaluate_backtrace_against_synthetic


def find_default_parquet_path() -> Optional[Path]:
    """Search for canonical joined_1min.parquet using cleaning.locate."""
    repo_root = Path(__file__).resolve().parents[2]
    cleaning_dir = repo_root / "backend-cleaning"
    if str(cleaning_dir) not in sys.path:
        sys.path.insert(0, str(cleaning_dir))
    try:
        from cleaning.locate import find_joined
        found = find_joined()
        if found is not None and Path(found).is_file():
            return Path(found).resolve()
    except ImportError:
        pass

    # Direct env resolution
    env_path = os.environ.get("MMCOWS_JOINED") or os.environ.get("MMCOWS_PARQUET")
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_dir():
            p = p / "joined_1min.parquet"
        if p.is_file():
            return p.resolve()

    candidates = [
        repo_root / "backend-cleaning" / "data" / "processed" / "joined_1min.parquet",
        Path("backend-cleaning/data/processed/joined_1min.parquet"),
        Path("../backend-cleaning/data/processed/joined_1min.parquet"),
    ]
    for candidate in candidates:
        if candidate.resolve().is_file():
            return candidate.resolve()
    return None


def run_cli(args_list: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run MMCows multi-modal analysis pipeline against real parquet data or synthetic fallback."
    )
    parser.add_argument(
        "--parquet",
        "-p",
        type=str,
        default=None,
        help="Path to joined_1min.parquet. Defaults to backend-cleaning/data/processed/joined_1min.parquet.",
    )
    parser.add_argument(
        "--out",
        "-o",
        type=str,
        default=None,
        help="Output directory for generated JSON/parquet files. Defaults to backend-analysis/data/output.",
    )
    parser.add_argument(
        "--cows",
        type=str,
        default=None,
        help="Comma-separated list of cow IDs to filter (e.g. C01,C02).",
    )
    parser.add_argument(
        "--n-splits",
        type=int,
        default=5,
        help="Number of animal-disjoint cross-validation folds (default: 5).",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Fail if parquet file does not exist rather than falling back to synthetic fixtures.",
    )
    parser.add_argument(
        "--eval-backtrace",
        action="store_true",
        help="Execute S11 transmission backtrace evaluation benchmark against synthetic labels ground truth.",
    )
    parser.add_argument(
        "--export-vis-dir",
        type=str,
        default=None,
        help="Optional directory in backend-visualization to copy analysis artifacts.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress console output.",
    )

    args = parser.parse_args(args_list)

    # 1. Determine Parquet Path
    parquet_path: Optional[Path] = None
    if args.parquet:
        p = Path(args.parquet)
        if p.exists():
            parquet_path = p
        else:
            if args.no_fallback:
                sys.stderr.write(f"Error: Specified parquet file not found: {args.parquet}\n")
                return 1
    else:
        parquet_path = find_default_parquet_path()

    # 2. Determine Output Directory
    repo_root = Path(__file__).resolve().parents[2]
    if args.out:
        out_dir = Path(args.out)
    else:
        out_dir = repo_root / "backend-analysis" / "data" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 3. Load Data
    is_synthetic = False
    if parquet_path is not None and parquet_path.exists():
        if not args.quiet:
            print(f"[backend-analysis] Ingesting real MMCows dataset from: {parquet_path}")
        df = pd.read_parquet(parquet_path)
        is_synthetic = False
    else:
        if args.no_fallback:
            sys.stderr.write("Error: Real MMCows parquet not found and --no-fallback specified.\n")
            return 1
        if not args.quiet:
            print("[backend-analysis] Real joined_1min.parquet not found on disk.")
            print("[backend-analysis] Generating deterministic MMCows synthetic fixture (is_synthetic=True).")
        df = generate_synthetic_mmcows_data(n_cows=10, n_minutes=120, seed=42)
        is_synthetic = True

    # 4. Optional cow filtering
    if args.cows:
        target_cows = [c.strip().upper() for c in args.cows.split(",") if c.strip()]
        df = df[df["cow_id"].isin(target_cows)].copy()
        if len(df) == 0:
            sys.stderr.write(f"Error: No data rows found matching cows {target_cows}\n")
            return 1

    # 5. Execute Pipeline
    n_splits = args.n_splits
    n_unique_cows = df["cow_id"].nunique()
    if n_unique_cows < n_splits:
        n_splits = max(2, n_unique_cows)

    result = run_analysis_pipeline(
        df=df,
        output_dir=out_dir,
        n_cv_splits=n_splits,
        is_synthetic=is_synthetic,
    )

    # 6. S11 Outbreak Backtrace Benchmark (if requested)
    backtrace_benchmark = None
    if args.eval_backtrace:
        if not args.quiet:
            print("[backend-analysis] Evaluating S11 outbreak backtrace against synthetic ground truth...")
        backtrace_benchmark = evaluate_backtrace_against_synthetic(
            output_dir=out_dir,
            n_permutations=100,
            seed=42,
        )

    # 7. Optional visualization export copy
    if args.export_vis_dir:
        vis_dir = Path(args.export_vis_dir)
        vis_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        export_files = [
            "cow_risk_summary.json",
            "auto_flags.json",
            "benchmark_results.json",
            "backtrace_result.json",
            "backtrace_benchmark.json",
            "analyzed_timeseries.schema.json",
            "cow_day_features.schema.json",
        ]
        for fname in export_files:
            src = out_dir / fname
            if src.exists():
                shutil.copy2(src, vis_dir / fname)

    # 7. Print summary report
    if not args.quiet:
        cow_summaries = result["cow_summaries"]
        benchmarks = result["benchmarks"]
        auto_flags = result.get("auto_flags", [])
        print("\n" + "=" * 80)
        print(" MMCows Multi-Modal Dairy Health & Mastitis Risk Pipeline Run")
        print(f" Data Source: {'Real MMCows Parquet' if not is_synthetic else 'Synthetic Fixture Fallback'}")
        print(f" Entities Analyzed: {len(cow_summaries)} | Output Directory: {out_dir}")
        print("=" * 80)

        header = f"{'Cow ID':<8} {'Watch Risk':<12} {'Health Idx':<12} {'Mastitis':<12} {'Baseline Tier':<16} {'Category':<16}"
        print(header)
        print("-" * len(header))
        for cid, summary in sorted(cow_summaries.items()):
            score = summary.get("watch_risk_score", 0.0)
            category = summary.get("risk_category", "unknown")
            h_idx = summary.get("health_index")
            h_str = f"{h_idx:.1f}" if h_idx is not None else "N/A"
            m_risk = summary.get("acute_mastitis_risk", 0.0)
            b_tier = summary.get("baseline_tier", "none")
            print(f"{cid:<8} {score:<12.1f} {h_str:<12} {m_risk:<12.1f} {b_tier:<16} {category:<16}")

        if auto_flags:
            print("\nTriggered Auto-Flags (Mastitis Risk >= 70.0):")
            for flag in auto_flags:
                cid = flag["cow_id"]
                risk = flag["risk_score"]
                signals = "; ".join(flag["top_contributing_signals"][:2])
                print(f"  [AUTO-FLAG] Cow {cid}: Risk = {risk:.1f} | Signals: {signals}")

        print("\nAnimal-Disjoint Cross-Validation Benchmarks (ROC-AUC):")
        print(f"  Protocol: {benchmarks.get('evaluation_protocol', 'unknown')}")
        baselines = benchmarks.get("baselines", {})
        multimodal = benchmarks.get("multimodal_model", {})
        for name, b_info in baselines.items():
            mean_auc = b_info.get("roc_auc_mean", 0.0)
            std_auc = b_info.get("roc_auc_std", 0.0)
            print(f"  - {name:<26}: ROC-AUC = {mean_auc:.3f} +/- {std_auc:.3f}")
        mm_mean = multimodal.get("roc_auc_mean", 0.0)
        mm_std = multimodal.get("roc_auc_std", 0.0)
        print(f"  - {'multimodal_risk_model':<26}: ROC-AUC = {mm_mean:.3f} +/- {mm_std:.3f}")

        gt_val = benchmarks.get("behavior_ground_truth_validation", {})
        if gt_val.get("has_ground_truth_labels"):
            print("\nGround-Truth Video Concordance:")
            print(f"  - Labeled Observations: {gt_val.get('n_labeled_rows')}")
            print(f"  - Ankle Concordance   : {gt_val.get('ankle_sensor_ground_truth_concordance', 0.0):.2%}")
            posture_acc = gt_val.get("imu_posture_model", {}).get("accuracy", 0.0)
            print(f"  - IMU Posture Accuracy: {posture_acc:.2%}")

        if backtrace_benchmark is not None:
            print("\nS11 Outbreak Backtrace & Route Attribution Benchmark:")
            print(f"  - Route Accuracy      : {backtrace_benchmark.get('route_accuracy', 0.0):.1%}")
            print(f"  - Source Hit Rate     : {backtrace_benchmark.get('source_hit_rate', 0.0):.1%}")
            prec1 = backtrace_benchmark.get('overall_precision_at_1')
            rec1 = backtrace_benchmark.get('overall_recall_at_1')
            if prec1 is not None:
                print(f"  - Precision@1 (Index) : {prec1:.1%}")
            if rec1 is not None:
                print(f"  - Recall@1 (Index)    : {rec1:.1%}")
        print("=" * 80 + "\n")

    return 0


def main():
    sys.exit(run_cli())


if __name__ == "__main__":
    main()
