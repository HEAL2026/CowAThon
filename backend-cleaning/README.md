# Backend: Data Cleaning

Owns ingestion, validation, normalization, missing-value handling, and
export of analysis-ready datasets.

Document input/output schemas and make cleaning steps reproducible.

## Contract

[`CONTRACT.md`](CONTRACT.md) is the I/O contract that `backend-analysis/` and
`backend-visualization/` code against: directory layout, the `cow_id` / `ts_utc`
keys, the missing-data policy, and units. Changes there get announced on the
board before they land.

Column-level schema for Challenge 1 (MMCows) is in CONTRACT.md §5.

How the three stages work and why, written for the presentation:
[`PIPELINE.md`](PIPELINE.md).

## Running it

```bash
cd backend-cleaning
python3 -m pip install -r requirements.txt

# 1. raw data (CC BY-NC-SA, never committed): only the sections we use,
#    range-read out of the official 18 GB HuggingFace zip, resumable
python3 scripts/fetch_mmcows.py                  # ~11.7 GB; RGB excluded

# 2. raw -> interim -> processed
python3 -m cleaning --skip-heavy                 # tabular core, ~6 s
python3 -m cleaning                              # + 10 Hz immu/pressure -> collar_1min
```

### Synthetic layer (brief S0b)

```bash
python3 -m cleaning synth --seed 0        # -> data/synthetic/ (gitignored), all is_synthetic=true
```

One seeded world over the 14 real days: `milking_log` (unit + order synthetic,
visit time from each cow's real UWB milking trip), `sanitation` (one skipped
on purpose), `bedding_synthetic` (placeholder until Aster's), `milk_visits_synthetic`
(per‑quarter conductivity, SCC, yield — Aster's shape), `daily_perturbations`
(multipliers analysis applies to its own daily features for case cows), and
`synthetic_labels` (ground truth: case cows, onset, dx, `true_route`,
`true_source`). Three disjoint episodes: resting‑route (days 1–5, built from
where cows really lay), milking‑route (days 6–10), sporadic (days 11–14).
Signature ranges and their sources are in `cleaning/synth.py`.

### Reading it from another folder

Do not hardcode a relative path to the parquet — folders are nested
differently and a wrong guess looks like "no data" rather than an error:

```python
from cleaning.locate import find_joined          # also: find_interim, sidecar_for
import pandas as pd

path = find_joined()                              # None when it has not been built
df = pd.read_parquet(path) if path else my_fixtures()
is_synthetic = path is None
```

`find_joined()` honours `$MMCOWS_JOINED` (a parquet, or a directory holding
one) so a consumer can be pointed at an exported slice. `python3 -m cleaning
where` prints what it resolves, which is the quickest way to find out why a
consumer fell back to fixtures.

### Optional external milk example

For testing milk/physiology features under heat stress, users may download the
CC BY 4.0 Mendeley Data release [954f6g36sb/2](https://data.mendeley.com/datasets/954f6g36sb/2)
(`10.17632/954f6g36sb.2`) and normalize a CSV or parquet file without adding
the source data to this repository:

```python
from cleaning.optional_milk import load_optional_milk, optional_milk_metadata

milk = load_optional_milk("/path/to/downloaded/milk.csv")
print(optional_milk_metadata())
```

The adapter exposes `cow_id`, `ts_utc`, `milk_yield_kg`, milk composition,
`scc`, `respiration_rate_bpm`, `pulse_rate_bpm`, `rectal_temp_c`, `dmi_kg`,
and `thi_category` when present. It does not map the external animal
IDs to MMCows IDs or concatenate cohorts automatically; callers must provide
an explicit mapping and date alignment before using these rows in evaluation.
The health pipeline remains valid with no optional file: missing milk features
stay missing and the existing MMCows-only evaluation is unchanged.

### Sharing a slice

The raw data is 11 GB under CC BY-NC-SA and the track prompt forbids
redistributing source data, so what travels is a derived slice:

```bash
python3 -m cleaning export --cows C01,C02 --days 2 --out /tmp/demo.parquet
# -> demo.parquet + demo.meta.json (provenance, span, columns, source sidecar)
```

`--days` counts whole local days from the start of the span, so a slice never
ends mid-milking-cycle. 2 cows x 2 days is ~4k rows / 300 KB.

### Derived tables (brief S3)

`python3 -m cleaning` also writes, next to `joined_1min`:

| table | what |
|---|---|
| `lying_bouts` | continuous lying ≥ 5 min, median in‑pen location per bout — input to resting‑route tracing |
| `location_1min` | per‑minute median position (joined carries the mean) |
| `manual` | parity / DIM / pregnancy per cow, **derived from the real farm event log**, cross‑checked against the farm's DIM counter |
| `mastitis_events` | real clinical‑mastitis diagnoses, cultures, withholds (57 rows, none inside the sensor window) — validation anchors, never labels |
| `health_records` (interim) | the full event log, 3,503 rows, 16 cows |

`joined_1min` gains `in_pen` and `<col>_gap_min` (missing runs > 5 min, marked
never filled). Thresholds live in `cleaning/config.yaml`.

Outputs: `data/interim/<table>.parquet` at native rate with a
`<table>.schema.json` sidecar each, `data/interim/ingest.report.json`
(dropped-key counts), and `data/processed/joined_1min.parquet` with its
sidecar and `joined_1min.report.json` (imputation and null counts per column).
Reruns on the same raw input are byte-identical.

Layout: `cleaning/ingest.py` (per-section shaping, pure functions + IO
wrappers), `cleaning/join.py` (minute grid, slow-channel forward-fill with
`_is_imputed` / `_age_s`), `cleaning/splits.py` (leakage-safe splits).

### Leakage-safe splits

Both Challenge datasets hold many rows per animal, so a row-level random split
leaks. Always split on whole animals:

```python
from cleaning.splits import group_split, group_kfold, assert_no_group_leakage

train, test = group_split(df, by="cow_id", test_frac=0.25, seed=0)
assert_no_group_leakage(train, test)   # cheap, call it before training

# cross-validation: list of (train, val), every cow held out exactly once
folds = group_kfold(df, by="cow_id", n_splits=5, seed=0)
```

Tests: `cd backend-cleaning && for t in tests/test_*.py; do python3 $t; done`
