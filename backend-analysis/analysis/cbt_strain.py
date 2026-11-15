"""Core Body Temperature (CBT) dynamics and physiological strain modeling.

Normal dairy cow core body temperature ranges from 38.5°C to 39.2°C.
Temperatures above 39.3°C reflect physiological heat strain or febrile state.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def calculate_cbt_strain_score(
    cbt_c: float | np.ndarray | pd.Series,
    baseline_temp_c: float = 38.8,
    mild_threshold_c: float = 39.2,
    severe_threshold_c: float = 40.0,
    max_points: float = 40.0,
) -> float | np.ndarray | pd.Series:
    """Calculate physiological thermal strain score from core body temperature.

    Score allocation (0 - 40 points):
        CBT <= 39.2°C: 0.0 (normal comfort range)
        39.2°C < CBT <= 40.0°C: Linear scale from 0 to 30 points
        CBT > 40.0°C: Linear scale from 30 up to max_points (40.0) at 41.0°C.

    Args:
        cbt_c: Core body temperature in °C.
        baseline_temp_c: Reference normal cow temperature.
        mild_threshold_c: Threshold where mild strain begins.
        severe_threshold_c: Threshold where severe strain begins.
        max_points: Maximum score points allocated to CBT (default 40.0).

    Returns:
        Strain score between 0.0 and max_points.
    """
    arr = np.asarray(cbt_c, dtype=float)
    score = np.zeros_like(arr, dtype=float)

    mask_mild = (arr > mild_threshold_c) & (arr <= severe_threshold_c)
    score[mask_mild] = (arr[mask_mild] - mild_threshold_c) / (
        severe_threshold_c - mild_threshold_c
    ) * 30.0

    mask_severe = arr > severe_threshold_c
    excess_above_severe = np.clip((arr[mask_severe] - severe_threshold_c) / 1.0, 0.0, 1.0)
    score[mask_severe] = 30.0 + excess_above_severe * 10.0

    if isinstance(cbt_c, pd.Series):
        return pd.Series(score, index=cbt_c.index, name="cbt_strain_score")
    elif np.isscalar(cbt_c):
        return float(score.item())
    return score


def detect_temperature_spikes(
    df: pd.DataFrame,
    cbt_col: str | None = None,
    time_col: str = "ts_utc",
    group_col: str = "cow_id",
    spike_threshold_c: float = 39.5,
    min_duration_minutes: int = 30,
) -> pd.DataFrame:
    """Identify sustained elevated temperature episodes per animal.

    Args:
        df: DataFrame containing temperature, animal ID, and timestamps.
        cbt_col: Column containing core body temperature ('cbt_c' or 'cbt').
        time_col: Timestamp column.
        group_col: Cow identifier.
        spike_threshold_c: Temperature threshold for spike event.
        min_duration_minutes: Minimum consecutive duration to classify as sustained episode.

    Returns:
        DataFrame summarizing spike events with start, end, duration, and peak CBT.
    """
    if cbt_col is None:
        if "cbt_c" in df.columns:
            cbt_col = "cbt_c"
        elif "cbt" in df.columns:
            cbt_col = "cbt"
        else:
            return pd.DataFrame(columns=[group_col, "start_time", "end_time", "duration_min", "peak_cbt"])

    if group_col not in df.columns:
        return pd.DataFrame(columns=[group_col, "start_time", "end_time", "duration_min", "peak_cbt"])

    episodes = []
    for cow_id, group in df.groupby(group_col):
        g = group.sort_values(time_col).copy()
        is_high = g[cbt_col] >= spike_threshold_c
        blocks = (~is_high).cumsum()[is_high]
        for _, block in g[is_high].groupby(blocks):
            duration = len(block)
            if duration >= min_duration_minutes:
                episodes.append({
                    group_col: cow_id,
                    "start_time": block[time_col].iloc[0],
                    "end_time": block[time_col].iloc[-1],
                    "duration_min": duration,
                    "peak_cbt": float(block[cbt_col].max()),
                })

    return pd.DataFrame(episodes)
