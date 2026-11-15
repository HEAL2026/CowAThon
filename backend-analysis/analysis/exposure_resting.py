"""S8: Resting-route exposure tracing.

Tracks environmental pathogen transmission via contaminated bedding in cubicles/cells:
- Identifies resting occupancy (lying_bouts >= 20 min in-pen).
- Uses the flagged cow's real resting coordinates and a 1.5m radius area.
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
    radius_m: float = 1.5,
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
        Dictionary with cow_exposure (dict), implicated_resting_areas (list),
        and contact_events (list). `implicated_cells` remains as a deprecated
        compatibility summary and is not used for attribution.
    """
    flag_set = {c if isinstance(c, str) else str(c.get("cow_id", "")) for c in flagged_cows} if flagged_cows else set()
    if radius_m <= 0:
        raise ValueError(f"radius_m must be positive, got {radius_m}")
    if len(lying_bouts_df) == 0:
        return {
            "cow_exposure": {},
            "implicated_cells": [],
            "implicated_resting_areas": [],
            "implicated_circles": [],
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

    # Parse bedding change events
    bedding_changes: list[pd.Timestamp] = []
    if bedding_df is not None and len(bedding_df) > 0:
        col_t = "changed_at" if "changed_at" in bedding_df.columns else "event_datetime"
        if col_t in bedding_df.columns:
            bedding_changes = sorted(pd.to_datetime(bedding_df[col_t].dropna(), utc=True).tolist())

    def get_last_bedding_change(t: pd.Timestamp) -> pd.Timestamp:
        past_changes = [bc for bc in bedding_changes if bc <= t]
        return max(past_changes) if past_changes else pd.Timestamp.min.tz_localize("UTC")

    def get_next_bedding_change(t: pd.Timestamp) -> pd.Timestamp:
        future_changes = [bc for bc in bedding_changes if bc > t]
        return min(future_changes) if future_changes else (ref_t + pd.Timedelta(hours=2))

    # Track cell contamination and exposure
    # cell_id -> list of shedding events: (cow_id, end_utc, duration_min)
    cell_shedding: dict[str, list[dict[str, Any]]] = {}
    contact_events: list[dict[str, Any]] = []
    cow_exposure_raw: dict[str, float] = {str(cid): 0.0 for cid in df_bouts["cow_id"].unique()}
    area_exposure: dict[str, dict[str, Any]] = {}

    for _, bout in bouts.iterrows():
        cid = str(bout["cow_id"])
        t_start = bout["start_utc"]
        t_end = bout["end_utc"]
        dur = float(bout["duration_min"])
        last_change = get_last_bedding_change(t_start)
        # A later cow is exposed only if its resting center falls inside the
        # flagged cow's real-coordinate circle and bedding has not changed.
        for area in area_exposure.values():
            if t_start <= area["source_end"] or last_change > area["source_end"]:
                continue
            distance_m = float(np.hypot(
                float(bout["x_m"]) - area["center_x_m"],
                float(bout["y_m"]) - area["center_y_m"],
            ))
            if distance_m > area["radius_m"]:
                continue
            hours_diff = (t_start - area["source_end"]).total_seconds() / 3600.0
            decay = np.exp(-hours_diff / 24.0)
            exposure_inc = float(min(1.0, (dur / 60.0) * decay * (area["cumulative_duration_min"] / 60.0)))
            if exposure_inc <= 0.01:
                continue
            cow_exposure_raw[cid] = cow_exposure_raw.get(cid, 0.0) + exposure_inc
            area["contacts"] += 1
            contact_events.append({
                "source_cow": area["source_cow"],
                "exposed_cow": cid,
                "area_id": area["area_id"],
                "source_time": area["source_end"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "exposed_time": t_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "distance_m": round(distance_m, 3),
                "radius_m": area["radius_m"],
                "hours_since_shedding": round(hours_diff, 1),
                "exposure_score": round(exposure_inc, 3),
            })

        if cid in flag_set:
            area_id = f"resting_area_{len(area_exposure) + 1:04d}"
            area_exposure[area_id] = {
                "area_id": area_id,
                "source_cow": cid,
                "source_start": t_start,
                "source_end": t_end,
                "center_x_m": float(bout["x_m"]),
                "center_y_m": float(bout["y_m"]),
                "radius_m": float(radius_m),
                "bedding_changed_at": last_change,
                "cumulative_duration_min": dur,
                "contacts": 0,
            }

    # Normalize cow exposure scores to [0.0, 1.0]
    cow_exposure: dict[str, float] = {}
    for cid, raw_score in cow_exposure_raw.items():
        if cid in flag_set:
            cow_exposure[cid] = 1.0
        else:
            cow_exposure[cid] = float(round(np.clip(1.0 - np.exp(-raw_score), 0.0, 1.0), 3))

    implicated_cells = []
    implicated_resting_areas = []
    for area in sorted(area_exposure.values(), key=lambda item: item["contacts"], reverse=True):
        next_change = get_next_bedding_change(area["source_end"])
        contacts = sorted({
            event["exposed_cow"] for event in contact_events
            if event["area_id"] == area["area_id"]
        })
        implicated_resting_areas.append({
            "area_id": area["area_id"],
            "center_x_m": round(area["center_x_m"], 2),
            "center_y_m": round(area["center_y_m"], 2),
            "radius_m": area["radius_m"],
            "source_cow": area["source_cow"],
            "target_cow_id": area["source_cow"],
            "target_cows": [area["source_cow"]],
            "until_bedding_change_utc": next_change.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bedding_changed_at": area["bedding_changed_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "contact_cows": contacts,
            "cumulative_shed_duration_min": round(area["cumulative_duration_min"], 1),
            "n_contacts": area["contacts"],
        })

    return {
        "cow_exposure": cow_exposure,
        "implicated_cells": implicated_cells,
        "implicated_resting_areas": implicated_resting_areas,
        "implicated_circles": implicated_resting_areas,
        "contact_events": contact_events,
        "co_occupancy_pairs_count": len(contact_events),
    }
