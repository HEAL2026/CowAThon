"""Optional external milk/physiology source adapter.

The Mendeley dataset is a testing and calibration example, not an MMCows
replacement. Its cow identifiers and sampling design must not be joined to
MMCows implicitly. Callers provide an explicit ``cow_id`` mapping when they
want to evaluate the optional features with another dataset.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pandas as pd

MENDELEY_URL = "https://data.mendeley.com/datasets/954f6g36sb/2"
MENDELEY_DOI = "10.17632/954f6g36sb.2"
MENDELEY_LICENSE = "CC BY 4.0"

_ALIASES = {
    "cow_id": ("cow_id", "cow", "cow_no", "cow_number", "animal_id", "animal"),
    "date": ("date", "sampling_date", "sample_date", "measurement_date"),
    "milk_yield_kg": (
        "milk_yield_kg", "milk_yield", "milk_production", "daily_milk_yield",
        "milk_ yield", "milk yield",
    ),
    "milk_fat_pct": ("milk_fat_pct", "fat_pct", "fat", "milk_fat"),
    "milk_protein_pct": ("milk_protein_pct", "protein_pct", "protein", "milk_protein"),
    "milk_lactose_pct": ("milk_lactose_pct", "lactose_pct", "lactose", "milk_lactose"),
    "scc": ("scc", "somatic_cell_count", "somatic_cell"),
    "thi_category": ("thi_category", "thi", "thi_group", "heat_stress"),
    "respiration_rate_bpm": ("respiration_rate_bpm", "respiration_rate", "respiration"),
    "pulse_rate_bpm": ("pulse_rate_bpm", "pulse_rate", "pulse"),
    "rectal_temp_c": ("rectal_temp_c", "rectal_temperature_c", "rectal_temperature"),
    "dmi_kg": ("dmi_kg", "dry_matter_intake", "dmi"),
}


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _column_map(columns: list[object]) -> dict[str, str]:
    normalized = {_key(c): str(c) for c in columns}
    result: dict[str, str] = {}
    for target, aliases in _ALIASES.items():
        for alias in aliases:
            source = normalized.get(_key(alias))
            if source is not None:
                result[target] = source
                break
    return result


def normalize_optional_milk(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize an externally downloaded milk table without fabricating IDs.

    Required fields are an animal identifier and a sampling date. The result
    uses the same optional feature names consumed by cow-day aggregation.
    No rows are dropped for missing measurements; only missing grouping keys
    are rejected.
    """
    if not isinstance(raw, pd.DataFrame):
        raise TypeError("raw optional milk data must be a pandas DataFrame")
    if raw.empty:
        return pd.DataFrame(columns=["cow_id", "ts_utc", "milk_yield_kg", "is_synthetic"])

    mapping = _column_map(list(raw.columns))
    missing = [name for name in ("cow_id", "date") if name not in mapping]
    if missing:
        raise ValueError(
            "optional milk data requires columns for " + ", ".join(missing)
            + "; provide an explicit pre-normalization step for this source"
        )

    out = pd.DataFrame(index=raw.index)
    out["cow_id"] = raw[mapping["cow_id"]].astype("string").str.strip()
    out["ts_utc"] = pd.to_datetime(raw[mapping["date"]], utc=True, errors="coerce")
    for target in (
        "milk_yield_kg", "milk_fat_pct", "milk_protein_pct",
        "milk_lactose_pct", "scc", "respiration_rate_bpm",
        "pulse_rate_bpm", "rectal_temp_c", "dmi_kg",
    ):
        if target in mapping:
            out[target] = pd.to_numeric(raw[mapping[target]], errors="coerce")
    if "thi_category" in mapping:
        out["thi_category"] = raw[mapping["thi_category"]].astype("string")

    out = out.dropna(subset=["cow_id", "ts_utc"]).copy()
    out["source_dataset"] = MENDELEY_DOI
    out["is_synthetic"] = False
    return out.sort_values(["cow_id", "ts_utc"]).reset_index(drop=True)


def load_optional_milk(path: str | Path) -> pd.DataFrame:
    """Load CSV or parquet supplied by a user, or raise a useful error."""
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"optional milk file does not exist: {source}")
    if source.suffix.lower() == ".csv":
        raw = pd.read_csv(source)
    elif source.suffix.lower() in {".parquet", ".pq"}:
        raw = pd.read_parquet(source)
    else:
        raise ValueError("optional milk file must be CSV or parquet")
    return normalize_optional_milk(raw)


def optional_milk_metadata() -> dict[str, Any]:
    """Return citation/provenance metadata without downloading the source."""
    return {
        "name": "Physiological responses, Dry matter Intake, milk yield, composition and blood metabolites of HF Cross cows",
        "url": MENDELEY_URL,
        "doi": MENDELEY_DOI,
        "license": MENDELEY_LICENSE,
        "role": "optional testing/calibration source; not an MMCows evaluation split",
        "join_policy": "explicit cow_id mapping and timestamp/date alignment required",
    }
