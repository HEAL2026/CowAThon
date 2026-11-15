"""Behavioral metrics, kinetic activity indexing, and rumination estimation.

Uses 1-minute aggregated IMU features (neck_imu_magnitude_std or 3-axis stds) to compute:
- Kinetic activity index
- Posture / activity state (resting vs active)
- Rumination proxy from characteristic low-amplitude cyclical neck motion
- Behavioral anomaly score (0 - 30 points)
"""

from __future__ import annotations
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


def classify_posture_state(
    activity_index: pd.Series | np.ndarray,
    resting_threshold: float = 0.08,
) -> pd.Series:
    """Classify posture / movement state into 'resting' or 'active'."""
    arr = np.asarray(activity_index)
    states = np.where(arr < resting_threshold, "resting", "active")
    if isinstance(activity_index, pd.Series):
        return pd.Series(states, index=activity_index.index, name="posture_state")
    return pd.Series(states, name="posture_state")


def calculate_rumination_proxy(
    df: pd.DataFrame,
    activity_col: str = "activity_index",
    lying_col: str = "lying",
) -> pd.Series:
    """Estimate rumination index (0 - 100) from neck-mounted IMU patterns and lying state.

    Rumination is characterized by rhythmic, low-to-moderate acceleration
    predominantly during resting/lying states.
    Drops significantly during acute distress, heat exhaustion, or ruminal disruption.
    """
    if activity_col in df.columns:
        act = df[activity_col]
    else:
        act = calculate_activity_index(df)

    in_resting_zone = act < 0.08
    rhythm_score = np.exp(-((act - 0.035) ** 2) / (2 * (0.02**2))) * 100.0
    rumination_score = np.where(in_resting_zone, rhythm_score, 0.0)

    # If ankle lying sensor is available, boost confidence when lying down
    if lying_col in df.columns:
        is_lying = df[lying_col].fillna(0).astype(int) == 1
        rumination_score = np.where(is_lying, rumination_score * 1.05, rumination_score * 0.95)

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
        immobility = np.clip((0.015 - act) / 0.015, 0.0, 1.0)
        score += immobility * 10.0

    return pd.Series(
        np.clip(score, 0.0, max_points),
        index=df.index,
        name="behavior_anomaly_score",
    )
