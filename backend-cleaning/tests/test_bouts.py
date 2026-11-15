"""Tests for lying bouts, median location and gap marking (brief S3).

Run from backend-cleaning/:  python3 tests/test_bouts.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cleaning.bouts import lying_bouts, location_1min_median, mark_gaps  # noqa: E402

T0 = pd.Timestamp("2023-07-25 05:00:00", tz="UTC")


def _grid(lying, out_of_pen=None, x=None, cow="C01"):
    n = len(lying)
    return pd.DataFrame({
        "cow_id": cow,
        "ts_utc": pd.date_range(T0, periods=n, freq="1min", tz="UTC"),
        "lying": lying,
        "out_of_pen": out_of_pen if out_of_pen is not None else [False] * n,
        "uwb_x_m": x if x is not None else [1.0] * n,
        "uwb_y_m": [2.0] * n,
        "uwb_z_m": [0.9] * n,
    })


def test_bouts_respect_min_duration_and_boundaries():
    # 3 min lying (too short), 2 up, 6 min lying (bout), 1 up, 5 min lying (bout, exactly at threshold)
    lying = [1] * 3 + [0] * 2 + [1] * 6 + [0] + [1] * 5
    b = lying_bouts(_grid(lying), min_duration_min=5)
    assert b["duration_min"].tolist() == [6, 5]
    assert b["start_utc"].iloc[0] == T0 + pd.Timedelta(minutes=5)
    assert b["end_utc"].iloc[0] == T0 + pd.Timedelta(minutes=11), "end is exclusive"


def test_bout_location_is_median_of_in_pen_fixes_only():
    lying = [1] * 8
    x = [1.0, 1.0, 1.0, 9.0, 9.0, 1.0, 1.0, 50.0]        # 50 is an out-of-pen minute's junk
    oop = [False] * 7 + [True]
    b = lying_bouts(_grid(lying, out_of_pen=oop, x=x))
    assert len(b) == 1
    assert b["x_m"].iloc[0] == 1.0, "median of the 7 in-pen fixes, out-of-pen minute excluded"
    assert b["n_fixes"].iloc[0] == 7 and abs(b["in_pen_frac"].iloc[0] - 7 / 8) < 1e-9


def test_a_time_jump_splits_a_bout_and_nan_lying_is_not_lying():
    g = _grid([1] * 10)
    g = g.drop(index=[4, 5]).reset_index(drop=True)      # 2-minute hole in the clock
    b = lying_bouts(g, min_duration_min=3)
    assert b["duration_min"].tolist() == [4, 4], "a gap in the grid ends the run"
    g2 = _grid([1, 1, 1, np.nan, 1, 1, 1])
    assert lying_bouts(g2, min_duration_min=3)["duration_min"].tolist() == [3, 3]


def test_two_cows_do_not_merge():
    a = _grid([1] * 6, cow="C01"); b = _grid([1] * 6, cow="C02")
    out = lying_bouts(pd.concat([a, b], ignore_index=True))
    assert sorted(out["cow_id"].tolist()) == ["C01", "C02"] and out["duration_min"].tolist() == [6, 6]


def test_location_median_excludes_suspect_and_out_of_pen():
    ts = [T0 + pd.Timedelta(seconds=15 * i) for i in range(4)]
    u = pd.DataFrame({"cow_id": "C01", "ts_utc": ts, "uwb_x_m": [1.0, 1.0, 9.0, 40.0], "uwb_y_m": 0.0, "uwb_z_m": 1.0,
                      "out_of_pen": [False, False, False, False], "uwb_suspect": [False, False, False, True]})
    m = location_1min_median(u)
    assert len(m) == 1 and m["x_med_m"].iloc[0] == 1.0 and m["n_fixes"].iloc[0] == 3


def test_gap_marks_only_runs_longer_than_threshold():
    g = _grid([1] * 14)
    g["cbt_c"] = 38.5
    g.loc[2:3, "cbt_c"] = np.nan        # 2-minute hole: below threshold, not marked
    g.loc[6:12, "cbt_c"] = np.nan       # 7-minute hole: marked with its length
    out = mark_gaps(g, {"cbt_c": 1}, mark_after_min=5)
    assert out["cbt_c_gap_min"].tolist() == [0, 0, 0, 0, 0, 0, 7, 7, 7, 7, 7, 7, 7, 0]
    assert out["cbt_c"].isna().sum() == 9, "marking never fills"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
