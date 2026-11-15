"""
Exporter utility to generate static visualization payload files or serve them.
Alignd with MMCows raw schema and backend-analysis CONTRACT.md.
"""

import json
import os
import argparse
from datetime import datetime, timezone
from typing import Dict, Any

from visualization.payloads import (
    generate_barn_overview,
    generate_cow_timeseries,
    generate_milking_stalls,
    generate_watch_list,
    generate_benchmarks_summary,
    generate_integrations_feasibility,
)
from visualization.fixtures import (
    generate_mock_cows_overview,
    generate_mock_timeseries,
    COW_IDS,
    INSTRUMENTED_COWS,
)


def export_all_payloads(output_dir: str = "backend-visualization/data/exported") -> Dict[str, str]:
    """
    Generates and saves all contract JSON payloads into the specified directory.
    Returns mapping of payload_name -> file_path.
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}
    now_utc = datetime(2023, 7, 28, 14, 0, tzinfo=timezone.utc).isoformat()

    # 1. Barn overview
    cows_overview = generate_mock_cows_overview()
    barn_payload = generate_barn_overview(
        cows_data=cows_overview,
        indoor_thi=74.2,
        indoor_temp_c=26.8,
        indoor_humidity_pct=66.0,
        ts_utc=now_utc,
        is_synthetic=True,
    )
    barn_path = os.path.join(output_dir, "barn_overview.json")
    with open(barn_path, "w", encoding="utf-8") as f:
        json.dump(barn_payload, f, indent=2)
    results["barn_overview"] = barn_path

    # 2. Milking stalls
    stalls_payload = generate_milking_stalls(ts_utc=now_utc)
    stalls_path = os.path.join(output_dir, "milking_stalls.json")
    with open(stalls_path, "w", encoding="utf-8") as f:
        json.dump(stalls_payload, f, indent=2)
    results["milking_stalls"] = stalls_path

    # 3. Watch list
    flagged = [
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
        },
    ]
    watch_payload = generate_watch_list(flagged, ts_utc=now_utc)
    watch_path = os.path.join(output_dir, "watch_list.json")
    with open(watch_path, "w", encoding="utf-8") as f:
        json.dump(watch_payload, f, indent=2)
    results["watch_list"] = watch_path

    # 4. Cross-validation benchmarks summary
    benchmarks_payload = generate_benchmarks_summary()
    benchmarks_path = os.path.join(output_dir, "benchmarks_summary.json")
    with open(benchmarks_path, "w", encoding="utf-8") as f:
        json.dump(benchmarks_payload, f, indent=2)
    results["benchmarks_summary"] = benchmarks_path

    # 5. Integrations feasibility
    feasibility_payload = generate_integrations_feasibility()
    feasibility_path = os.path.join(output_dir, "integrations_feasibility.json")
    with open(feasibility_path, "w", encoding="utf-8") as f:
        json.dump(feasibility_payload, f, indent=2)
    results["integrations_feasibility"] = feasibility_path

    # 6. Cow timeseries (for all 16 animals)
    cows_dir = os.path.join(output_dir, "cows")
    os.makedirs(cows_dir, exist_ok=True)
    for cid in COW_IDS:
        ts_points = generate_mock_timeseries(cid, days=7)
        resting_hist = [
            {
                "session_id": f"rest_{cid}_01",
                "zone": "cubicle_row_b" if "1" in cid else "cubicle_row_a",
                "start_utc": "2023-07-28T09:30:00Z",
                "end_utc": "2023-07-28T12:00:00Z",
                "duration_minutes": 150,
            }
        ]
        co_resters = [
            {
                "cow_id": "C02" if cid == "C01" else "C01",
                "shared_zone": "cubicle_row_b",
                "overlap_minutes": 110,
                "last_shared_utc": "2023-07-28T12:00:00Z",
            }
        ] if cid in ["C01", "C02"] else []

        cow_payload = generate_cow_timeseries(
            cow_id=cid,
            timeseries_points=ts_points,
            resting_history=resting_hist,
            co_resting_cows=co_resters,
            baseline_yield_kg=26.5 if cid == "C01" else 31.0,
        )
        c_path = os.path.join(cows_dir, f"{cid}.json")
        with open(c_path, "w", encoding="utf-8") as f:
            json.dump(cow_payload, f, indent=2)

    results["cows_dir"] = cows_dir
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export visualization payloads.")
    parser.add_argument(
        "--output-dir",
        default="backend-visualization/data/exported",
        help="Target folder for exported JSON payloads",
    )
    args = parser.parse_args()
    outputs = export_all_payloads(args.output_dir)
    print(f"Exported {len(outputs)} payload sets to {args.output_dir}")
