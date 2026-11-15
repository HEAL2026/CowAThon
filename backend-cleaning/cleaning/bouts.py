"""Lying bouts and in-pen location, for the resting-route trace (brief S3/S8).

A bout is a run of consecutive minutes with `lying == 1` lasting at least
`min_duration_min`. Each bout carries the median in-pen UWB position over
its minutes, so the tracer can put it in a grid cell. Minutes the cow was
out of the pen (milking) or had only suspect fixes contribute no location.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

MIN_DURATION_MIN = 5


def lying_bouts(joined: pd.DataFrame, min_duration_min: int = MIN_DURATION_MIN) -> pd.DataFrame:
    """One row per bout: cow_id, start_utc, end_utc (exclusive), duration_min,
    x_m, y_m, z_m (median of in-pen fixes), n_fixes, in_pen_frac."""
    need = {"cow_id", "ts_utc", "lying"}
    missing = need - set(joined.columns)
    if missing:
        raise KeyError(f"joined table lacks {sorted(missing)}")

    d = joined.sort_values(["cow_id", "ts_utc"]).copy()
    d["_lying"] = (d["lying"].fillna(0) >= 0.5)
    # a new run starts when lying flips, the cow changes, or the clock jumps
    gap = d.groupby("cow_id")["ts_utc"].diff() != pd.Timedelta(minutes=1)
    flip = d["_lying"] != d.groupby("cow_id")["_lying"].shift()
    d["_run"] = (gap | flip).cumsum()

    runs = d[d["_lying"]]
    if runs.empty:
        return pd.DataFrame(columns=["cow_id", "start_utc", "end_utc", "duration_min", "x_m", "y_m", "z_m", "n_fixes", "in_pen_frac"])

    def _summ(g: pd.DataFrame) -> pd.Series:
        inpen = g[~g["out_of_pen"].fillna(False).astype(bool)] if "out_of_pen" in g else g
        fixes = inpen.dropna(subset=["uwb_x_m", "uwb_y_m"]) if "uwb_x_m" in inpen else inpen.iloc[0:0]
        return pd.Series({
            "cow_id": g["cow_id"].iloc[0],
            "start_utc": g["ts_utc"].iloc[0],
            "end_utc": g["ts_utc"].iloc[-1] + pd.Timedelta(minutes=1),
            "duration_min": len(g),
            "x_m": fixes["uwb_x_m"].median() if len(fixes) else np.nan,
            "y_m": fixes["uwb_y_m"].median() if len(fixes) else np.nan,
            "z_m": fixes["uwb_z_m"].median() if "uwb_z_m" in fixes and len(fixes) else np.nan,
            "n_fixes": int(len(fixes)),
            "in_pen_frac": float(len(inpen) / len(g)),
        })

    bouts = runs.groupby("_run", sort=True).apply(_summ, include_groups=False).reset_index(drop=True)
    bouts = bouts[bouts["duration_min"] >= min_duration_min].reset_index(drop=True)
    bouts["duration_min"] = bouts["duration_min"].astype(int)
    return bouts


def location_1min_median(uwb: pd.DataFrame) -> pd.DataFrame:
    """Per cow-minute median of in-bounds, in-pen UWB fixes (brief S3 asks for
    a median; `joined_1min` carries the mean). Also the fix count."""
    d = uwb[~uwb["out_of_pen"] & ~uwb["uwb_suspect"]].copy()
    d["ts_utc"] = d["ts_utc"].dt.floor("min")
    g = d.groupby(["cow_id", "ts_utc"])
    out = g[["uwb_x_m", "uwb_y_m", "uwb_z_m"]].median()
    out.columns = ["x_med_m", "y_med_m", "z_med_m"]
    out["n_fixes"] = g.size()
    return out.reset_index()


def resting_areas(
    bouts: pd.DataFrame,
    min_duration_min: int = 20,
    radius_m: float = 1.5,
) -> pd.DataFrame:
    """Mark every cow's qualifying resting bout as a spatial area.

    The center is the bout's median in-pen UWB location. Downstream tracing
    uses this center and radius rather than a synthetic/grid cell label.
    """
    required = {"cow_id", "start_utc", "end_utc", "duration_min", "x_m", "y_m"}
    missing = required - set(bouts.columns)
    if missing:
        raise KeyError(f"lying bouts lacks {sorted(missing)}")
    if radius_m <= 0:
        raise ValueError(f"radius_m must be positive, got {radius_m}")
    out = bouts.loc[
        (bouts["duration_min"] >= min_duration_min)
        & bouts["x_m"].notna()
        & bouts["y_m"].notna()
    ].copy()
    out = out.rename(columns={"x_m": "center_x_m", "y_m": "center_y_m"})
    out["radius_m"] = float(radius_m)
    columns = [
        "cow_id", "start_utc", "end_utc", "duration_min",
        "center_x_m", "center_y_m", "radius_m",
    ]
    return out[columns].sort_values(["cow_id", "start_utc"]).reset_index(drop=True)


def resting_spots(
    bouts: pd.DataFrame,
    min_duration_min: int = 20,
    link_m: float = 1.5,
) -> pd.DataFrame:
    """Cubicle-level resting spots: clusters of qualifying bout centres with
    single-linkage <= `link_m`, dwell-weighted centroids (docs/backtrace_spec.md
    section 3.2). Bouts are visited longest first so the big cubicles seed the
    clusters. Returns one row per spot ordered by total dwell, plus a
    `spot_id` per input bout is NOT stored here -- assign at use time by
    nearest centre within `link_m` (see `assign_spots`)."""
    required = {"cow_id", "duration_min", "x_m", "y_m"}
    missing = required - set(bouts.columns)
    if missing:
        raise KeyError(f"lying bouts lacks {sorted(missing)}")
    if link_m <= 0:
        raise ValueError(f"link_m must be positive, got {link_m}")
    b = bouts.loc[(bouts["duration_min"] >= min_duration_min) & bouts["x_m"].notna() & bouts["y_m"].notna()]
    if "in_pen_frac" in b.columns:
        b = b[b["in_pen_frac"].fillna(1.0) >= 0.5]
    b = b.sort_values("duration_min", ascending=False)
    spots: list[dict] = []
    for x, y, dur, cow in zip(b["x_m"].to_numpy(float), b["y_m"].to_numpy(float), b["duration_min"].to_numpy(float), b["cow_id"]):
        for sp in spots:
            if np.hypot(sp["x"] - x, sp["y"] - y) <= link_m:
                w = sp["dwell"]
                sp["x"] = (sp["x"] * w + x * dur) / (w + dur)
                sp["y"] = (sp["y"] * w + y * dur) / (w + dur)
                sp["dwell"] += dur
                sp["n_bouts"] += 1
                sp["cows"].add(cow)
                break
        else:
            spots.append({"x": x, "y": y, "dwell": dur, "n_bouts": 1, "cows": {cow}})
    spots.sort(key=lambda sp: -sp["dwell"])
    return pd.DataFrame({
        "spot_id": [f"spot_{i + 1:02d}" for i in range(len(spots))],
        "center_x_m": [round(sp["x"], 3) for sp in spots],
        "center_y_m": [round(sp["y"], 3) for sp in spots],
        "radius_m": float(link_m),
        "n_bouts": [sp["n_bouts"] for sp in spots],
        "n_cows": [len(sp["cows"]) for sp in spots],
        "dwell_min": [round(sp["dwell"], 1) for sp in spots],
        "is_synthetic": False,
    })


def assign_spots(bouts: pd.DataFrame, spots: pd.DataFrame) -> pd.Series:
    """`spot_id` for each bout: nearest spot centre within its radius, else NA."""
    if len(spots) == 0 or len(bouts) == 0:
        return pd.Series(pd.NA, index=bouts.index, dtype="string")
    sx = spots["center_x_m"].to_numpy(float)[None, :]
    sy = spots["center_y_m"].to_numpy(float)[None, :]
    d = np.hypot(bouts["x_m"].to_numpy(float)[:, None] - sx, bouts["y_m"].to_numpy(float)[:, None] - sy)
    j = d.argmin(axis=1)
    ok = d[np.arange(len(bouts)), j] <= spots["radius_m"].to_numpy(float)[j]
    out = pd.Series(spots["spot_id"].to_numpy()[j], index=bouts.index, dtype="string")
    out[~ok | bouts["x_m"].isna().to_numpy()] = pd.NA
    return out


def mark_gaps(joined: pd.DataFrame, channels: dict[str, int], mark_after_min: int = 5) -> pd.DataFrame:
    """For each native per-cow channel, add `<col>_gap_min`: length of the
    run of missing minutes the row sits in, when that run exceeds the
    threshold; 0 otherwise. Marks, never fills (brief S3)."""
    d = joined.sort_values(["cow_id", "ts_utc"]).copy()
    for col in channels:
        if col not in d.columns:
            continue
        isna = d[col].isna()
        run_id = (isna != isna.groupby(d["cow_id"]).shift()).cumsum()
        run_len = isna.groupby(run_id).transform("size")
        d[f"{col}_gap_min"] = np.where(isna & (run_len > mark_after_min), run_len, 0).astype(int)
    return d
