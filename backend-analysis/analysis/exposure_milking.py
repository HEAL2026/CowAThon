"""S9: Milking equipment exposure tracing.

Tracks contagious pathogen transmission via sequential usage of milking units/clusters:
- Sequences cows through milking units (unit_id / stall_number).
- Resets equipment contamination upon parlor sanitation events (sanitized_at per unit).
- Quantifies sequential cluster contact exposure for unflagged cows milking after shedding animals.
"""

from __future__ import annotations
from typing import Any, Sequence
import numpy as np
import pandas as pd


def calculate_milking_exposure(
    milking_log_df: pd.DataFrame,
    sanitation_df: pd.DataFrame | None = None,
    flagged_cows: Sequence[str] | set[str] | None = None,
    lookback_hours: int = 72,
    reference_time: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Calculate milking-equipment contact exposure across sequential parlor visits.

    Args:
        milking_log_df: DataFrame with cow_id (or animal_id), milking_time (or event_datetime), and unit_id (or unit_code/stall_number).
        sanitation_df: Optional DataFrame with unit_id and sanitized_at (or event_datetime).
        flagged_cows: Cow IDs exhibiting acute mastitis / shedding.
        lookback_hours: Tracing investigation window in hours (default: 72).
        reference_time: Reference end time for lookback.

    Returns:
        Dictionary with cow_exposure (dict), implicated_units (list), and contact_events (list).
    """
    flag_set = {c if isinstance(c, str) else str(c.get("cow_id", "")) for c in flagged_cows} if flagged_cows else set()
    if len(milking_log_df) == 0:
        return {
            "cow_exposure": {},
            "implicated_units": [],
            "contact_events": [],
            "serial_contact_pairs_count": 0,
        }

    df_milking = milking_log_df.copy()

    # Column normalization
    cid_col = "cow_id" if "cow_id" in df_milking.columns else "animal_id"
    t_col = "milking_time" if "milking_time" in df_milking.columns else "event_datetime"
    unit_col = "unit_id" if "unit_id" in df_milking.columns else (
        "unit_code" if "unit_code" in df_milking.columns else "stall_number"
    )

    df_milking["ts_utc"] = pd.to_datetime(df_milking[t_col], utc=True)
    ref_t = reference_time or df_milking["ts_utc"].max()
    window_start = ref_t - pd.Timedelta(hours=lookback_hours)

    mask_valid = (df_milking["ts_utc"] >= window_start) & (df_milking["ts_utc"] <= ref_t)
    visits = df_milking[mask_valid].sort_values("ts_utc").copy()

    # Parse sanitation events per unit
    sanitations_by_unit: dict[str, list[pd.Timestamp]] = {}
    if sanitation_df is not None and len(sanitation_df) > 0:
        s_unit_col = "unit_id" if "unit_id" in sanitation_df.columns else "unit_code"
        s_t_col = "sanitized_at" if "sanitized_at" in sanitation_df.columns else "event_datetime"

        if s_unit_col in sanitation_df.columns and s_t_col in sanitation_df.columns:
            for u_id, s_group in sanitation_df.groupby(s_unit_col):
                sanitations_by_unit[str(u_id)] = sorted(
                    pd.to_datetime(s_group[s_t_col].dropna(), utc=True).tolist()
                )

    def was_sanitized_between(u_id: str, t_start: pd.Timestamp, t_end: pd.Timestamp) -> bool:
        s_list = sanitations_by_unit.get(u_id, [])
        return any(t_start < s_time <= t_end for s_time in s_list)

    # Process each milking unit sequentially
    contact_events: list[dict[str, Any]] = []
    cow_exposure_raw: dict[str, float] = {str(cid): 0.0 for cid in df_milking[cid_col].unique()}
    unit_contamination_counts: dict[str, int] = {}

    for unit, group in visits.groupby(unit_col):
        u_str = str(unit)
        unit_contamination_counts[u_str] = 0
        sorted_visits = group.sort_values("ts_utc")

        last_flagged_visit: dict[str, Any] | None = None

        for _, row in sorted_visits.iterrows():
            cid = str(row[cid_col])
            t_visit = row["ts_utc"]

            # Check if this cow arrives after an earlier un-sanitized flagged visit
            if last_flagged_visit is not None and last_flagged_visit["cow_id"] != cid:
                t_prev = last_flagged_visit["milking_time"]
                # Check if cluster was sanitized between the two visits
                if not was_sanitized_between(u_str, t_prev, t_visit):
                    hours_diff = (t_visit - t_prev).total_seconds() / 3600.0
                    decay = np.exp(-hours_diff / 4.0)
                    exposure_score = float(round(decay, 3))

                    if exposure_score > 0.05:
                        cow_exposure_raw[cid] = cow_exposure_raw.get(cid, 0.0) + exposure_score
                        unit_contamination_counts[u_str] += 1
                        contact_events.append({
                            "source_cow": last_flagged_visit["cow_id"],
                            "exposed_cow": cid,
                            "unit_id": u_str,
                            "source_time": t_prev.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "exposed_time": t_visit.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "hours_since_contamination": round(hours_diff, 2),
                            "was_sanitized_in_between": False,
                            "exposure_score": exposure_score,
                        })
                else:
                    # Sanitation cleared the cluster contamination
                    last_flagged_visit = None

            if cid in flag_set:
                # Flagged cow contaminates this milking unit
                last_flagged_visit = {
                    "cow_id": cid,
                    "milking_time": t_visit,
                }

    # Normalize cow exposure scores to [0.0, 1.0]
    cow_exposure: dict[str, float] = {}
    for cid, raw_score in cow_exposure_raw.items():
        if cid in flag_set:
            cow_exposure[cid] = 1.0
        else:
            cow_exposure[cid] = float(round(np.clip(1.0 - np.exp(-raw_score), 0.0, 1.0), 3))

    implicated_units = [
        {"unit_id": u, "transmission_count": cnt}
        for u, cnt in sorted(unit_contamination_counts.items(), key=lambda x: x[1], reverse=True)
        if cnt > 0
    ]

    return {
        "cow_exposure": cow_exposure,
        "implicated_units": implicated_units,
        "contact_events": contact_events,
        "serial_contact_pairs_count": len(contact_events),
    }
