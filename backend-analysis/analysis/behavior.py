"""Behavioral metrics, kinetic activity indexing, and rumination estimation.

Calibrated against empirical MMCows sensor distributions:
- Live cows: |accel| std p25 = 0.28, p50 = 0.45, p75 = 0.64 m/s²
- Stationary tags (T13/T14 on posts): |accel| std p25 = 0.08, p50 = 0.095, p75 = 0.18 m/s²
- Position std: stationary tags = 0.13-0.25 m vs cows = multiple meters

Uses multi-modal evidence (modality absence + spatial variance + IMU levels)
to avoid false classification of stationary reference hardware.
"""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd


def calculate_activity_index(
    df: pd.DataFrame,
    magnitude_std_col: str = "neck_imu_magnitude_std",
    acc_x_std_col: str = "acc_x_std",
    acc_y_std_col: str = "acc_y_std",
    acc_z_std_col: str = "acc_z_std",
) -> pd.Series:
    """Calculate the kinetic activity index from IMU acceleration magnitude standard deviation
    or 3-axis acceleration standard deviations.

    Activity Index = neck_imu_magnitude_std or sqrt(std_x^2 + std_y^2 + std_z^2)
    """
    if magnitude_std_col in df.columns:
        return pd.Series(df[magnitude_std_col], index=df.index, name="activity_index")

    cols = [acc_x_std_col, acc_y_std_col, acc_z_std_col]
    present = [c for c in cols if c in df.columns]

    if not present:
        return pd.Series(0.0, index=df.index, name="activity_index")

    squared_sum = sum(df[c] ** 2 for c in present)
    activity_index = np.sqrt(squared_sum)
    return pd.Series(activity_index, index=df.index, name="activity_index")


def detect_stationary_hardware_candidate(
    df: pd.DataFrame,
    group_col: str = "cow_id",
    activity_col: str = "neck_imu_magnitude_std",
    uwb_x_col: str = "uwb_x_m",
    uwb_y_col: str = "uwb_y_m",
    animal_modalities: tuple[str, ...] = ("cbt_c", "cbt", "lying", "milk_yield_kg", "milk_yield"),
) -> pd.Series:
    """Detect stationary hardware reference tags (e.g. T13/T14).

    Identified via structural modality absence (no CBT, lying, or milk records)
    combined with negligible spatial excursion (UWB position std < 0.35m)
    and low median IMU variance (< 0.15 m/s²).
    """
    is_hardware = pd.Series(False, index=df.index, name="is_stationary_hardware")

    present_animal_cols = [c for c in animal_modalities if c in df.columns and df[c].notna().any()]

    for cow_id, group in df.groupby(group_col):
        has_animal_data = False
        for col in present_animal_cols:
            if group[col].notna().any():
                has_animal_data = True
                break

        if has_animal_data:
            continue

        low_position_var = True
        if uwb_x_col in group.columns and uwb_y_col in group.columns:
            valid_uwb = group.dropna(subset=[uwb_x_col, uwb_y_col])
            if len(valid_uwb) >= 5:
                pos_std = np.sqrt(valid_uwb[uwb_x_col].std()**2 + valid_uwb[uwb_y_col].std()**2)
                low_position_var = pos_std < 0.35

        act_series = group[activity_col] if activity_col in group.columns else None
        low_imu_var = True
        if act_series is not None and act_series.notna().any():
            low_imu_var = act_series.median() < 0.15

        if low_position_var and low_imu_var:
            is_hardware.loc[group.index] = True

    return is_hardware


def classify_posture_state(
    activity_index: pd.Series | np.ndarray,
    resting_threshold: float = 0.20,
    is_stationary_hardware: pd.Series | np.ndarray | None = None,
) -> pd.Series:
    """Classify posture / movement state into 'stationary_hardware', 'resting', or 'active'.

    Live cattle kinetic variance distributions:
    - Deep rest / lying: ~0.06 - 0.20 m/s²
    - Active walking / feeding: > 0.20 m/s² (p50 = 0.45 m/s²)
    """
    arr = np.asarray(activity_index, dtype=float)
    states = np.empty(arr.shape, dtype=object)
    states[arr < resting_threshold] = "resting"
    states[arr >= resting_threshold] = "active"

    if is_stationary_hardware is not None:
        hw_mask = np.asarray(is_stationary_hardware, dtype=bool)
        states[hw_mask] = "stationary_hardware"

    if isinstance(activity_index, pd.Series):
        return pd.Series(states, index=activity_index.index, name="posture_state")
    return pd.Series(states, name="posture_state")


def calculate_rumination_proxy(
    df: pd.DataFrame,
    activity_col: str = "activity_index",
    lying_col: str = "lying",
) -> pd.Series:
    """Estimate rumination index (0 - 100) from neck-mounted IMU patterns and lying state.

    Rumination occurs predominantly during resting/lying windows in the 0.08 - 0.22 m/s² band.
    """
    if activity_col in df.columns:
        act = df[activity_col]
    else:
        act = calculate_activity_index(df)

    in_resting_zone = (act >= 0.06) & (act < 0.22)
    rhythm_score = np.exp(-((act - 0.12) ** 2) / (2 * (0.04**2))) * 100.0
    rumination_score = np.where(in_resting_zone, rhythm_score, 0.0)

    # Ankle lying sensor concordance
    if lying_col in df.columns:
        is_lying = df[lying_col].fillna(0).astype(int) == 1
        rumination_score = np.where(is_lying, rumination_score * 1.10, rumination_score * 0.90)

    return pd.Series(
        np.clip(rumination_score, 0.0, 100.0),
        index=df.index,
        name="rumination_proxy",
    )


def calculate_behavior_anomaly_score(
    df: pd.DataFrame,
    activity_col: str = "activity_index",
    rumination_col: str = "rumination_proxy",
    max_points: float = 30.0,
) -> pd.Series:
    """Calculate behavioral anomaly score (0 - 30 points)."""
    score = np.zeros(len(df), dtype=float)

    if rumination_col in df.columns:
        rum = df[rumination_col].values
        deficit = np.clip((40.0 - rum) / 40.0, 0.0, 1.0)
        score += deficit * 20.0

    if activity_col in df.columns:
        act = df[activity_col].values
        immobility = np.clip((0.10 - act) / 0.10, 0.0, 1.0)
        score += immobility * 10.0

    return pd.Series(
        np.clip(score, 0.0, max_points),
        index=df.index,
        name="behavior_anomaly_score",
    )


def validate_behavior_against_ground_truth(
    df: pd.DataFrame,
    behavior_mode_col: str = "behavior_mode",
    behavior_mode_name_col: str = "behavior_mode_name",
    lying_frac_col: str = "behavior_lying_frac",
    posture_col: str = "posture_state",
    ankle_lying_col: str = "lying",
) -> dict[str, Any]:
    """Validate posture and activity predictions against real MMCows ground-truth labels.

    Evaluates:
    - Posture concordance (lying/resting vs standing/active)
    - Agreement between ankle accelerometer (lying) and vision ground truth
    - Excludes unknown behavior (mode == 0) per official benchmark conventions.
    """
    has_labels = (
        (behavior_mode_col in df.columns and df[behavior_mode_col].notna().any())
        or (behavior_mode_name_col in df.columns and df[behavior_mode_name_col].notna().any())
        or (lying_frac_col in df.columns and df[lying_frac_col].notna().any())
    )

    if not has_labels:
        return {
            "has_ground_truth_labels": False,
            "note": "No ground-truth behavior annotations present in this window (annotations available for 2023-07-25).",
        }

    mask = pd.Series(False, index=df.index)
    if behavior_mode_col in df.columns:
        mask = mask | (df[behavior_mode_col].notna() & (df[behavior_mode_col] != 0))
    if behavior_mode_name_col in df.columns:
        mask = mask | (df[behavior_mode_name_col].notna() & (df[behavior_mode_name_col] != "unknown"))
    if lying_frac_col in df.columns:
        mask = mask | df[lying_frac_col].notna()

    labeled_df = df.loc[mask].copy()
    if len(labeled_df) == 0:
        return {"has_ground_truth_labels": False, "n_labeled_rows": 0}

    is_gt_lying = pd.Series(False, index=labeled_df.index)
    if behavior_mode_col in labeled_df.columns:
        is_gt_lying = is_gt_lying | (labeled_df[behavior_mode_col] == 7)
    if behavior_mode_name_col in labeled_df.columns:
        is_gt_lying = is_gt_lying | (labeled_df[behavior_mode_name_col] == "lying")
    if lying_frac_col in labeled_df.columns:
        is_gt_lying = is_gt_lying | (labeled_df[lying_frac_col] >= 0.5)

    gt_arr = is_gt_lying.astype(int).values

    results: dict[str, Any] = {
        "has_ground_truth_labels": True,
        "n_labeled_rows": len(labeled_df),
        "gt_lying_rate": round(float(np.mean(gt_arr)), 3),
    }

    if ankle_lying_col in labeled_df.columns and labeled_df[ankle_lying_col].notna().any():
        ankle_pred = labeled_df[ankle_lying_col].fillna(0).astype(int).values
        ankle_acc = float(np.mean(ankle_pred == gt_arr))
        results["ankle_sensor_ground_truth_concordance"] = round(ankle_acc, 3)

    if posture_col in labeled_df.columns:
        pred_resting = (labeled_df[posture_col] == "resting").astype(int).values
        acc = float(np.mean(pred_resting == gt_arr))
        tp = int(np.sum((gt_arr == 1) & (pred_resting == 1)))
        fp = int(np.sum((gt_arr == 0) & (pred_resting == 1)))
        fn = int(np.sum((gt_arr == 1) & (pred_resting == 0)))
        tn = int(np.sum((gt_arr == 0) & (pred_resting == 0)))

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        results["imu_posture_model"] = {
            "accuracy": round(acc, 3),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        }

    return results
