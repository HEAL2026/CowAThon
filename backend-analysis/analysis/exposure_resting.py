"""S8: Resting-route exposure tracing.

Tracks environmental pathogen transmission via contaminated bedding in cubicles/cells:
- Identifies resting occupancy (lying_bouts >= 20 min in-pen).
- Discretizes barn into spatial cubicle grid cells (default 2.0m x 2.0m).
- Bounds transmission windows by bedding replacement events (changed_at per zone/pen).
- Computes resting exposure scores for herd members and flags implicated stalls/cells.
"""

from __future__ import annotations
from typing import Any, Sequence
import numpy as np
import pandas as pd


def get_grid_cell_id(x: float, y: float, cell_size_m: float = 2.0, zone_id: str | None = None) -> str:
    """Discretize continuous UWB coordinates into a stall/cubicle grid cell."""
    ix = int(np.floor(float(x) / cell_size_m))
    iy = int(np.floor(float(y) / cell_size_m))
    prefix = f"{zone_id}:" if zone_id else ""
    return f"{prefix}cell_X{ix}_Y{iy}"


def calculate_resting_exposure(
    lying_bouts_df: pd.DataFrame,
    bedding_df: pd.DataFrame | None = None,
    flagged_cows: Sequence[str] | set[str] | None = None,
    lookback_hours: int = 72,
    resting_min_duration_min: int = 20,
    cell_size_m: float = 2.0,
    reference_time: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Calculate resting-route environmental exposure and identify contaminated cubicles.

    Args:
        lying_bouts_df: DataFrame with cow_id, start_utc, end_utc, duration_min, x_m, y_m.
        bedding_df: Optional DataFrame with zone_id/pen_id and changed_at/event_datetime.
        flagged_cows: Cow IDs exhibiting acute mastitis / shedding.
        lookback_hours: Tracing investigation window in hours (default: 72).
        resting_min_duration_min: Minimum bout length for resting occupancy (default: 20 min).
        cell_size_m: Spatial grid resolution in meters (default: 2.0m).
        reference_time: Reference end time for lookback (default: latest bout timestamp).

    Returns:
        Dictionary with cow_exposure (dict), implicated_cells (list), and contact_events (list).
    """
    flag_set = set(flagged_cows) if flagged_cows else set()
    if len(lying_bouts_df) == 0:
        return {
            "cow_exposure": {},
            "implicated_cells": [],
            "contact_events": [],
            "co_occupancy_pairs_count": 0,
        }

    df_bouts = lying_bouts_df.copy()
    df_bouts["start_utc"] = pd.to_datetime(df_bouts["start_utc"], utc=True)
    df_bouts["end_utc"] = pd.to_datetime(df_bouts["end_utc"], utc=True)

    ref_t = reference_time or df_bouts["end_utc"].max()
    window_start = ref_t - pd.Timedelta(hours=lookback_hours)

    # Filter to lookback window and resting bouts >= threshold
    mask_valid = (
        (df_bouts["end_utc"] >= window_start)
        & (df_bouts["start_utc"] <= ref_t)
        & (df_bouts["duration_min"] >= resting_min_duration_min)
        & df_bouts["x_m"].notna()
        & df_bouts["y_m"].notna()
    )
    bouts = df_bouts[mask_valid].sort_values("start_utc").copy()

    # Assign grid cell to each bout
    bouts["cell_id"] = [
        get_grid_cell_id(row["x_m"], row["y_m"], cell_size_m=cell_size_m, zone_id=row.get("zone_id"))
        for _, row in bouts.iterrows()
    ]

    # Parse bedding change events
    bedding_changes: list[pd.Timestamp] = []
    if bedding_df is not None and len(bedding_df) > 0:
        col_t = "changed_at" if "changed_at" in bedding_df.columns else "event_datetime"
        if col_t in bedding_df.columns:
            bedding_changes = sorted(pd.to_datetime(bedding_df[col_t].dropna(), utc=True).tolist())

    def get_last_bedding_change(t: pd.Timestamp) -> pd.Timestamp:
        past_changes = [bc for bc in bedding_changes if bc <= t]
        return max(past_changes) if past_changes else pd.Timestamp.min.tz_localize("UTC")

    # Track cell contamination and exposure
    # cell_id -> list of shedding events: (cow_id, end_utc, duration_min)
    cell_shedding: dict[str, list[dict[str, Any]]] = {}
    contact_events: list[dict[str, Any]] = []
    cow_exposure_raw: dict[str, float] = {str(cid): 0.0 for cid in df_bouts["cow_id"].unique()}
    cell_exposure_load: dict[str, float] = {}

    for _, bout in bouts.iterrows():
        cid = str(bout["cow_id"])
        cell = bout["cell_id"]
        t_start = bout["start_utc"]
        t_end = bout["end_utc"]
        dur = float(bout["duration_min"])
        last_change = get_last_bedding_change(t_start)

        if cell not in cell_shedding:
            cell_shedding[cell] = []
            cell_exposure_load[cell] = 0.0

        # Check active contamination from earlier shedders in this cell
        if cell in cell_shedding:
            for shed in cell_shedding[cell]:
                if shed["cow_id"] != cid:
                    shed_t = shed["deposited_at"]
                    # Must be after shedding and within the same bedding window
                    if shed_t < t_start and last_change <= shed_t:
                        hours_diff = (t_start - shed_t).total_seconds() / 3600.0
                        decay = np.exp(-hours_diff / 24.0)  # 24-hour half-life persistence in organic bedding
                        exposure_inc = float(min(1.0, (dur / 60.0) * decay * (shed["duration_min"] / 60.0)))

                        if exposure_inc > 0.01:
                            cow_exposure_raw[cid] = cow_exposure_raw.get(cid, 0.0) + exposure_inc
                            contact_events.append({
                                "source_cow": shed["cow_id"],
                                "exposed_cow": cid,
                                "cell_id": cell,
                                "source_time": shed_t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "exposed_time": t_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "hours_since_shedding": round(hours_diff, 1),
                                "exposure_score": round(exposure_inc, 3),
                            })

        if cid in flag_set:
            # Shedding cow deposits pathogen in bedding for subsequent visits
            cell_shedding[cell].append({
                "cow_id": cid,
                "deposited_at": t_end,
                "duration_min": dur,
                "bedding_change_cutoff": last_change,
            })
            cell_exposure_load[cell] += dur

    # Normalize cow exposure scores to [0.0, 1.0]
    cow_exposure: dict[str, float] = {}
    for cid, raw_score in cow_exposure_raw.items():
        if cid in flag_set:
            cow_exposure[cid] = 1.0
        else:
            cow_exposure[cid] = float(round(np.clip(1.0 - np.exp(-raw_score), 0.0, 1.0), 3))

    # Identify implicated cells ranked by transmission load
    implicated_cells = []
    for cell, load in sorted(cell_exposure_load.items(), key=lambda x: x[1], reverse=True):
        if load > 0.0:
            matching_bouts = bouts[bouts["cell_id"] == cell]
            implicated_cells.append({
                "cell_id": cell,
                "x_m": round(float(matching_bouts["x_m"].median()), 2),
                "y_m": round(float(matching_bouts["y_m"].median()), 2),
                "cumulative_shed_duration_min": round(load, 1),
                "n_contacts": len([e for e in contact_events if e["cell_id"] == cell]),
            })

    return {
        "cow_exposure": cow_exposure,
        "implicated_cells": implicated_cells,
        "contact_events": contact_events,
        "co_occupancy_pairs_count": len(contact_events),
    }
