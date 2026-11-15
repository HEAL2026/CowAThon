"""S11: Outbreak backtrace investigation & permutation-test route attribution.

Entry point: backtrace(flags, lookback_hours=72) -> BacktraceResult

Performs non-diagnostic epidemiological route attribution:
- Formulates resting-route co-occupancy and milking-equipment sequence statistics.
- Executes permutation testing (shuffling herd assignments B times) to compute empirical p-values.
- Attributes transmission route (resting_environment, milking_equipment, or sporadic_inconclusive).
- Estimates pathogen group likelihood distribution (contagious vs environmental) strictly as likelihood, never clinical diagnosis.
- Identifies implicated resources (cubicle cells, milking units) and surfaces exposed herd members.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Sequence
import numpy as np
import pandas as pd

from .exposure_resting import calculate_resting_exposure, get_grid_cell_id
from .exposure_milking import calculate_milking_exposure
from .exposure_combined import calculate_combined_exposure


# Canonical vocabulary aligned with cleaning/synth.py:make_cases true_route
CANONICAL_TO_LEGACY_ROUTES = {
    "resting_area": "resting_environment",
    "milking_equipment": "milking_equipment",
    "both": "mixed_transmission",
    "no_common_route": "sporadic_inconclusive",
}

LEGACY_TO_CANONICAL_ROUTES = {
    "resting_environment": "resting_area",
    "milking_equipment": "milking_equipment",
    "mixed_transmission": "both",
    "sporadic_inconclusive": "no_common_route",
}


def run_permutation_attribution_test(
    lying_bouts_df: pd.DataFrame,
    milking_log_df: pd.DataFrame,
    flagged_cows: Sequence[str] | set[str],
    bedding_df: pd.DataFrame | None = None,
    sanitation_df: pd.DataFrame | None = None,
    lookback_hours: int = 72,
    n_permutations: int = 200,
    seed: int = 42,
    reference_time: pd.Timestamp | str | None = None,
) -> dict[str, Any]:
    """Execute permutation test to attribute transmission route and compute empirical p-values."""
    flag_set = set(flagged_cows)
    rng = np.random.default_rng(seed)
    ref_t = pd.to_datetime(reference_time, utc=True) if reference_time is not None else None

    # 1. Observed test statistics
    res_obs = calculate_resting_exposure(
        lying_bouts_df=lying_bouts_df,
        bedding_df=bedding_df,
        flagged_cows=flag_set,
        lookback_hours=lookback_hours,
        reference_time=ref_t,
    )
    milk_obs = calculate_milking_exposure(
        milking_log_df=milking_log_df,
        sanitation_df=sanitation_df,
        flagged_cows=flag_set,
        lookback_hours=lookback_hours,
        reference_time=ref_t,
    )

    def compute_case_contact_score(contact_events: list[dict[str, Any]], cases: set[str]) -> float:
        return float(sum(
            e.get("exposure_score", 1.0)
            for e in contact_events
            if e.get("source_cow") in cases and e.get("exposed_cow") in cases
        ))

    t_resting_obs = compute_case_contact_score(res_obs.get("contact_events", []), flag_set)
    t_milking_obs = compute_case_contact_score(milk_obs.get("contact_events", []), flag_set)

    all_cows = sorted(list(
        set(lying_bouts_df["cow_id"].unique() if len(lying_bouts_df) else [])
        | set(milking_log_df["cow_id"].unique() if "cow_id" in milking_log_df else [])
        | flag_set
    ))

    if len(flag_set) == 0 or len(all_cows) < 2:
        return {
            "p_value_resting": 1.0,
            "p_value_milking": 1.0,
            "t_resting_obs": t_resting_obs,
            "t_milking_obs": t_milking_obs,
            "likely_route": "no_common_route",
            "likely_route_alias": "sporadic_inconclusive",
            "pathogen_group_likelihood": {
                "contagious_milking_associated": 0.50,
                "environmental_bedding_associated": 0.50,
                "note": "Zero or insufficient flags to perform permutation testing",
            },
        }

    k_flags = len(flag_set)
    b_resting_greater = 0
    b_milking_greater = 0

    # 2. Permutation loop
    for _ in range(n_permutations):
        shuffled_flags = set(rng.choice(all_cows, size=min(k_flags, len(all_cows)), replace=False))

        # Permuted resting statistic
        if len(lying_bouts_df) > 0 and t_resting_obs > 0:
            res_perm = calculate_resting_exposure(
                lying_bouts_df=lying_bouts_df,
                bedding_df=bedding_df,
                flagged_cows=shuffled_flags,
                lookback_hours=lookback_hours,
                reference_time=ref_t,
            )
            t_perm_rest = compute_case_contact_score(res_perm.get("contact_events", []), shuffled_flags)
            if t_perm_rest >= t_resting_obs:
                b_resting_greater += 1
        elif t_resting_obs == 0:
            b_resting_greater += 1

        # Permuted milking statistic
        if len(milking_log_df) > 0 and t_milking_obs > 0:
            milk_perm = calculate_milking_exposure(
                milking_log_df=milking_log_df,
                sanitation_df=sanitation_df,
                flagged_cows=shuffled_flags,
                lookback_hours=lookback_hours,
                reference_time=ref_t,
            )
            t_perm_milk = compute_case_contact_score(milk_perm.get("contact_events", []), shuffled_flags)
            if t_perm_milk >= t_milking_obs:
                b_milking_greater += 1
        elif t_milking_obs == 0:
            b_milking_greater += 1

    p_resting = round((1.0 + b_resting_greater) / (n_permutations + 1.0), 3)
    p_milking = round((1.0 + b_milking_greater) / (n_permutations + 1.0), 3)

    # 3. Decision attribution
    alpha = 0.05
    is_rest_sig = (p_resting < alpha) and (t_resting_obs > 0)
    is_milk_sig = (p_milking < alpha) and (t_milking_obs > 0)

    if is_rest_sig and not is_milk_sig:
        likely_route = "resting_area"
        likely_route_alias = "resting_environment"
        pathogen_dist = {
            "environmental_bedding_associated": 0.85,
            "contagious_milking_associated": 0.15,
            "note": "Significant spatial cubicle co-occupancy clustering; typical of environmental pathogens (e.g. E. coli, Strep uberis)",
        }
    elif is_milk_sig and not is_rest_sig:
        likely_route = "milking_equipment"
        likely_route_alias = "milking_equipment"
        pathogen_dist = {
            "contagious_milking_associated": 0.85,
            "environmental_bedding_associated": 0.15,
            "note": "Significant un-sanitized serial milking stall contacts; typical of contagious pathogens (e.g. Staph aureus)",
        }
    elif is_rest_sig and is_milk_sig:
        likely_route = "both"
        likely_route_alias = "mixed_transmission"
        pathogen_dist = {
            "environmental_bedding_associated": 0.50,
            "contagious_milking_associated": 0.50,
            "note": "Both resting and milking routes exhibit statistically significant contact clustering",
        }
    else:
        likely_route = "no_common_route"
        likely_route_alias = "sporadic_inconclusive"
        pathogen_dist = {
            "environmental_bedding_associated": 0.50,
            "contagious_milking_associated": 0.50,
            "note": "No statistically significant transmission route clustering; indicates individual animal susceptibility",
        }

    return {
        "p_value_resting": p_resting,
        "p_value_milking": p_milking,
        "t_resting_obs": t_resting_obs,
        "t_milking_obs": t_milking_obs,
        "likely_route": likely_route,
        "likely_route_alias": likely_route_alias,
        "pathogen_group_likelihood": pathogen_dist,
    }


def generate_synthetic_backtrace_fixtures(
    scenario: str = "resting",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate deterministic synthetic fixtures for resting, milking, or sporadic transmission."""
    base_t = pd.Timestamp("2023-07-25 08:00:00", tz="UTC")

    # Bedding changes every 4 days
    bedding_df = pd.DataFrame([{
        "zone_id": "cubicle_row_a",
        "changed_at": base_t - pd.Timedelta(days=2),
        "is_synthetic": True,
    }])

    # Parlor sanitation every 12 hours
    san_records = [{
        "unit_id": "STALL-01",
        "sanitized_at": base_t - pd.Timedelta(hours=14),
        "is_synthetic": True,
    }]
    if scenario == "milking":
        for u in ["STALL-02", "STALL-03", "STALL-04"]:
            for h in [10, 8, 6]:
                san_records.append({
                    "unit_id": u,
                    "sanitized_at": base_t - pd.Timedelta(hours=h, minutes=30),
                    "is_synthetic": True,
                })
    sanitation_df = pd.DataFrame(san_records)

    all_cow_ids = [f"C{i:02d}" for i in range(1, 11)]

    bouts_data = []
    milking_data = []

    if scenario == "resting":
        # Resting transmission: C02 sheds in cell (5.0, 3.0), C01 subsequently rests in that exact cell
        # Other cows (C03..C10) rest in distinct separate cells across the barn
        bouts_data.append({
            "cow_id": "C02",
            "start_utc": base_t - pd.Timedelta(hours=20),
            "end_utc": base_t - pd.Timedelta(hours=18),
            "duration_min": 120,
            "x_m": 5.1,
            "y_m": 3.1,
            "zone_id": "cubicle_row_a",
        })
        bouts_data.append({
            "cow_id": "C01",
            "start_utc": base_t - pd.Timedelta(hours=14),
            "end_utc": base_t - pd.Timedelta(hours=12),
            "duration_min": 120,
            "x_m": 5.2,
            "y_m": 3.0,
            "zone_id": "cubicle_row_a",
        })
        # Disperse remaining cows C03..C10 into distinct cubicles
        for i, cid in enumerate(all_cow_ids[2:], start=3):
            bouts_data.append({
                "cow_id": cid,
                "start_utc": base_t - pd.Timedelta(hours=16),
                "end_utc": base_t - pd.Timedelta(hours=14),
                "duration_min": 120,
                "x_m": float(i * 2.5),
                "y_m": float(i * 1.5),
                "zone_id": "cubicle_row_b",
            })

        # Disperse milking visits across 4 units (no sequential contacts for C01/C02)
        for i, cid in enumerate(all_cow_ids):
            unit = f"STALL-{(i % 4) + 1:02d}"
            milking_data.append({
                "cow_id": cid,
                "milking_time": base_t - pd.Timedelta(hours=8, minutes=i * 10),
                "unit_id": unit,
                "is_synthetic": True,
            })

    elif scenario == "milking":
        # Milking transmission: C02 milks at STALL-01, C01 milks immediately after on STALL-01 without sanitation
        # All other cows milk on separate units or long after
        milking_data.append({
            "cow_id": "C02",
            "milking_time": base_t - pd.Timedelta(hours=10),
            "unit_id": "STALL-01",
            "is_synthetic": True,
        })
        milking_data.append({
            "cow_id": "C01",
            "milking_time": base_t - pd.Timedelta(hours=9, minutes=45),
            "unit_id": "STALL-01",
            "is_synthetic": True,
        })
        for i, cid in enumerate(all_cow_ids[2:], start=3):
            unit = f"STALL-{(i % 3) + 2:02d}"  # STALL-02, 03, 04
            milking_data.append({
                "cow_id": cid,
                "milking_time": base_t - pd.Timedelta(hours=10, minutes=i * 5),
                "unit_id": unit,
                "is_synthetic": True,
            })

        # Disperse resting locations so C01 and C02 do not share cubicles
        for i, cid in enumerate(all_cow_ids):
            bouts_data.append({
                "cow_id": cid,
                "start_utc": base_t - pd.Timedelta(hours=18),
                "end_utc": base_t - pd.Timedelta(hours=16),
                "duration_min": 120,
                "x_m": float(i * 2.5),
                "y_m": float(i * 1.5),
                "zone_id": "cubicle_row_a",
            })

    else:
        # Sporadic: completely un-correlated
        for i, cid in enumerate(all_cow_ids):
            bouts_data.append({
                "cow_id": cid,
                "start_utc": base_t - pd.Timedelta(hours=18),
                "end_utc": base_t - pd.Timedelta(hours=16),
                "duration_min": 120,
                "x_m": float(i * 2.5),
                "y_m": float(i * 1.5),
                "zone_id": "cubicle_row_a",
            })
            milking_data.append({
                "cow_id": cid,
                "milking_time": base_t - pd.Timedelta(hours=8, minutes=i * 10),
                "unit_id": f"STALL-{(i % 4) + 1:02d}",
                "is_synthetic": True,
            })

    return pd.DataFrame(bouts_data), pd.DataFrame(milking_data), bedding_df, sanitation_df


def backtrace(
    flags: list[dict[str, Any]] | None = None,
    lookback_hours: int = 72,
    lying_bouts_df: pd.DataFrame | None = None,
    milking_log_df: pd.DataFrame | None = None,
    bedding_df: pd.DataFrame | None = None,
    sanitation_df: pd.DataFrame | None = None,
    n_permutations: int = 200,
    seed: int = 42,
    reference_time: pd.Timestamp | str | None = None,
    is_synthetic: bool | None = None,
) -> dict[str, Any]:
    """Execute outbreak backtrace investigation across resting and milking transmission routes.

    Args:
        flags: List of flag dictionaries (each containing 'cow_id' or 'animal_id').
        lookback_hours: Investigation lookback window in hours (default: 72).
        lying_bouts_df: Optional DataFrame of lying bouts.
        milking_log_df: Optional DataFrame of milking visit records.
        bedding_df: Optional DataFrame of bedding changes.
        sanitation_df: Optional DataFrame of parlor unit sanitations.
        n_permutations: Number of random permutations for empirical p-values (default: 200).
        seed: Random seed for permutation reproducibility.
        reference_time: Optional explicit timestamp anchoring the investigation window.
                        If None, inferred from flag timestamps or latest events of flagged cows.

    Returns:
        BacktraceResult dictionary adhering to data contracts.
    """
    now_utc = datetime.now(timezone.utc)
    inv_id = f"trace_{now_utc.strftime('%Y%m%d_%H%M%S')}"

    # Extract flagged cows
    flagged_ids = []
    if flags:
        for f in flags:
            cid = f.get("cow_id") or f.get("animal_id")
            if cid and str(cid) not in flagged_ids:
                flagged_ids.append(str(cid))

    if is_synthetic is None:
        is_synthetic = False
    # If fixtures missing, generate resting scenario fallback
    if lying_bouts_df is None or len(lying_bouts_df) == 0:
        bouts_df, milk_df, bed_df, san_df = generate_synthetic_backtrace_fixtures(scenario="resting")
        lying_bouts_df = bouts_df
        if milking_log_df is None or len(milking_log_df) == 0:
            milking_log_df = milk_df
        if bedding_df is None or len(bedding_df) == 0:
            bedding_df = bed_df
        if sanitation_df is None or len(sanitation_df) == 0:
            sanitation_df = san_df
        is_synthetic = True
        if not flagged_ids:
            flagged_ids = ["C02"]

    # Resolve investigation reference time
    ref_t = pd.to_datetime(reference_time, utc=True) if reference_time is not None else None

    # Infer from flag timestamps if available
    if ref_t is None and flags:
        flag_ts = []
        for f in flags:
            for k in ("dx_utc", "onset_utc", "timestamp", "ts_utc", "created_at"):
                v = f.get(k)
                if v is not None:
                    try:
                        flag_ts.append(pd.to_datetime(v, utc=True))
                    except Exception:
                        pass
        if flag_ts:
            ref_t = max(flag_ts)

    # If still None, default to latest timestamp in available tables
    if ref_t is None:
        table_ts = []
        if lying_bouts_df is not None and len(lying_bouts_df) > 0:
            t_col = "end_utc" if "end_utc" in lying_bouts_df.columns else ("start_utc" if "start_utc" in lying_bouts_df.columns else None)
            if t_col and pd.notna(lying_bouts_df[t_col]).any():
                table_ts.append(pd.to_datetime(lying_bouts_df[t_col], utc=True).max())
        if milking_log_df is not None and len(milking_log_df) > 0:
            t_col = "milking_time" if "milking_time" in milking_log_df.columns else ("event_datetime" if "event_datetime" in milking_log_df.columns else None)
            if t_col and pd.notna(milking_log_df[t_col]).any():
                table_ts.append(pd.to_datetime(milking_log_df[t_col], utc=True).max())
        if table_ts:
            ref_t = max(table_ts)

    # Execute S8 & S9 exposure analyses
    res_resting = calculate_resting_exposure(
        lying_bouts_df=lying_bouts_df,
        bedding_df=bedding_df,
        flagged_cows=flagged_ids,
        lookback_hours=lookback_hours,
        reference_time=ref_t,
    )
    res_milking = calculate_milking_exposure(
        milking_log_df=milking_log_df if milking_log_df is not None else pd.DataFrame(),
        sanitation_df=sanitation_df,
        flagged_cows=flagged_ids,
        lookback_hours=lookback_hours,
        reference_time=ref_t,
    )

    # Execute S10 combined exposure
    res_comb = calculate_combined_exposure(
        resting_exposure=res_resting["cow_exposure"],
        milking_exposure=res_milking["cow_exposure"],
        flagged_cows=flagged_ids,
    )

    # Execute S11 permutation attribution test
    perm_res = run_permutation_attribution_test(
        lying_bouts_df=lying_bouts_df,
        milking_log_df=milking_log_df if milking_log_df is not None else pd.DataFrame(),
        flagged_cows=flagged_ids,
        bedding_df=bedding_df,
        sanitation_df=sanitation_df,
        lookback_hours=lookback_hours,
        n_permutations=n_permutations,
        seed=seed,
        reference_time=ref_t,
    )

    # Synthesize implicated units/cells and real 1.5m resting circles
    implicated = []
    implicated_resting_areas = res_resting.get("implicated_resting_areas", [])
    if perm_res["likely_route"] == "resting_area" and len(implicated_resting_areas) > 1:
        primary = implicated_resting_areas[0]
        source_areas = [
            area for area in implicated_resting_areas
            if area.get("target_cow_id") in flagged_ids
        ]
        if source_areas:
            primary["center_x_m"] = round(float(np.median([a["center_x_m"] for a in source_areas])), 2)
            primary["center_y_m"] = round(float(np.median([a["center_y_m"] for a in source_areas])), 2)
    if perm_res["likely_route"] in ("resting_area", "resting_environment"):
        for c in res_resting["implicated_cells"]:
            implicated.append(c["cell_id"])
        if not res_resting["implicated_cells"]:
            implicated.extend(
                get_grid_cell_id(area["center_x_m"], area["center_y_m"])
                for area in implicated_resting_areas
            )
    elif perm_res["likely_route"] == "milking_equipment":
        for u in res_milking["implicated_units"]:
            implicated.append(u["unit_id"])
    else:
        for area in res_resting.get("implicated_resting_areas", [])[:1]:
            implicated.append(area["area_id"])
        for u in res_milking["implicated_units"][:1]:
            implicated.append(u["unit_id"])

    # Determine primary resource label (1.5m spatial circle for resting route)
    if perm_res["likely_route"] in ("resting_area", "resting_environment") and implicated_resting_areas:
        primary_resource_label = f"Resting Circle (x={implicated_resting_areas[0]['center_x_m']}m, y={implicated_resting_areas[0]['center_y_m']}m, r=1.5m)"
    else:
        primary_resource_label = implicated[0] if implicated else None

    # Action recommendations
    if perm_res["likely_route"] in ("resting_area", "resting_environment"):
        actions = [
            "Deep clean and apply lime/disinfectant bedding powder to implicated 1.5m resting circles; replace organic bedding",
            "Verify stall curb cleanliness and ensure proper bedding drainage",
            "Inspect resting area ventilation and stall drying fans",
        ]
    elif perm_res["likely_route"] == "milking_equipment":
        actions = [
            "Inspect teat cup liner condition and vacuum stability on implicated milking units",
            "Enforce automatic cluster backflush / hot water acid disinfection between milkings",
            "Enforce strict individual teat drying towels and pre-milking teat dip contact time",
        ]
    else:
        actions = [
            "Maintain standard parlor hygiene and routine stall cleanliness",
            "Monitor individual cow somatic cell counts and core temperatures closely",
        ]

    return {
        "investigation_id": inv_id,
        "generated_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference_time_utc": ref_t.strftime("%Y-%m-%dT%H:%M:%SZ") if ref_t is not None else None,
        "lookback_hours": lookback_hours,
        "flagged_cows": flagged_ids,
        "likely_route": perm_res["likely_route"],
        "likely_route_alias": perm_res.get("likely_route_alias"),
        "route_p_values": {
            "resting_p_value": perm_res["p_value_resting"],
            "milking_p_value": perm_res["p_value_milking"],
        },
        "p_values": {
            "resting_route": perm_res["p_value_resting"],
            "milking_equipment": perm_res["p_value_milking"],
        },
        "pathogen_group_likelihood": perm_res["pathogen_group_likelihood"],
        "implicated_units_or_cells": implicated,
        "implicated_resting_areas": implicated_resting_areas,
        "implicated_circles": implicated_resting_areas,
        "implicated_resources": {
            "primary_unit_or_cell": primary_resource_label,
            "all": implicated,
            "resting_areas": implicated_resting_areas,
        },
        "exposed_cows": res_comb["exposed_cows"],
        "high_risk_contacts": [{"cow_id": c["cow_id"], **c} for c in res_comb["exposed_cows"]],
        "recommended_actions": actions,
        "is_model_suggestion": True,
        "is_synthetic": is_synthetic,
    }
