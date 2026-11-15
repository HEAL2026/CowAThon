"""Environmental heat load and Temperature-Humidity Index (THI) analysis.

Standard formula: NRC / Thom formula for livestock:
THI = (1.8 * T + 32) - (0.55 - 0.0055 * RH) * (1.8 * T - 26)
where T is dry-bulb ambient temperature in °C and RH is relative humidity in %.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def calculate_thi(
    temp_c: float | np.ndarray | pd.Series,
    rh_pct: float | np.ndarray | pd.Series,
) -> float | np.ndarray | pd.Series:
    """Calculate the Temperature-Humidity Index (THI).

    Args:
        temp_c: Ambient temperature in degrees Celsius.
        rh_pct: Relative humidity in percent (0 - 100).

    Returns:
        THI value(s).
    """
    t_f = 1.8 * temp_c + 32.0
    thi = t_f - (0.55 - 0.0055 * rh_pct) * (1.8 * temp_c - 26.0)
    return thi


def categorize_thi_strain(
    thi: float | np.ndarray | pd.Series,
) -> str | np.ndarray | pd.Series:
    """Categorize THI into standard livestock heat stress categories.

    Thresholds:
        THI < 68.0: 'comfort'
        68.0 <= THI < 72.0: 'mild_strain'
        72.0 <= THI < 79.0: 'moderate_strain'
        THI >= 79.0: 'severe_strain'
    """
    if isinstance(thi, (pd.Series, np.ndarray)):
        arr = np.asarray(thi, dtype=float)
        categories = np.empty(arr.shape, dtype=object)
        categories[arr < 68.0] = "comfort"
        categories[(arr >= 68.0) & (arr < 72.0)] = "mild_strain"
        categories[(arr >= 72.0) & (arr < 79.0)] = "moderate_strain"
        categories[arr >= 79.0] = "severe_strain"
        if isinstance(thi, pd.Series):
            return pd.Series(categories, index=thi.index, name="thi_category")
        return categories
    else:
        v = float(thi)
        if v < 68.0:
            return "comfort"
        elif v < 72.0:
            return "mild_strain"
        elif v < 79.0:
            return "moderate_strain"
        else:
            return "severe_strain"


def calculate_thermal_load(
    df: pd.DataFrame,
    thi_col: str | None = None,
    time_col: str = "ts_utc",
    group_col: str = "cow_id",
    threshold: float = 68.0,
    window_hours: int = 24,
) -> pd.Series:
    """Calculate rolling cumulative thermal load (degree-hours above threshold).

    Args:
        df: Input DataFrame containing time and THI columns.
        thi_col: Column name containing THI (defaults to 'indoor_thi' or 'thi').
        time_col: Timestamp column.
        group_col: Animal or group grouping column.
        threshold: Heat stress threshold (default 68.0).
        window_hours: Rolling integration window in hours.

    Returns:
        pd.Series containing degree-hours thermal load.
    """
    if thi_col is None:
        if "indoor_thi" in df.columns:
            thi_col = "indoor_thi"
        elif "thi" in df.columns:
            thi_col = "thi"
        else:
            raise KeyError("Neither 'indoor_thi' nor 'thi' found in DataFrame.")

    thi_excess = (df[thi_col] - threshold).clip(lower=0.0)
    df_temp = df.copy()
    df_temp["_excess"] = thi_excess

    if group_col in df_temp.columns:
        rolling_load = df_temp.groupby(group_col)["_excess"].transform(
            lambda s: s.rolling(window_hours * 60, min_periods=1).sum() / 60.0
        )
    else:
        rolling_load = df_temp["_excess"].rolling(window_hours * 60, min_periods=1).sum() / 60.0

    return pd.Series(rolling_load, index=df.index, name="thermal_load_deg_hrs")
