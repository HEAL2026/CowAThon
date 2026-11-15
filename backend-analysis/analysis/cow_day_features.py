"""S5: Per cow-day feature aggregation.

Aggregates 1-minute time series into standardized cow-day summary records:
- Thermal load: cbt_mean, cbt_max, cbt_std, cbt_spikes, thi_mean, thi_hours_above_68
- Production: daily_milk_yield_kg, milk_drop_pct
- Posture & Lying: lying_time_min, lying_bouts_count, mean_bout_duration_min
- Behavior: activity_index_mean, activity_index_std, clf_*_time_min
- Feeding proxy: feeding_time_min / active feeding zone
- Optional clinical/lab indicators: conductivity_max, scc_mean
- Optional feed intake: dmi_kg and 2–3 day lagged DMI features for production
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional


def aggregate_cow_day_features(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1-minute joined observations to per cow-day records.

    Args:
        df: Input DataFrame with cow_id and ts_utc.

    Returns:
        DataFrame with one row per (cow_id, date) containing summary features.
    """
    if len(df) == 0:
        return pd.DataFrame()

    df_proc = df.copy()

    # Ensure timestamp is datetime and extract calendar date
    if "ts_utc" in df_proc.columns:
        ts = pd.to_datetime(df_proc["ts_utc"], utc=True)
        df_proc["date"] = ts.dt.date
    elif "date" not in df_proc.columns:
        df_proc["date"] = pd.Timestamp.now(tz="UTC").date()

    # Identify existing column names (accounting for aliases)
    cbt_col = "cbt_c" if "cbt_c" in df_proc.columns else (
        "cbt" if "cbt" in df_proc.columns else (
            "rectal_temp_c" if "rectal_temp_c" in df_proc.columns else (
                "rectal_temp" if "rectal_temp" in df_proc.columns else None
            )
        )
    )
    thi_col = "indoor_thi" if "indoor_thi" in df_proc.columns else ("thi" if "thi" in df_proc.columns else None)
    act_col = "activity_index" if "activity_index" in df_proc.columns else (
        "neck_imu_magnitude_std" if "neck_imu_magnitude_std" in df_proc.columns else None
    )
    milk_col = "milk_yield_kg" if "milk_yield_kg" in df_proc.columns else (
        "milk_yield" if "milk_yield" in df_proc.columns else None
    )
    drop_col = "milk_drop_pct" if "milk_drop_pct" in df_proc.columns else None
    lying_col = "lying" if "lying" in df_proc.columns else None
    dim_col = "dim" if "dim" in df_proc.columns else None
    parity_col = "parity" if "parity" in df_proc.columns else None
    cond_col = "conductivity" if "conductivity" in df_proc.columns else None
    scc_col = "scc" if "scc" in df_proc.columns else None
    resp_col = "respiration_rate_bpm" if "respiration_rate_bpm" in df_proc.columns else (
        "respiration_rate" if "respiration_rate" in df_proc.columns else None
    )
    pulse_col = "pulse_rate_bpm" if "pulse_rate_bpm" in df_proc.columns else (
        "pulse_rate" if "pulse_rate" in df_proc.columns else None
    )
    dmi_col = "dmi_kg" if "dmi_kg" in df_proc.columns else (
        "dmi" if "dmi" in df_proc.columns else None
    )
    fat_col = "milk_fat_pct" if "milk_fat_pct" in df_proc.columns else (
        "fat_pct" if "fat_pct" in df_proc.columns else None
    )
    prot_col = "milk_protein_pct" if "milk_protein_pct" in df_proc.columns else (
        "protein_pct" if "protein_pct" in df_proc.columns else None
    )
    lact_col = "milk_lactose_pct" if "milk_lactose_pct" in df_proc.columns else (
        "lactose_pct" if "lactose_pct" in df_proc.columns else None
    )
    b_name_col = "behavior_name" if "behavior_name" in df_proc.columns else None
    b_code_col = "behavior" if "behavior" in df_proc.columns else None

    # Group by cow_id and date
    records = []
    for (cow_id, date), group in df_proc.groupby(["cow_id", "date"]):
        rec: dict[str, object] = {
            "cow_id": str(cow_id),
            "date": str(date),
            "n_records_1min": len(group),
        }

        # Stationary hardware check
        rec["is_stationary_hardware"] = bool(
            group["is_stationary_hardware"].any() if "is_stationary_hardware" in group.columns else False
        )
        rec["is_synthetic"] = bool(
            group["is_synthetic"].any() if "is_synthetic" in group.columns else False
        )

        # 1. Thermal Metrics
        if cbt_col and group[cbt_col].notna().any():
            cbt_s = group[cbt_col].dropna()
            rec["cbt_mean"] = round(float(cbt_s.mean()), 2)
            rec["cbt_max"] = round(float(cbt_s.max()), 2)
            rec["cbt_std"] = round(float(cbt_s.std()), 3) if len(cbt_s) > 1 else 0.0
            rec["cbt_spikes_count"] = int((cbt_s >= 39.3).sum())
        else:
            rec["cbt_mean"] = None
            rec["cbt_max"] = None
            rec["cbt_std"] = None
            rec["cbt_spikes_count"] = 0

        if thi_col and group[thi_col].notna().any():
            thi_s = group[thi_col].dropna()
            rec["thi_mean"] = round(float(thi_s.mean()), 1)
            rec["thi_max"] = round(float(thi_s.max()), 1)
            rec["thi_hours_above_68"] = round(float((thi_s >= 68.0).sum() / 60.0), 2)
        else:
            rec["thi_mean"] = None
            rec["thi_max"] = None
            rec["thi_hours_above_68"] = 0.0

        # 2. Production Metrics
        if milk_col and group[milk_col].notna().any():
            # Daily yield is either daily sum or representative daily record
            rec["daily_milk_yield_kg"] = round(float(group[milk_col].dropna().iloc[-1]), 1)
        else:
            rec["daily_milk_yield_kg"] = None

        if drop_col and group[drop_col].notna().any():
            rec["milk_drop_pct"] = round(float(group[drop_col].dropna().max()), 1)
        else:
            rec["milk_drop_pct"] = 0.0

        # 3. Posture & Lying Bouts
        if lying_col and group[lying_col].notna().any():
            lying_s = group[lying_col].dropna().astype(int)
            total_lying_min = int(lying_s.sum())
            rec["lying_time_min"] = total_lying_min

            # Count continuous lying bouts >= 5 minutes
            bouts = []
            cur_bout = 0
            for val in lying_s.values:
                if val == 1:
                    cur_bout += 1
                else:
                    if cur_bout >= 5:
                        bouts.append(cur_bout)
                    cur_bout = 0
            if cur_bout >= 5:
                bouts.append(cur_bout)

            rec["lying_bouts_count"] = len(bouts)
            rec["mean_bout_duration_min"] = round(float(np.mean(bouts)), 1) if bouts else 0.0
        else:
            rec["lying_time_min"] = None
            rec["lying_bouts_count"] = None
            rec["mean_bout_duration_min"] = None

        # 4. Activity & Rumination
        if act_col and group[act_col].notna().any():
            act_s = group[act_col].dropna()
            rec["activity_index_mean"] = round(float(act_s.mean()), 4)
            rec["activity_index_std"] = round(float(act_s.std()), 4) if len(act_s) > 1 else 0.0
        else:
            rec["activity_index_mean"] = None
            rec["activity_index_std"] = None

        # 4b. Trained Behavior Classifier Durations (MMCows 8-class vocabulary: 0 unknown, 1 walking, 2 standing, 3 feed_up, 4 feed_down, 5 licking, 6 drinking, 7 lying)
        if b_name_col and group[b_name_col].notna().any():
            b_names = group[b_name_col].astype(str).str.lower()
            rec["clf_lying_time_min"] = int((b_names == "lying").sum())
            rec["clf_standing_time_min"] = int((b_names == "standing").sum())
            rec["clf_walking_time_min"] = int((b_names == "walking").sum())
            rec["clf_feed_up_time_min"] = int((b_names == "feed_up").sum())
            rec["clf_feed_down_time_min"] = int((b_names == "feed_down").sum())
            rec["clf_feeding_time_min"] = int(np.isin(b_names, ["feed_up", "feed_down"]).sum())
            rec["clf_drinking_time_min"] = int((b_names == "drinking").sum())
            rec["clf_licking_time_min"] = int((b_names == "licking").sum())
            if rec.get("lying_time_min") is None:
                rec["lying_time_min"] = rec["clf_lying_time_min"]
        elif b_code_col and group[b_code_col].notna().any():
            b_codes = group[b_code_col].fillna(0).astype(int)
            rec["clf_lying_time_min"] = int((b_codes == 7).sum())
            rec["clf_standing_time_min"] = int((b_codes == 2).sum())
            rec["clf_walking_time_min"] = int((b_codes == 1).sum())
            rec["clf_feed_up_time_min"] = int((b_codes == 3).sum())
            rec["clf_feed_down_time_min"] = int((b_codes == 4).sum())
            rec["clf_feeding_time_min"] = int(np.isin(b_codes, [3, 4]).sum())
            rec["clf_drinking_time_min"] = int((b_codes == 6).sum())
            rec["clf_licking_time_min"] = int((b_codes == 5).sum())
            if rec.get("lying_time_min") is None:
                rec["lying_time_min"] = rec["clf_lying_time_min"]
        else:
            rec["clf_lying_time_min"] = None
            rec["clf_standing_time_min"] = None
            rec["clf_walking_time_min"] = None
            rec["clf_feed_up_time_min"] = None
            rec["clf_feed_down_time_min"] = None
            rec["clf_feeding_time_min"] = None
            rec["clf_drinking_time_min"] = None
            rec["clf_licking_time_min"] = None

        # 5. Cohort metadata (DIM and parity)
        if dim_col and group[dim_col].notna().any():
            rec["dim"] = int(group[dim_col].dropna().iloc[-1])
        else:
            rec["dim"] = 120  # Mid lactation default

        if parity_col and group[parity_col].notna().any():
            rec["parity"] = int(group[parity_col].dropna().iloc[-1])
        else:
            rec["parity"] = 2  # Multiparous default

        # 6. Optional Mastitis / Lab Indicators
        if cond_col and group[cond_col].notna().any():
            rec["conductivity_max"] = round(float(group[cond_col].dropna().max()), 2)
        else:
            rec["conductivity_max"] = None

        if scc_col and group[scc_col].notna().any():
            rec["scc_mean"] = round(float(group[scc_col].dropna().mean()), 1)
        else:
            rec["scc_mean"] = None

        # 7. Optional External Physiology / Nutrition Indicators (e.g. Mendeley 954f6g36sb/2)
        if resp_col and group[resp_col].notna().any():
            resp_s = group[resp_col].dropna()
            rec["respiration_rate_bpm_mean"] = round(float(resp_s.mean()), 1)
            rec["respiration_rate_bpm_max"] = round(float(resp_s.max()), 1)
        else:
            rec["respiration_rate_bpm_mean"] = None
            rec["respiration_rate_bpm_max"] = None

        if pulse_col and group[pulse_col].notna().any():
            rec["pulse_rate_bpm_mean"] = round(float(group[pulse_col].dropna().mean()), 1)
        else:
            rec["pulse_rate_bpm_mean"] = None

        if dmi_col and group[dmi_col].notna().any():
            rec["dmi_kg"] = round(float(group[dmi_col].dropna().iloc[-1]), 2)
        else:
            rec["dmi_kg"] = None

        if fat_col and group[fat_col].notna().any():
            v_fat = round(float(group[fat_col].dropna().iloc[-1]), 2)
            rec["milk_fat_pct"] = v_fat
            rec["fat_pct"] = v_fat
        else:
            rec["milk_fat_pct"] = None
            rec["fat_pct"] = None

        if prot_col and group[prot_col].notna().any():
            v_prot = round(float(group[prot_col].dropna().iloc[-1]), 2)
            rec["milk_protein_pct"] = v_prot
            rec["protein_pct"] = v_prot
        else:
            rec["milk_protein_pct"] = None
            rec["protein_pct"] = None

        if lact_col and group[lact_col].notna().any():
            v_lact = round(float(group[lact_col].dropna().iloc[-1]), 2)
            rec["milk_lactose_pct"] = v_lact
            rec["lactose_pct"] = v_lact
        else:
            rec["milk_lactose_pct"] = None
            rec["lactose_pct"] = None

        records.append(rec)

    result = pd.DataFrame(records)
    if "dmi_kg" in result.columns and len(result):
        result = result.sort_values(["cow_id", "date"]).reset_index(drop=True)
        grouped = result.groupby("cow_id", sort=False)["dmi_kg"]
        result["dmi_kg_lag_2d"] = grouped.shift(2)
        result["dmi_kg_lag_3d"] = grouped.shift(3)
        result["dmi_kg_lagged_mean"] = result[
            ["dmi_kg_lag_2d", "dmi_kg_lag_3d"]
        ].mean(axis=1, skipna=True)
    return result
