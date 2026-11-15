"""Where the processed tables are.

One resolver so every consumer looks in the same place. Each folder otherwise
hardcodes its own relative path, they drift, and a consumer silently falls
back to fixtures because it guessed wrong about how deep it was nested.

    from cleaning.locate import find_joined

    path = find_joined()
    df = pd.read_parquet(path) if path else my_fixtures()

Resolution order:
  1. $MMCOWS_JOINED, if set -- a full path to the parquet, or a directory
     holding it. Set this to point at a slice produced by `cleaning export`.
  2. backend-cleaning/data/processed/joined_1min.parquet, found by walking up
     from this file, so it works regardless of the caller's cwd.

Returns None when nothing is there: absence is normal (the raw data is 11 GB
and never committed), so consumers degrade to fixtures rather than crash.
"""

from __future__ import annotations

import os
from pathlib import Path

JOINED_NAME = "joined_1min.parquet"
ENV_VAR = "MMCOWS_JOINED"

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
INTERIM_DIR = Path(__file__).resolve().parents[1] / "data" / "interim"


def find_joined() -> Path | None:
    """Absolute path to the joined table, or None if it has not been built."""
    env = os.environ.get(ENV_VAR)
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            p = p / JOINED_NAME
        return p.resolve() if p.is_file() else None
    p = PROCESSED_DIR / JOINED_NAME
    return p if p.is_file() else None


def find_interim(table: str) -> Path | None:
    """Absolute path to an interim table by name (no extension), or None.

    `behavior`, `uwb_unmapped` and `collar_unmapped` live here -- the ground
    truth and the data-scarce fixture are not on the joined cow grid.
    """
    p = INTERIM_DIR / f"{table}.parquet"
    return p if p.is_file() else None


def sidecar_for(path: Path) -> Path | None:
    """The .schema.json beside a table: cadence, units, per-column null counts.

    Read the cadence from here rather than parsing it out of the filename.
    """
    p = path.with_name(path.stem + ".schema.json")
    return p if p.is_file() else None
