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

Tests: `cd backend-cleaning && python3 tests/test_splits.py && python3 tests/test_ingest.py`
