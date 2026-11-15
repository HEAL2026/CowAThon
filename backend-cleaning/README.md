# Backend: Data Cleaning

Owns ingestion, validation, normalization, missing-value handling, and
export of analysis-ready datasets.

Document input/output schemas and make cleaning steps reproducible.

## Contract

[`CONTRACT.md`](CONTRACT.md) is the I/O contract that `backend-analysis/` and
`backend-visualization/` code against: directory layout, the `cow_id` / `ts_utc`
keys, the missing-data policy, and units. Changes there get announced on the
board before they land.

Column-level schema is marked PENDING until the team picks a Challenge.

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

Tests: `cd backend-cleaning && python3 tests/test_splits.py`
