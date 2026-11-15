"""Run the whole pipeline:  python3 -m cleaning [--skip-heavy] [--raw DIR]

raw -> interim -> processed, reproducibly. --skip-heavy leaves out the 10 Hz
immu/pressure aggregate (minutes of IO) so the tabular core can be rebuilt fast.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import ingest, join

HERE = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(prog="cleaning")
    ap.add_argument("--raw", type=Path, default=HERE / "data" / "raw" / "sensor_data" / "main_data")
    ap.add_argument("--interim", type=Path, default=HERE / "data" / "interim")
    ap.add_argument("--processed", type=Path, default=HERE / "data" / "processed")
    ap.add_argument("--skip-heavy", action="store_true", help="skip immu/pressure -> collar_1min")
    ap.add_argument("--join-only", action="store_true", help="reuse existing interim tables")
    a = ap.parse_args()

    if not a.join_only:
        r = ingest.run(a.raw, a.interim, skip_heavy=a.skip_heavy)
        print(json.dumps(r, indent=2, sort_keys=True))
    r = join.run(a.interim, a.processed)
    print(json.dumps({k: r[k] for k in ("rows", "cows", "span_utc", "imputed_counts")}, indent=2, default=str))
    print(f"-> {a.processed / 'joined_1min.parquet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
