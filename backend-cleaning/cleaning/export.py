"""Slice the joined table for sharing or for a demo.

The full table is 198k rows over 14 days and the raw data behind it is 11 GB
under CC BY-NC-SA, which the track prompt says we do not redistribute. A
derived slice, clearly labelled as derived, is what travels.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .locate import find_joined, sidecar_for


def slice_joined(df: pd.DataFrame, cows: list[str] | None = None, days: int | None = None,
                 start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
                 tz: str = "America/Chicago") -> pd.DataFrame:
    """Subset by cow and/or time window. Whole days, counted from the start of
    the first local day present, so a slice is never half a milking cycle."""
    out = df
    if cows:
        missing = sorted(set(cows) - set(out["cow_id"].unique()))
        if missing:
            raise ValueError(f"no such cow_id in the table: {missing}")
        out = out[out["cow_id"].isin(cows)]
    if start is not None:
        out = out[out["ts_utc"] >= start]
    if end is not None:
        out = out[out["ts_utc"] <= end]
    if days is not None:
        if days < 1:
            raise ValueError(f"days must be >= 1, got {days}")
        local = out["ts_utc"].dt.tz_convert(tz)
        first_day = local.min().normalize()
        cutoff = first_day + pd.Timedelta(days=days)
        out = out[local < cutoff]
    return out.reset_index(drop=True)


def run(out_path: Path, cows: list[str] | None = None, days: int | None = None,
        source: Path | None = None, fmt: str = "parquet") -> dict:
    src = source or find_joined()
    if src is None:
        raise FileNotFoundError(
            "joined_1min.parquet not found. Build it with `python3 -m cleaning`, "
            "or point $MMCOWS_JOINED at an existing copy."
        )
    df = pd.read_parquet(src)
    sliced = slice_joined(df, cows=cows, days=days)
    if sliced.empty:
        raise ValueError("slice is empty; check --cows / --days against the table's span")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        sliced.to_csv(out_path, index=False)
    else:
        sliced.to_parquet(out_path, index=False)

    meta = {
        "derived_from": "MMCows (neis-lab/mmcows), CC BY-NC-SA 4.0 -- derived aggregate, not source data",
        "produced_by": "backend-cleaning/cleaning/export.py",
        "source_table": src.name, "cadence": "1min",
        "keys": ["cow_id", "ts_utc"],
        "rows": int(len(sliced)), "cows": sorted(sliced["cow_id"].unique()),
        "span_utc": [str(sliced["ts_utc"].min()), str(sliced["ts_utc"].max())],
        "columns": list(sliced.columns),
    }
    side = sidecar_for(src)
    if side is not None:
        meta["source_sidecar"] = json.loads(side.read_text())
    out_path.with_name(out_path.stem + ".meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta
