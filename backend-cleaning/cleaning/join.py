"""Stage 2: interim tables -> data/processed/joined_1min.parquet.

One row = one cow x one minute. Fast channels are aggregated to the minute,
slow channels are forward-filled and flagged with <col>_is_imputed plus
<col>_age_s (seconds since the last real observation). Nothing is ever filled
across an out_of_pen gap because no per-cow channel is forward-filled at all:
cbt/lying gaps stay NaN. See CONTRACT.md section 5.2.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .ingest import BEHAVIOR_NAMES, UNITS, write_table

CADENCE = "1min"
# a slow channel older than this is reported as missing, not carried forward
STALE_AFTER_S = {"weather": 30 * 60, "thi": 10 * 60}


def _read(interim: Path, name: str) -> pd.DataFrame | None:
    p = interim / f"{name}.parquet"
    return pd.read_parquet(p) if p.exists() else None


def minute_grid(cows: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    minutes = pd.date_range(start.floor("min"), end.floor("min"), freq="1min", tz="UTC")
    return pd.MultiIndex.from_product([sorted(cows), minutes], names=["cow_id", "ts_utc"]).to_frame(index=False)


def to_minute(df: pd.DataFrame, by: list[str], agg: dict) -> pd.DataFrame:
    """Floor ts_utc to the minute and aggregate duplicates per `by`."""
    d = df.assign(ts_utc=df["ts_utc"].dt.floor("min"))
    return d.groupby(by + ["ts_utc"], as_index=False).agg(agg)


def attach_slow(grid_minutes: pd.DataFrame, obs: pd.DataFrame, cols: list[str], stale_after_s: int) -> pd.DataFrame:
    """Forward-fill a barn-level (no cow_id) slow channel onto the minute grid.

    Returns the grid with `cols`, `<col>_is_imputed` and `<col>_age_s`. A row
    is imputed when the observation is not from that same minute; beyond
    `stale_after_s` the value is reported as missing (age still recorded)."""
    obs = obs.sort_values("ts_utc").assign(_obs_ts=lambda d: d["ts_utc"])
    merged = pd.merge_asof(grid_minutes.sort_values("ts_utc"), obs[["ts_utc", "_obs_ts"] + cols],
                           on="ts_utc", direction="backward")
    age = (merged["ts_utc"] - merged["_obs_ts"]).dt.total_seconds()
    stale = age > stale_after_s
    for c in cols:
        merged.loc[stale, c] = np.nan
        merged[f"{c}_is_imputed"] = (age > 0) & ~stale & merged[c].notna()
        merged[f"{c}_age_s"] = age
    return merged.drop(columns="_obs_ts")


def attach_daily_milk(grid: pd.DataFrame, milk: pd.DataFrame, tz: str) -> pd.DataFrame:
    """Daily yield carried through the local day it was recorded on."""
    m = milk.assign(_day=milk["ts_utc"].dt.tz_convert(tz).dt.date, _stamp=milk["ts_utc"])
    g = grid.assign(_day=grid["ts_utc"].dt.tz_convert(tz).dt.date)
    out = g.merge(m[["cow_id", "_day", "_stamp", "milk_yield_kg", "dim"]], on=["cow_id", "_day"], how="left")
    has = out["milk_yield_kg"].notna()
    out["milk_yield_kg_is_imputed"] = has  # a daily figure on a minute row is always a carry
    out["milk_yield_kg_age_s"] = (out["ts_utc"] - out["_stamp"]).dt.total_seconds().clip(lower=0)
    return out.drop(columns=["_day", "_stamp"])


def behavior_minute(beh: pd.DataFrame) -> pd.DataFrame:
    """1 s labels -> per cow-minute: dominant known code, its name, and how
    much of the minute was labelled at all / labelled lying. Unknown seconds
    (code 0) count toward coverage only, never toward the mode."""
    d = beh.assign(ts_utc=beh["ts_utc"].dt.floor("min"))
    cov = d.groupby(["cow_id", "ts_utc"]).agg(behavior_known_frac=("behavior_known", "mean"))
    known = d[d["behavior_known"]]
    mode = known.groupby(["cow_id", "ts_utc"])["behavior"].agg(lambda s: s.value_counts().idxmax()).rename("behavior_mode")
    lying = known.groupby(["cow_id", "ts_utc"])["behavior"].agg(lambda s: (s == 7).mean()).rename("behavior_lying_frac")
    out = cov.join(mode).join(lying).reset_index()
    out["behavior_mode"] = out["behavior_mode"].astype("Int8")
    out["behavior_mode_name"] = out["behavior_mode"].map(BEHAVIOR_NAMES).astype("string")
    return out


def build(interim: Path, tz: str = "America/Chicago") -> tuple[pd.DataFrame, dict]:
    report: dict = {"stage": "join", "cadence": CADENCE, "sources": {}}
    cbt, ankle, uwb = _read(interim, "cbt"), _read(interim, "ankle"), _read(interim, "uwb")
    thi, weather, milk, collar = _read(interim, "thi"), _read(interim, "weather"), _read(interim, "milk"), _read(interim, "collar_1min")
    beh = _read(interim, "behavior")

    per_cow = [t for t in (cbt, ankle, uwb, collar) if t is not None and len(t)]
    if not per_cow:
        raise FileNotFoundError(f"no per-cow interim tables in {interim}; run ingest first")
    cows = sorted(set().union(*(set(t["cow_id"]) for t in per_cow)))
    start = min(t["ts_utc"].min() for t in per_cow)
    end = max(t["ts_utc"].max() for t in per_cow)
    grid = minute_grid(cows, start, end)
    report["cows"], report["span_utc"] = cows, [str(start), str(end)]

    if cbt is not None:
        grid = grid.merge(to_minute(cbt, ["cow_id"], {"cbt_c": "mean"}), on=["cow_id", "ts_utc"], how="left")
    if ankle is not None:
        a = to_minute(ankle.assign(lying=ankle["lying"].astype(float)), ["cow_id"], {"lying": "mean"})
        grid = grid.merge(a, on=["cow_id", "ts_utc"], how="left")
    if uwb is not None:
        # suspect samples are excluded from the minute mean, counted as a fraction
        clean = uwb.copy()
        clean.loc[clean["uwb_suspect"], ["uwb_x_m", "uwb_y_m", "uwb_z_m"]] = np.nan
        u = to_minute(clean, ["cow_id"], {"uwb_x_m": "mean", "uwb_y_m": "mean", "uwb_z_m": "mean",
                                           "out_of_pen": "any", "uwb_suspect": "mean"})
        u = u.rename(columns={"uwb_suspect": "uwb_suspect_frac"})
        grid = grid.merge(u, on=["cow_id", "ts_utc"], how="left")
        grid["out_of_pen"] = grid["out_of_pen"].fillna(False).astype(bool)
    if collar is not None:
        grid = grid.merge(collar, on=["cow_id", "ts_utc"], how="left")
    if beh is not None:
        # labels exist for all 16 cows but the grid is the 10 sensored cows; the
        # rest stay in interim/behavior for anyone working on the full herd
        grid = grid.merge(behavior_minute(beh[beh["cow_id"].isin(cows)]), on=["cow_id", "ts_utc"], how="left")

    minutes = grid[["ts_utc"]].drop_duplicates().sort_values("ts_utc")
    if thi is not None:
        avg = thi[thi["sensor_id"] == "avg"]
        barn = attach_slow(minutes, to_minute(avg, [], {"indoor_temp_c": "mean", "indoor_rh_pct": "mean", "indoor_thi": "mean"}),
                           ["indoor_temp_c", "indoor_rh_pct", "indoor_thi"], STALE_AFTER_S["thi"])
        grid = grid.merge(barn, on="ts_utc", how="left")
    if weather is not None:
        wcols = [c for c in weather.columns if c.startswith("outdoor_") and c != "outdoor_wind_dir"]
        w = attach_slow(minutes, weather[["ts_utc"] + wcols], wcols, STALE_AFTER_S["weather"])
        grid = grid.merge(w, on="ts_utc", how="left")
    if milk is not None:
        grid = attach_daily_milk(grid, milk, tz)

    grid = grid.sort_values(["cow_id", "ts_utc"]).reset_index(drop=True)
    for t, name in ((cbt, "cbt"), (ankle, "ankle"), (uwb, "uwb"), (thi, "thi"), (weather, "weather"), (milk, "milk"), (collar, "collar_1min"), (beh, "behavior")):
        report["sources"][name] = None if t is None else int(len(t))
    report["rows"] = int(len(grid))
    report["imputed_counts"] = {c: int(grid[c].sum()) for c in grid.columns if c.endswith("_is_imputed")}
    report["null_counts"] = {c: int(grid[c].isna().sum()) for c in grid.columns if not c.endswith(("_is_imputed", "_age_s"))}
    return grid, report


def run(interim: Path, processed: Path) -> dict:
    grid, report = build(interim)
    for c in grid.columns:  # provenance columns inherit units
        if c.endswith("_age_s"):
            UNITS.setdefault(c, "s since last real observation")
        elif c.endswith("_is_imputed"):
            UNITS.setdefault(c, "bool")
    write_table(grid, processed, f"joined_{CADENCE}", CADENCE, ["cow_id", "ts_utc"],
                {"stale_after_s": STALE_AFTER_S, "note": "fast channels aggregated, slow channels forward-filled and flagged; "
                 "per-cow channels never forward-filled, so nothing is filled across out_of_pen"})
    (processed / f"joined_{CADENCE}.report.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    return report
