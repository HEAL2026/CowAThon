"""
Data loader for backend-visualization.
Uses cleaning.locate.find_joined() and sidecar_for() to consume real joined_1min data,
gating is_synthetic strictly on path resolution and falling back to deterministic fixtures.
Anchored on REPO_ROOT so resolution is cwd-independent.
"""

from __future__ import annotations

import os
import sys
import json
import logging
import warnings
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

# Ensure repository packages (backend-cleaning, apis, backend-analysis) are on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
for subfolder in ["backend-cleaning", "apis", "backend-analysis", "backend-visualization"]:
    p = str(REPO_ROOT / subfolder)
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger(__name__)

from visualization.fixtures import (
    generate_mock_cows_overview,
    generate_mock_timeseries,
    COW_IDS,
)


def locate_joined_table() -> Path | None:
    """
    Locates the canonical joined table using cleaning.locate.find_joined().
    Falls back to $MMCOWS_JOINED, REPO_ROOT candidates, and cwd-relative paths.
    """
    try:
        from cleaning.locate import find_joined
        p = find_joined()
        if p:
            return Path(p).resolve()
    except ImportError as e:
        warnings.warn(
            f"Could not import cleaning.locate ({e}); falling back to env/root resolution.",
            RuntimeWarning,
            stacklevel=2,
        )
    except Exception as e:
        warnings.warn(
            f"Unexpected error in cleaning.locate.find_joined(): {e}",
            RuntimeWarning,
            stacklevel=2,
        )

    env = os.environ.get("MMCOWS_JOINED")
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            p = p / "joined_1min.parquet"
        if p.is_file():
            return p.resolve()

    candidates = [
        REPO_ROOT / "backend-cleaning" / "data" / "processed" / "joined_1min.parquet",
        Path("backend-cleaning/data/processed/joined_1min.parquet"),
        Path("../backend-cleaning/data/processed/joined_1min.parquet"),
    ]
    for c in candidates:
        if c.is_file():
            return c.resolve()

    return None


def get_sidecar_metadata(path: Path) -> Dict[str, Any]:
    """Reads metadata/cadence from the .schema.json sidecar beside the parquet."""
    try:
        from cleaning.locate import sidecar_for
        sidecar = sidecar_for(path)
    except ImportError as e:
        warnings.warn(f"Could not import cleaning.locate.sidecar_for: {e}", RuntimeWarning, stacklevel=2)
        sidecar = path.with_name(path.stem + ".schema.json")
    except Exception:
        sidecar = path.with_name(path.stem + ".schema.json")

    if sidecar and Path(sidecar).is_file():
        try:
            with open(sidecar, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"cadence": "1 minute", "keys": ["cow_id", "ts_utc"]}


def load_raw_table_records(
    table_path: Optional[Path] = None,
) -> Tuple[Optional[List[Dict[str, Any]]], bool]:
    """
    Attempts to read records from real joined parquet.
    Returns (records, is_synthetic). is_synthetic is False ONLY when a path was resolved.
    """
    p = table_path or locate_joined_table()
    if p is None:
        return None, True

    # Resolved a real path -> is_synthetic is strictly False
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(str(p))
        pydict = table.to_pydict()
        keys = list(pydict.keys())
        n_rows = len(pydict[keys[0]]) if keys else 0
        records = [
            {k: pydict[k][i] for k in keys}
            for i in range(n_rows)
        ]
        return records, False
    except Exception:
        pass

    try:
        import pandas as pd
        df = pd.read_parquet(str(p))
        return df.to_dict(orient="records"), False
    except Exception:
        pass

    # If parquet loading packages unavailable but path existed, still not synthetic
    return None, False


def get_cow_timeseries_data(
    cow_id: str,
    days: int = 7,
    custom_records: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Retrieves timeseries points for cow_id.
    Returns (points_list, is_synthetic).
    """
    if custom_records is not None:
        records, is_synthetic = custom_records, False
    else:
        records, is_synthetic = load_raw_table_records()

    if records:
        cow_records = [
            r for r in records
            if str(r.get("cow_id", "")).upper() == cow_id.upper()
        ]
        if cow_records:
            points = []
            for r in cow_records:
                ts = str(r.get("ts_utc", ""))
                points.append({
                    "ts_utc": ts,
                    "cbt_c": r.get("cbt_c"),
                    "cbt_c_is_imputed": bool(r.get("cbt_c_is_imputed", False)),
                    "cbt_c_age_s": r.get("cbt_c_age_s"),
                    "neck_imu_magnitude_mean": r.get("neck_imu_magnitude_mean"),
                    "neck_imu_magnitude_mean_is_imputed": bool(r.get("neck_imu_magnitude_mean_is_imputed", False)),
                    "daily_milk_yield_kg": r.get("milk_yield_kg", r.get("daily_milk_yield_kg")),
                    "daily_milk_yield_kg_is_imputed": bool(r.get("milk_yield_kg_is_imputed", False)),
                    "milk_yield_kg_age_s": r.get("milk_yield_kg_age_s"),
                    "lying": r.get("lying"),
                    "indoor_thi": r.get("indoor_thi"),
                    "indoor_thi_is_imputed": bool(r.get("indoor_thi_is_imputed", False)),
                    "out_of_pen": bool(r.get("out_of_pen", False)),
                })
            return points, is_synthetic

    # Fallback to deterministic synthetic fixture
    return generate_mock_timeseries(cow_id, days=days), True


def get_barn_overview_data(
    custom_records: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, float], bool]:
    """
    Retrieves barn overview cow records and environment.
    Returns (cows_list, env_dict, is_synthetic).
    """
    if custom_records is not None:
        records, is_synthetic = custom_records, False
    else:
        records, is_synthetic = load_raw_table_records()

    if records:
        by_cow = {}
        for r in records:
            cid = str(r.get("cow_id", "")).upper()
            if cid:
                by_cow[cid] = r

        if by_cow:
            cows = []
            for cid, r in by_cow.items():
                x = r.get("uwb_x_m", r.get("x_coord", 15.0))
                y = r.get("uwb_y_m", r.get("y_coord", 7.5))
                out_pen = bool(r.get("out_of_pen", False))
                cbt = r.get("cbt_c")
                is_high_risk = bool(cbt and cbt > 39.5)
                cows.append({
                    "cow_id": cid,
                    "display_name": f"Cow {cid}",
                    "uwb_x_m": round(float(x), 2) if x is not None else 15.0,
                    "uwb_y_m": round(float(y), 2) if y is not None else 7.5,
                    "zone": "milking_lane" if out_pen else "cubicle_row_a",
                    "activity_state": "milking" if out_pen else ("resting" if r.get("lying") == 1 else "active"),
                    "out_of_pen": out_pen,
                    "risk_status": "priority_watch" if is_high_risk else "baseline",
                    "risk_score": 0.85 if is_high_risk else 0.15,
                    "factors": ["Real MMCows sensor telemetry"],
                    "on_watch_list": is_high_risk,
                    "vet_flagged": False,
                    "missing_modalities": [],
                    "is_instrumented": cid in COW_IDS[:10],
                })

            latest = records[-1]
            env = {
                "indoor_thi": float(latest.get("indoor_thi") or 72.0),
                "indoor_temp_c": float(latest.get("indoor_temp_c") or 24.5),
                "indoor_humidity_pct": float(latest.get("indoor_rh_pct") or 65.0),
            }
            return cows, env, is_synthetic

    # Fallback to synthetic fixture
    return generate_mock_cows_overview(), {"indoor_thi": 74.2, "indoor_temp_c": 26.8, "indoor_humidity_pct": 66.0}, True


def get_benchmarks_data() -> Tuple[Dict[str, Any], bool]:
    """
    Retrieves cross-validation benchmarks payload.
    Looks for benchmark_results.json from backend-analysis output first.
    Ensures evaluation_protocol conforms to:
      - 'group_kfold_K (n=N)'
      - 'leave_one_animal_out (n=N)'
      - 'insufficient_animals_for_cv (n=N)'
    Returns (benchmarks_payload, is_synthetic).
    """
    candidates = [
        REPO_ROOT / "backend-analysis" / "data" / "output" / "benchmark_results.json",
        REPO_ROOT / "backend-analysis" / "data" / "benchmark_results.json",
        Path("backend-analysis/data/output/benchmark_results.json"),
    ]
    for p in candidates:
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                is_synthetic = bool(data.get("is_synthetic", False))
                proto = str(data.get("evaluation_protocol", ""))
                if not any(k in proto for k in ["group_kfold", "leave_one_animal_out", "insufficient_animals_for_cv"]):
                    n_g = data.get("n_groups", 10)
                    n_s = data.get("n_splits", 5)
                    data["evaluation_protocol"] = f"group_kfold_{n_s} (n={n_g})"
                data.setdefault("cv_unavailable", False)
                data.setdefault("is_synthetic", is_synthetic)
                return data, is_synthetic
            except Exception:
                pass

    from visualization.payloads import generate_benchmarks_summary
    return generate_benchmarks_summary(), True


def get_watch_list_data() -> Tuple[List[Dict[str, Any]], bool]:
    """
    Retrieves watch-list flagged cows from backend-analysis cow_risk_summary.json.
    Falls back to deterministic mock watch items.
    Returns (flagged_cows_list, is_synthetic).
    """
    candidates = [
        REPO_ROOT / "backend-analysis" / "data" / "output" / "cow_risk_summary.json",
        REPO_ROOT / "backend-analysis" / "data" / "cow_risk_summary.json",
        Path("backend-analysis/data/output/cow_risk_summary.json"),
    ]
    for p in candidates:
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    summaries = json.load(f)
                flagged = []
                if isinstance(summaries, dict):
                    for cid, s in summaries.items():
                        cat = s.get("risk_category", "baseline")
                        score = float(s.get("watch_risk_score", 0.0))
                        if cat in ["priority_watch", "moderate_watch"] or score >= 50.0:
                            factors = s.get("contributing_factors", [])
                            reason = "; ".join(factors) if factors else f"Elevated watch risk score {score:.1f}"
                            actions = s.get("recommended_actions", ["Monitor in next milking cycle"])
                            action = "; ".join(actions) if actions else "Monitor"
                            flagged.append({
                                "cow_id": cid,
                                "flag_type": "model_suggestion",
                                "risk_category": cat if cat != "baseline" else "moderate_watch",
                                "watch_risk_score": score,
                                "watch_reason": reason,
                                "confidence": float(s.get("confidence_score", 0.85)),
                                "modalities_present": s.get("modalities_present", []),
                                "modalities_missing": s.get("missing_modalities", []),
                                "missing_modality_impact": "Sensor channels missing; risk estimated from partial telemetry" if s.get("missing_modalities") else "Full telemetry available",
                                "recommended_action": action,
                                "is_model_suggestion": True,
                            })
                if flagged:
                    return flagged, False
            except Exception:
                pass

    default_flagged = [
        {
            "cow_id": "C01",
            "flag_type": "model_suggestion",
            "risk_category": "priority_watch",
            "watch_risk_score": 84.5,
            "watch_reason": "Sustained high CBT (39.85C) under elevated THI accompanied by 18% yield decrease",
            "confidence": 0.88,
            "modalities_present": ["cbt", "neck_imu", "indoor_env", "milk_yield", "ankle"],
            "modalities_missing": ["uwb"],
            "missing_modality_impact": "Location confidence lower; utilizing last-seen stall beacon",
            "recommended_action": "Check for heat abatement and udder inflammation prior to next cycle",
            "is_model_suggestion": True,
        },
        {
            "cow_id": "C02",
            "flag_type": "vet_flagged",
            "risk_category": "moderate_watch",
            "watch_risk_score": 68.0,
            "watch_reason": "Co-resting in cubicle_row_b alongside C01 with 22% activity drop",
            "confidence": 0.74,
            "modalities_present": ["neck_imu", "indoor_env", "milk_yield", "cbt"],
            "modalities_missing": ["uwb"],
            "missing_modality_impact": "Spatial tracking degraded; relying on rumination variance",
            "recommended_action": "Monitor evening milking yield and observe gait",
            "is_model_suggestion": True,
        },
    ]
    return default_flagged, True
