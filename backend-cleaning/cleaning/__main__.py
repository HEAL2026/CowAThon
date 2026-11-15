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

from . import export, ingest, join
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
    return 0


def _export(a: argparse.Namespace) -> int:
    cows = [c.strip() for c in a.cows.split(",") if c.strip()] if a.cows else None
    meta = export.run(a.out, cows=cows, days=a.days, source=a.source, fmt=a.format)
    print(json.dumps({k: meta[k] for k in ("rows", "cows", "span_utc")}, indent=2))
    print(f"-> {a.out}  (+ {a.out.with_name(a.out.stem + '.meta.json').name})")
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

    w = sub.add_parser("where", help="print the joined table a consumer would resolve")
    w.set_defaults(fn=_where)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
