"""
Payload shaping functions for the frontend dashboard.
Transforms tabular inputs into validated, JSON-serializable structures.
Alignd with MMCows raw schema and backend-analysis CONTRACT.md.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import math

REPO_ROOT = Path(__file__).resolve().parents[2]
APIS_PATH = str(REPO_ROOT / "apis")
if APIS_PATH not in sys.path:
    sys.path.insert(0, APIS_PATH)


def generate_barn_overview(
    cows_data: List[Dict[str, Any]],
    indoor_thi: float = 72.0,
    indoor_temp_c: float = 24.5,
    indoor_humidity_pct: float = 65.0,
    barn_id: str = "main_barn_01",
    ts_utc: Optional[str] = None,
    is_synthetic: bool = False,
) -> Dict[str, Any]:
    """
    Constructs the spatial barn overview payload including cow dots,
    out_of_pen milking states, zone occupancies, and density heatmap grid.
    """
    if ts_utc is None:
        ts_utc = datetime(2023, 7, 28, 14, 0, tzinfo=timezone.utc).isoformat()

    cows_payload = []
    zone_counts: Dict[str, int] = {}
    zone_idling_totals: Dict[str, float] = {}

    grid_w, grid_h = 20, 10
    grid = [[0.0 for _ in range(grid_w)] for _ in range(grid_h)]

    for cow in cows_data:
        cid = str(cow["cow_id"])
        display_name = str(cow.get("display_name", cid))
        x = float(cow.get("uwb_x_m", cow.get("x_coord", 0.0)))
        y = float(cow.get("uwb_y_m", cow.get("y_coord", 0.0)))
        zone = str(cow.get("zone", "cubicle_row_a"))
        activity = str(cow.get("activity_state", "resting"))
        out_of_pen = bool(cow.get("out_of_pen", False))
        risk_status = str(cow.get("risk_status", "baseline"))
        risk_score = float(cow.get("risk_score", 0.1))
        factors = list(cow.get("factors", []))
        on_watch_list = bool(cow.get("on_watch_list", False))
        vet_flagged = bool(cow.get("vet_flagged", False))
        missing_modalities = list(cow.get("missing_modalities", []))
        is_instrumented = bool(cow.get("is_instrumented", True))

        zone_counts[zone] = zone_counts.get(zone, 0) + 1
        idling_m = float(cow.get("idling_minutes", 30.0))
        zone_idling_totals[zone] = zone_idling_totals.get(zone, 0.0) + idling_m

        cows_payload.append({
            "cow_id": cid,
            "display_name": display_name,
            "uwb_x_m": round(x, 2),
            "uwb_y_m": round(y, 2),
            "x_coord": round(x, 2),
            "y_coord": round(y, 2),
            "zone": zone,
            "activity_state": activity,
            "out_of_pen": out_of_pen,
            "risk_status": risk_status,
            "risk_score": round(risk_score, 3),
            "factors": factors,
            "on_watch_list": on_watch_list,
            "vet_flagged": vet_flagged,
            "missing_modalities": missing_modalities,
            "is_instrumented": is_instrumented,
        })

        # Populate heatmap density grid (clamped to grid boundaries)
        gx = max(0, min(grid_w - 1, int(x / 1.5)))
        gy = max(0, min(grid_h - 1, int(y / 1.5)))
        grid[gy][gx] += 1.0

    # Normalize heatmap density between 0.0 and 1.0
    max_val = max([max(row) for row in grid]) if grid else 1.0
    if max_val > 0:
        grid = [[round(val / max_val, 2) for val in row] for row in grid]

    zones_payload = []
    zone_capacities = {
        "cubicle_row_a": 15,
        "cubicle_row_b": 15,
        "feed_alley": 25,
        "holding_pen": 10,
        "milking_lane": 8,
    }
    for zid, count in zone_counts.items():
        cap = zone_capacities.get(zid, 20)
        tot_idling = zone_idling_totals.get(zid, 0.0)
        mean_idling = round(tot_idling / count, 1) if count > 0 else 0.0
        zone_type = "resting" if "cubicle" in zid else ("feeding" if "feed" in zid else "transit")
        zones_payload.append({
            "zone_id": zid,
            "zone_type": zone_type,
            "cow_count": count,
            "capacity": cap,
            "mean_idling_minutes": mean_idling,
        })

    return {
        "ts_utc": ts_utc,
        "barn_id": barn_id,
        "indoor_thi": round(indoor_thi, 1),
        "indoor_temp_c": round(indoor_temp_c, 1),
        "indoor_humidity_pct": round(indoor_humidity_pct, 1),
        "is_synthetic": is_synthetic,
        "cows": cows_payload,
        "zones": zones_payload,
        "heatmap_grid": {
            "resolution_m": 1.5,
            "width": grid_w,
            "height": grid_h,
            "density_matrix": grid,
        },
    }


def generate_cow_timeseries(
    cow_id: str,
    timeseries_points: List[Dict[str, Any]],
    resting_history: Optional[List[Dict[str, Any]]] = None,
    co_resting_cows: Optional[List[Dict[str, Any]]] = None,
    baseline_yield_kg: float = 30.0,
) -> Dict[str, Any]:
    """
    Constructs multi-temporal trajectory for an MMCow animal,
    preserving imputation flags, lying posture, and contact exposure.
    """
    if resting_history is None:
        resting_history = []
    if co_resting_cows is None:
        co_resting_cows = []

    ts_list = []
    cbt_vals = []
    milk_vals = []

    for pt in timeseries_points:
        t_utc = str(pt["ts_utc"])
        cbt = pt.get("cbt_c")
        cbt_imp = bool(pt.get("cbt_c_is_imputed", False))
        imu = pt.get("neck_imu_magnitude_mean")
        imu_imp = bool(pt.get("neck_imu_magnitude_mean_is_imputed", False))
        milk = pt.get("daily_milk_yield_kg", pt.get("daily_milk_yield_l"))
        milk_imp = bool(pt.get("daily_milk_yield_kg_is_imputed", pt.get("daily_milk_yield_l_is_imputed", False)))
        lying = pt.get("lying")
        thi = pt.get("indoor_thi")
        thi_imp = bool(pt.get("indoor_thi_is_imputed", False))
        out_pen = bool(pt.get("out_of_pen", False))

        if cbt is not None:
            cbt_vals.append(float(cbt))
        if milk is not None:
            milk_vals.append(float(milk))

        ts_list.append({
            "ts_utc": t_utc,
            "cbt_c": round(float(cbt), 2) if cbt is not None else None,
            "cbt_c_is_imputed": cbt_imp,
            "neck_imu_magnitude_mean": round(float(imu), 3) if imu is not None else None,
            "neck_imu_magnitude_mean_is_imputed": imu_imp,
            "daily_milk_yield_kg": round(float(milk), 2) if milk is not None else None,
            "daily_milk_yield_kg_is_imputed": milk_imp,
            "lying": lying,
            "indoor_thi": round(float(thi), 1) if thi is not None else None,
            "indoor_thi_is_imputed": thi_imp,
            "out_of_pen": out_pen,
        })

    mean_cbt = round(sum(cbt_vals) / len(cbt_vals), 2) if cbt_vals else None
    latest_milk = round(milk_vals[-1], 2) if milk_vals else baseline_yield_kg

    # Anomaly status based on thermal strain / yield deviation
    cbt_anomaly = (mean_cbt is not None) and (mean_cbt > 39.2)
    if cbt_anomaly or (latest_milk < baseline_yield_kg * 0.82):
        status = "priority_watch" if cbt_anomaly and latest_milk < baseline_yield_kg * 0.85 else "moderate_watch"
    else:
        status = "baseline"

    start_utc = ts_list[0]["ts_utc"] if ts_list else datetime(2023, 7, 21, 12, 30, tzinfo=timezone.utc).isoformat()
    end_utc = ts_list[-1]["ts_utc"] if ts_list else start_utc

    return {
        "cow_id": cow_id,
        "data_range": {
            "start_utc": start_utc,
            "end_utc": end_utc,
        },
        "summary": {
            "baseline_daily_milk_kg": round(baseline_yield_kg, 2),
            "current_daily_milk_kg": latest_milk,
            "mean_cbt_c": mean_cbt,
            "cbt_anomaly_detected": cbt_anomaly,
            "risk_category": status,
        },
        "timeseries": ts_list,
        "resting_history": resting_history,
        "co_resting_cows": co_resting_cows,
    }


def generate_milking_stalls(
    stall_data: Optional[List[Dict[str, Any]]] = None,
    ts_utc: Optional[str] = None,
    parlor_id: str = "parlor_alpha",
    num_stalls: int = 8,
) -> Dict[str, Any]:
    """
    Constructs parlor and stall status payload.
    """
    if ts_utc is None:
        ts_utc = datetime(2023, 7, 28, 14, 0, tzinfo=timezone.utc).isoformat()

    stalls_payload = []
    if stall_data is not None:
        stalls_payload = stall_data
    else:
        for s in range(1, num_stalls + 1):
            is_active = s in [1, 2, 4, 7]
            stalls_payload.append({
                "stall_number": s,
                "state": "active" if is_active else "idle",
                "current_cow_id": f"C{s:02d}" if is_active else None,
                "session_yield_kg": round(11.5 + s * 0.7, 1) if is_active else None,
                "flow_rate_kg_min": 2.7 if is_active else None,
                "last_completed_cycle": {
                    "cow_id": f"C{s+2:02d}",
                    "yield_kg": 13.8,
                    "completed_at_utc": ts_utc,
                    "flagged_risk": (s == 4),
                },
            })

    return {
        "ts_utc": ts_utc,
        "parlor_id": parlor_id,
        "stalls": stalls_payload,
    }


def generate_watch_list(
    flagged_cows: List[Dict[str, Any]],
    ts_utc: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Constructs the watch list payload stating uncertainty,
    missing modalities, and non-clinical risk suggestions.
    """
    if ts_utc is None:
        ts_utc = datetime(2023, 7, 28, 14, 0, tzinfo=timezone.utc).isoformat()

    items = []
    for item in flagged_cows:
        cid = str(item["cow_id"])
        flag_type = str(item.get("flag_type", "model_suggestion"))
        category = str(item.get("risk_category", "moderate_watch"))
        score = float(item.get("watch_risk_score", item.get("risk_score", 65.0)))
        reason = str(item.get("watch_reason", "Observed metric deviation"))
        conf = float(item.get("confidence", item.get("confidence_score", 0.75)))
        present = list(item.get("modalities_present", ["neck_imu", "milk_yield"]))
        missing = list(item.get("modalities_missing", []))
        impact = str(item.get("missing_modality_impact", "Standard monitoring active"))
        rec = str(item.get("recommended_action", "Visual check prior to evening milking"))

        items.append({
            "cow_id": cid,
            "flag_type": flag_type,
            "risk_category": category,
            "watch_risk_score": round(score, 1),
            "watch_reason": reason,
            "confidence": round(conf, 2),
            "modalities_present": present,
            "modalities_missing": missing,
            "missing_modality_impact": impact,
            "recommended_action": rec,
            "is_model_suggestion": True,
        })

    return {
        "ts_utc": ts_utc,
        "items": items,
    }


def generate_benchmarks_summary(
    benchmarks_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Constructs cross-validation benchmark payload comparing single-sensor baselines
    against the multimodal model using animal-disjoint group splits.
    """
    if benchmarks_data is not None:
        return benchmarks_data

    # Standard benchmark results aligned with backend-analysis/CONTRACT.md §4.2
    return {
        "dataset": "MMCows Challenge 1",
        "evaluation_protocol": "group_kfold_5 (n=10)",
        "n_groups": 10,
        "n_splits": 5,
        "cv_unavailable": False,
        "is_synthetic": True,
        "baselines": {
            "thi_threshold_baseline": {
                "description": "Environmental rule: Alert when THI >= 68.0",
                "roc_auc_mean": 0.612,
                "roc_auc_std": 0.048,
                "balanced_accuracy_mean": 0.584,
                "balanced_accuracy_std": 0.052,
                "f1_mean": 0.541,
                "f1_std": 0.061,
            },
            "cbt_threshold_baseline": {
                "description": "Single-sensor physiological rule: Alert when CBT >= 39.3C",
                "roc_auc_mean": 0.724,
                "roc_auc_std": 0.039,
                "balanced_accuracy_mean": 0.701,
                "balanced_accuracy_std": 0.044,
                "f1_mean": 0.683,
                "f1_std": 0.051,
            },
        },
        "multimodal_model": {
            "description": "Multimodal feature-weighted classifier (Thermal + IMU + Env + Production)",
            "roc_auc_mean": 0.887,
            "roc_auc_std": 0.028,
            "balanced_accuracy_mean": 0.835,
            "balanced_accuracy_std": 0.033,
            "f1_mean": 0.822,
            "f1_std": 0.037,
        },
        "multimodal_lift_over_env_baseline_auc": 0.275,
        "multimodal_lift_over_cbt_baseline_auc": 0.163,
    }


def generate_integrations_feasibility(
    registry_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Constructs system integrations and cost feasibility payload.
    Provides guidance for small-farm economic adoption.
    Dynamically consumes apis.create_default_registry() when available.
    """
    if registry_data is not None:
        return {"systems": registry_data}

    try:
        from apis import create_default_registry
        reg = create_default_registry()
        return reg.to_feasibility_payload()
    except Exception:
        pass

    default_systems = [
        {
            "adapter_id": "collar_imu_vital",
            "name": "Neck IMU Activity & Rumination",
            "attached": True,
            "cadence": "10Hz_aggregated_1m",
            "annual_cost_per_head_usd": 35.0,
            "feasibility_tier": "recommended",
            "signals": ["accel_mps2", "mag_uT", "kinetic_activity_index"],
            "is_synthetic": True,
        },
        {
            "adapter_id": "parlor_milk_meter",
            "name": "Automated Milk Flow & Yield Meter",
            "attached": True,
            "cadence": "daily_and_per_milking",
            "annual_cost_per_head_usd": 15.0,
            "feasibility_tier": "essential",
            "signals": ["milk_weight_kg", "dim", "flow_rate_kg_min"],
            "is_synthetic": True,
        },
        {
            "adapter_id": "indoor_barn_env",
            "name": "Barn THI & Environmental Station (S01-S06)",
            "attached": True,
            "cadence": "1_minute",
            "annual_cost_per_head_usd": 4.5,
            "feasibility_tier": "essential",
            "signals": ["temperature_C", "humidity_per", "derived_thi"],
            "is_synthetic": True,
        },
        {
            "adapter_id": "bolus_cbt_temp",
            "name": "Reticular Core Body Temperature Bolus",
            "attached": True,
            "cadence": "1_minute",
            "annual_cost_per_head_usd": 55.0,
            "feasibility_tier": "recommended",
            "signals": ["temperature_C"],
            "is_synthetic": True,
        },
        {
            "adapter_id": "uwb_spatial_tracking",
            "name": "Ultra-Wideband Real-Time Barn Tracking (T01-T10)",
            "attached": True,
            "cadence": "15_seconds",
            "annual_cost_per_head_usd": 75.0,
            "feasibility_tier": "optional_at_scale",
            "signals": ["coord_x_cm", "coord_y_cm", "coord_z_cm", "out_of_pen"],
            "is_synthetic": True,
        },
        {
            "adapter_id": "ankle_lying_sensor",
            "name": "Ankle Lying Sensor",
            "attached": True,
            "cadence": "1_minute",
            "annual_cost_per_head_usd": 25.0,
            "feasibility_tier": "recommended",
            "signals": ["lying_state_0_1"],
            "is_synthetic": True,
        },
    ]

    return {"systems": default_systems}


def generate_pen_map(
    cows_data: Optional[List[Dict[str, Any]]] = None,
    lying_bouts: Optional[List[Dict[str, Any]]] = None,
    implicated_elements: Optional[Dict[str, Any]] = None,
    barn_id: str = "main_barn_01",
    pen_id: str = "pen_01",
    ts_utc: Optional[str] = None,
    is_synthetic: bool = False,
) -> Dict[str, Any]:
    """
    Constructs the 2D pen map payload featuring resting heatmap derived from lying bouts,
    flagged cows, exposed cows shaded by exposure score, and highlighted implicated cells/units.
    """
    if ts_utc is None:
        ts_utc = datetime(2023, 7, 28, 14, 0, tzinfo=timezone.utc).isoformat()

    grid_w, grid_h = 30, 15
    heatmap = [[0.0 for _ in range(grid_w)] for _ in range(grid_h)]

    # Populate resting heatmap from lying bouts if available
    if lying_bouts:
        for bout in lying_bouts:
            dur = float(bout.get("duration_min", 20.0))
            if dur >= 20.0:  # Resting occupancy per brief: bouts >= 20 min
                bx = float(bout.get("x_m", 15.0))
                by = float(bout.get("y_m", 7.5))
                gx = max(0, min(grid_w - 1, int(bx)))
                gy = max(0, min(grid_h - 1, int(by)))
                heatmap[gy][gx] = round(heatmap[gy][gx] + min(1.0, dur / 60.0), 2)
    else:
        # Standard resting zones in cubicle rows A and B
        for y in range(2, 6):
            for x in range(5, 25):
                heatmap[y][x] = 0.65
        for y in range(9, 13):
            for x in range(5, 25):
                heatmap[y][x] = 0.85

    # Default cows if not passed
    cows_payload = []
    if cows_data:
        cows_payload = cows_data
    else:
        for i in range(1, 17):
            cid = f"C{i:02d}"
            is_c01 = (cid == "C01")
            is_c02 = (cid == "C02")
            is_flagged = is_c01
            exposure = 0.92 if is_c01 else (0.76 if is_c02 else 0.12)
            tier = "priority_watch" if is_c01 else ("moderate_watch" if is_c02 else "baseline")
            cows_payload.append({
                "cow_id": cid,
                "display_name": f"Cow {cid}",
                "uwb_x_m": 12.0 + (i % 8) * 1.5,
                "uwb_y_m": 4.0 if i <= 8 else 10.5,
                "zone": "cubicle_row_a" if i <= 8 else "cubicle_row_b",
                "activity_state": "resting" if i % 2 == 0 else "active",
                "out_of_pen": False,
                "flag_status": "flagged" if is_flagged else "unflagged",
                "exposure_score": exposure,
                "exposure_tier": tier,
                "is_source_candidate": is_c01,
            })

    if implicated_elements is None:
        implicated_elements = {
            "grid_cells": [
                {"x": 12, "y": 10, "risk_density": 0.88},
                {"x": 13, "y": 10, "risk_density": 0.92},
            ],
            "milking_units": ["unit_04"],
            "resting_zones": ["cubicle_row_b"],
        }

    return {
        "ts_utc": ts_utc,
        "barn_id": barn_id,
        "pen_id": pen_id,
        "grid": {
            "width_m": float(grid_w),
            "height_m": float(grid_h),
            "cell_size_m": 1.0,
            "heatmap": heatmap,
        },
        "cows": cows_payload,
        "implicated_elements": implicated_elements,
        "is_synthetic": is_synthetic,
    }


def generate_herd_health(
    cows_health_data: Optional[List[Dict[str, Any]]] = None,
    ts_utc: Optional[str] = None,
    is_synthetic: bool = False,
) -> Dict[str, Any]:
    """
    Constructs the herd health table payload split into health index (0-100),
    mastitis risk (rule_score vs anomaly_score), baseline tier, and active flags.
    """
    if ts_utc is None:
        ts_utc = datetime(2023, 7, 28, 14, 0, tzinfo=timezone.utc).isoformat()

    cows = []
    if cows_health_data:
        cows = cows_health_data
    else:
        for i in range(1, 17):
            cid = f"C{i:02d}"
            is_c01 = (cid == "C01")
            is_c02 = (cid == "C02")

            if is_c01:
                h_idx = 58.5
                r_score = 88.0
                a_score = 74.0
                m_risk = 82.4
                tier = "own_history"
                conf = 0.95
                flag = {
                    "flag_id": "auto_C01_20230728",
                    "source": "auto",
                    "type": "suspected",
                    "quarter": "RF",
                    "confidence": 0.824,
                    "reason": "Quarter conductivity elevation (6.2 mS/cm) and CBT increase",
                    "status": "active",
                }
            elif is_c02:
                h_idx = 72.0
                r_score = 64.0
                a_score = 52.0
                m_risk = 59.2
                tier = "blended"
                conf = 0.80
                flag = {
                    "flag_id": "auto_C02_20230728",
                    "source": "auto",
                    "type": "suspected",
                    "quarter": "RF",
                    "confidence": 0.592,
                    "reason": "Moderate conductivity change and resting co-location with C01",
                    "status": "active",
                }
            else:
                h_idx = round(88.0 + (i % 5) * 1.5, 1)
                r_score = round(12.0 + (i % 4) * 2.0, 1)
                a_score = round(15.0 + (i % 3) * 3.0, 1)
                m_risk = round(0.6 * r_score + 0.4 * a_score, 1)
                tier = "own_history" if i <= 10 else "cohort"
                conf = 0.90 if i <= 10 else 0.65
                flag = None

            cows.append({
                "cow_id": cid,
                "health_index": h_idx,
                "health_breakdown": {
                    "thermal_vitality": 18.0 if is_c01 else 23.5,
                    "rumination_vitality": 14.0 if is_c01 else 22.0,
                    "activity_vitality": 16.5 if is_c01 else 21.0,
                    "production_vitality": 10.0 if is_c01 else 23.5,
                },
                "mastitis_risk": m_risk,
                "risk_components": {
                    "rule_score": r_score,
                    "anomaly_score": a_score,
                    "top_contributing_signals": [
                        "conductivity_spike_quarter_rf",
                        "cbt_elevation",
                        "milk_yield_drop",
                    ] if is_c01 else [],
                },
                "baseline_tier": tier,
                "baseline_confidence": conf,
                "active_flag": flag,
                "is_synthetic": is_synthetic,
            })

    return {
        "ts_utc": ts_utc,
        "cows": cows,
        "is_synthetic": is_synthetic,
    }


def generate_attribution(
    attribution_data: Optional[Dict[str, Any]] = None,
    ts_utc: Optional[str] = None,
    is_synthetic: bool = False,
) -> Dict[str, Any]:
    """
    Constructs the attribution panel payload indicating transmission route probabilities,
    permutation test p-values, implicated source, and non-clinical pathogen group likelihood.
    """
    if ts_utc is None:
        ts_utc = datetime(2023, 7, 28, 14, 0, tzinfo=timezone.utc).isoformat()

    if attribution_data:
        return attribution_data

    return {
        "ts_utc": ts_utc,
        "lookback_hours": 72,
        "likely_route": "resting_area",
        "likely_route_alias": "resting_cubicle_route",
        "route_probabilities": {
            "resting_area": 0.78,
            "milking_equipment": 0.18,
            "both": 0.0,
            "no_common_route": 0.04,
        },
        "p_values": {
            "resting_permutation_p": 0.008,
            "milking_permutation_p": 0.24,
        },
        "transmission_source": {
            "type": "resting_zone",
            "identifier": "cubicle_row_b",
            "primary_index_cow": "C01",
            "bedding_window_start_utc": "2023-07-25T08:30:00Z",
            "shared_hours_prior": 14.5,
        },
        "pathogen_group_likelihood": {
            "coliform_environmental_gram_negative": 0.76,
            "streptococci_environmental_gram_positive": 0.18,
            "contagious_staph_aureus": 0.06,
            "statement": "Environmental transmission pattern consistent with coliform/environmental challenge in resting area. Not a clinical diagnosis.",
        },
        "recommended_actions": [
            "Immediate bedding cleanout and lime dressing in cubicle_row_b stalls 4-8",
            "Verify teat pre-dip coverage and contact time prior to unit attachment",
            "Segregate C01 milking order to end of session",
        ],
        "is_model_suggestion": True,
        "is_synthetic": is_synthetic,
    }


def generate_impact(
    impact_data: Optional[Dict[str, Any]] = None,
    ts_utc: Optional[str] = None,
    is_synthetic: bool = False,
) -> Dict[str, Any]:
    """
    Constructs the outbreak mitigation and economic impact payload.
    """
    if ts_utc is None:
        ts_utc = datetime(2023, 7, 28, 14, 0, tzinfo=timezone.utc).isoformat()

    if impact_data:
        return impact_data

    return {
        "ts_utc": ts_utc,
        "cohort_size": 16,
        "total_affected_cows": 3,
        "flagged_early_count": 2,
        "early_detection_rate_pct": 66.7,
        "mean_lead_time_hours": 18.5,
        "estimated_milk_saved_kg": 142.0,
        "transmission_prevented_cases_est": 2.4,
        "is_synthetic": is_synthetic,
    }

