"""Build or slice the cleaned dataset.

    python3 -m cleaning                       raw -> interim -> processed
    python3 -m cleaning --skip-heavy          without the 10 Hz collar aggregate
    python3 -m cleaning export --cows C01,C02 --days 2 --out slice.parquet

`build` is the default when no subcommand is given, so the original
`python3 -m cleaning [--skip-heavy]` invocation keeps working.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import bouts, derive, export, ingest, join, synth
from .ingest import write_table
from .locate import find_joined

HERE = Path(__file__).resolve().parents[1]
SUBCOMMANDS = ("build", "export", "where")


def _build(a: argparse.Namespace) -> int:
    if not a.join_only:
        r = ingest.run(a.raw, a.interim, skip_heavy=a.skip_heavy)
        print(json.dumps(r, indent=2, sort_keys=True))
    r = join.run(a.interim, a.processed)
    print(json.dumps({k: r[k] for k in ("rows", "cows", "span_utc", "imputed_counts")}, indent=2, default=str))
    print(f"-> {a.processed / 'joined_1min.parquet'}")
    _derived(a.interim, a.processed)
    return 0


def _config() -> dict:
    import yaml
    return yaml.safe_load((Path(__file__).with_name("config.yaml")).read_text())


def _derived(interim: Path, processed: Path) -> None:
    """Brief S3 outputs built from the joined table and the event log:
    lying_bouts, location_1min, gap marks on joined_1min, manual, mastitis_events."""
    import pandas as pd
    cfg = _config()
    joined_path = processed / "joined_1min.parquet"
    joined = pd.read_parquet(joined_path)

    # gap marks on the per-cow native channels: mark, never fill
    gap_cols = {"cbt_c": 1, "lying": 1, "uwb_x_m": 1, "neck_imu_magnitude_mean": 1}
    marked = bouts.mark_gaps(joined, gap_cols, mark_after_min=cfg["gaps"]["mark_after_min"])
    for c in gap_cols:
        ingest.UNITS.setdefault(f"{c}_gap_min", "minutes of missing run, 0 if <= threshold")
    marked["in_pen"] = ~marked["out_of_pen"].astype(bool)
    ingest.UNITS.setdefault("in_pen", "bool")
    sidecar = json.loads((processed / "joined_1min.schema.json").read_text())
    notes = {k: v for k, v in sidecar.items() if k not in ("table", "cadence", "keys", "rows", "columns")}
    notes["gap_mark_after_min"] = cfg["gaps"]["mark_after_min"]
    write_table(marked, processed, "joined_1min", "1min", ["cow_id", "ts_utc"], notes)

    lb = bouts.lying_bouts(marked, min_duration_min=cfg["lying_bouts"]["min_duration_min"])
    for c, u in (("start_utc", "UTC"), ("end_utc", "UTC, exclusive"), ("duration_min", "min"), ("x_m", "m"), ("y_m", "m"), ("z_m", "m"),
                 ("n_fixes", "in-pen UWB fixes"), ("in_pen_frac", "fraction")):
        ingest.UNITS.setdefault(c, u)
    write_table(lb, processed, "lying_bouts", "event", ["cow_id", "start_utc"],
                {"min_duration_min": cfg["lying_bouts"]["min_duration_min"],
                 "resting_min_duration_min": cfg["lying_bouts"]["resting_min_duration_min"],
                 "note": "continuous lying >= min_duration; location = median of in-pen, in-bounds UWB fixes during the bout"})
    print(f"-> {processed / 'lying_bouts.parquet'}  ({len(lb)} bouts)")

    uwb = pd.read_parquet(interim / "uwb.parquet")
    loc = bouts.location_1min_median(uwb)
    for c in ("x_med_m", "y_med_m", "z_med_m"):
        ingest.UNITS.setdefault(c, "m")
    write_table(loc, processed, "location_1min", "1min", ["cow_id", "ts_utc"],
                {"note": "per-minute median of in-pen, in-bounds fixes; joined_1min carries the mean"})

    hr_path = interim / "health_records.parquet"
    if hr_path.exists():
        hr = pd.read_parquet(hr_path)
        milk = pd.read_parquet(interim / "milk.parquet") if (interim / "milk.parquet").exists() else None
        man = derive.manual_from_health_records(hr, milk=milk)
        for c in man.columns:
            ingest.UNITS.setdefault(c, "")
        write_table(man, processed, "manual", "snapshot", ["cow_id"],
                    {"note": "parity / DIM / pregnancy derived from the real farm event log as of the first sensor row; "
                             "not farmer-entered, so source says derived_from_health_records"})
        me = derive.mastitis_events(hr)
        for c in me.columns:
            ingest.UNITS.setdefault(c, "")
        write_table(me, processed, "mastitis_events", "event", ["cow_id", "ts_utc"],
                    {"note": "real clinical-mastitis diagnoses / cultures / withholds from the farm log; anchors for validation, not labels",
                     "in_sensor_window": int(me["in_sensor_window"].sum())})
        print(f"-> {processed / 'manual.parquet'}  ({len(man)} cows)   mastitis_events: {len(me)} rows, {int(me['in_sensor_window'].sum())} inside the sensor window")


def _export(a: argparse.Namespace) -> int:
    cows = [c.strip() for c in a.cows.split(",") if c.strip()] if a.cows else None
    meta = export.run(a.out, cows=cows, days=a.days, source=a.source, fmt=a.format)
    print(json.dumps({k: meta[k] for k in ("rows", "cows", "span_utc")}, indent=2))
    print(f"-> {a.out}  (+ {a.out.with_name(a.out.stem + '.meta.json').name})")
    return 0


def _synth(a: argparse.Namespace) -> int:
    summary = synth.run(a.processed, a.interim, a.out, seed=a.seed)
    print(json.dumps(summary, indent=2, default=str))
    print(f"-> {a.out}")
    return 0


def _where(_: argparse.Namespace) -> int:
    """Print what a consumer would resolve, so a fixture fallback is debuggable."""
    p = find_joined()
    print(p if p else "joined_1min.parquet not found -- build it, or set $MMCOWS_JOINED")
    return 0 if p else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv.insert(0, "build")  # keep the bare `python3 -m cleaning` behaviour

    ap = argparse.ArgumentParser(prog="cleaning")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="raw -> interim -> processed")
    b.add_argument("--raw", type=Path, default=HERE / "data" / "raw" / "sensor_data" / "main_data")
    b.add_argument("--interim", type=Path, default=HERE / "data" / "interim")
    b.add_argument("--processed", type=Path, default=HERE / "data" / "processed")
    b.add_argument("--skip-heavy", action="store_true", help="skip immu/pressure -> collar_1min")
    b.add_argument("--join-only", action="store_true", help="reuse existing interim tables")
    b.set_defaults(fn=_build)

    e = sub.add_parser("export", help="slice the joined table for a demo or to share")
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--cows", help="comma-separated cow_ids, e.g. C01,C02 (default: all)")
    e.add_argument("--days", type=int, help="whole local days from the start of the span (default: all)")
    e.add_argument("--source", type=Path, help="joined table to slice (default: resolved via $MMCOWS_JOINED)")
    e.add_argument("--format", choices=("parquet", "csv"), default="parquet")
    e.set_defaults(fn=_export)

    sy = sub.add_parser("synth", help="S0b: seeded synthetic milking log / sanitation / cases / outbreak scenarios")
    sy.add_argument("--processed", type=Path, default=HERE / "data" / "processed")
    sy.add_argument("--interim", type=Path, default=HERE / "data" / "interim")
    sy.add_argument("--out", type=Path, default=HERE / "data" / "synthetic")
    sy.add_argument("--seed", type=int, default=0)
    sy.set_defaults(fn=_synth)

    w = sub.add_parser("where", help="print the joined table a consumer would resolve")
    w.set_defaults(fn=_where)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
