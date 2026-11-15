"""Behavioral metrics, kinetic activity indexing, and rumination estimation.

Uses 1-minute aggregated IMU features (mean and std across axes) to compute:
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
    acc_x_std_col: str = "acc_x_std",
    acc_y_std_col: str = "acc_y_std",
    acc_z_std_col: str = "acc_z_std",
) -> pd.Series:
    """Calculate the kinetic activity index from 3-axis acceleration standard deviations.

    Activity Index = sqrt(std_x^2 + std_y^2 + std_z^2)
    """
    cols = [acc_x_std_col, acc_y_std_col, acc_z_std_col]
    present = [c for c in cols if c in df.columns]

    if not present:
        # Graceful fallback: return zeros or ones if no IMU std columns exist
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
    acc_y_std_col: str = "acc_y_std",
    acc_z_std_col: str = "acc_z_std",
) -> pd.Series:
    """Estimate rumination index (0 - 100) from neck-mounted IMU patterns.

    Rumination is characterized by rhythmic, low-to-moderate acceleration
    predominantly along vertical and lateral neck axes during resting states.
    Drops significantly during acute distress, heat exhaustion, or ruminal disruption.
    """
    if activity_col in df.columns:
        act = df[activity_col]
    else:
        act = calculate_activity_index(df)

    # Base rumination signature: peaks in low-to-moderate activity zone (0.01 to 0.06 g)
    # Beyond 0.08 g, motion is whole-body walking/active and rumination ceases
    in_resting_zone = act < 0.08
    rhythm_score = np.exp(-((act - 0.035) ** 2) / (2 * (0.02**2))) * 100.0
    rumination_score = np.where(in_resting_zone, rhythm_score, 0.0)

    return pd.Series(
        np.clip(rumination_score, 0.0, 100.0),
        index=df.index,
        name="rumination_proxy",
    )


def calculate_behavior_anomaly_score(
    df: pd.DataFrame,
    activity_col: str = "activity_index",
    rumination_col: str = "rumination_proxy",
    expected_daily_rumination: float = 55.0,
    max_points: float = 30.0,
) -> pd.Series:
    """Calculate behavioral anomaly score (0 - 30 points).

    Penalizes:
    - Depressed rumination below expected baseline (rumination deficit)
    - Extreme lethargy during daytime or acute agitation during nighttime
    """
    score = np.zeros(len(df), dtype=float)

    if rumination_col in df.columns:
        rum = df[rumination_col].values
        # Rumination deficit: below 40 adds progressive anomaly points
        deficit = np.clip((40.0 - rum) / 40.0, 0.0, 1.0)
        score += deficit * 20.0

    if activity_col in df.columns:
        act = df[activity_col].values
        # Severe immobility / lethargy (near zero kinetic motion prolonged)
        immobility = np.clip((0.015 - act) / 0.015, 0.0, 1.0)
        score += immobility * 10.0

    return pd.Series(
        np.clip(score, 0.0, max_points),
        index=df.index,
        name="behavior_anomaly_score",
    )
