"""
Exporter utility to generate static visualization payload files.
Consumes data_loader functions to export real analysis/cleaning data when available,
falling back gracefully to deterministic synthetic fixtures.
"""

import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

REPO_ROOT = Path(__file__).resolve().parents[2]
for sub in ["backend-cleaning", "apis", "backend-analysis", "backend-visualization"]:
    p = str(REPO_ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

from visualization.payloads import (
    generate_barn_overview,
    generate_cow_timeseries,
    generate_milking_stalls,
    generate_watch_list,
    generate_benchmarks_summary,
    generate_integrations_feasibility,
    generate_pen_map,
    generate_herd_health,
    generate_attribution,
    generate_impact,
)
from visualization.fixtures import (
    COW_IDS,
)
from visualization.data_loader import (
    get_barn_overview_data,
    get_cow_timeseries_data,
    get_watch_list_data,
    get_benchmarks_data,
    get_pen_map_data,
    get_herd_health_data,
    get_attribution_data,
    get_impact_data,
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
    cows_overview, env, is_synth = get_barn_overview_data()
    barn_payload = generate_barn_overview(
        cows_data=cows_overview,
        indoor_thi=env.get("indoor_thi", 74.2),
        indoor_temp_c=env.get("indoor_temp_c", 26.8),
        indoor_humidity_pct=env.get("indoor_humidity_pct", 66.0),
        ts_utc=now_utc,
        is_synthetic=is_synth,
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
    flagged, is_synth = get_watch_list_data()
    watch_payload = generate_watch_list(flagged, ts_utc=now_utc)
    watch_payload["is_synthetic"] = is_synth
    watch_path = os.path.join(output_dir, "watch_list.json")
    with open(watch_path, "w", encoding="utf-8") as f:
        json.dump(watch_payload, f, indent=2)
    results["watch_list"] = watch_path

    # 4. Cross-validation benchmarks summary
    benchmarks_payload, is_synth = get_benchmarks_data()
    benchmarks_payload["is_synthetic"] = is_synth
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

    # 6. 2D Pen map (S12)
    pen_map_payload, is_synth = get_pen_map_data()
    pen_map_payload["is_synthetic"] = is_synth
    pen_map_path = os.path.join(output_dir, "pen_map.json")
    with open(pen_map_path, "w", encoding="utf-8") as f:
        json.dump(pen_map_payload, f, indent=2)
    results["pen_map"] = pen_map_path

    # 7. Herd health table (S12)
    herd_health_payload, is_synth = get_herd_health_data()
    herd_health_payload["is_synthetic"] = is_synth
    herd_health_path = os.path.join(output_dir, "herd_health.json")
    with open(herd_health_path, "w", encoding="utf-8") as f:
        json.dump(herd_health_payload, f, indent=2)
    results["herd_health"] = herd_health_path

    # 8. Outbreak transmission attribution (S12)
    attribution_payload, is_synth = get_attribution_data()
    attribution_payload["is_synthetic"] = is_synth
    attribution_path = os.path.join(output_dir, "attribution.json")
    with open(attribution_path, "w", encoding="utf-8") as f:
        json.dump(attribution_payload, f, indent=2)
    results["attribution"] = attribution_path

    # 9. Outbreak mitigation & economic impact (S12)
    impact_payload, is_synth = get_impact_data()
    impact_payload["is_synthetic"] = is_synth
    impact_path = os.path.join(output_dir, "impact.json")
    with open(impact_path, "w", encoding="utf-8") as f:
        json.dump(impact_payload, f, indent=2)
    results["impact"] = impact_path

    # 10. Cow timeseries (for all 16 animals)
    cows_dir = os.path.join(output_dir, "cows")
    os.makedirs(cows_dir, exist_ok=True)
    for cid in COW_IDS:
        ts_points, is_synth = get_cow_timeseries_data(cid, days=7)
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
        cow_payload["is_synthetic"] = is_synth
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
    print(f"Exported {len(outputs)} payload categories to {args.output_dir}")
