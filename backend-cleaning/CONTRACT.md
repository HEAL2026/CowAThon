# backend-cleaning: I/O contract

Owner: @hazelLu6. This is the contract `backend-analysis/` and
`backend-visualization/` code against. If something here changes, it gets
announced on the board (issue #1) before it lands.

Status: **column-level schema is PENDING the team's Challenge choice.**
Everything in sections 1-4 is mandated by the track prompt for both
Challenge 1 (MMCows) and Challenge 2 (Mendeley THI tabular), so it is
settled and safe to build against now.

## 1. Directory layout

```
backend-cleaning/
  data/
    raw/        # exactly as downloaded. never written to, never edited.
    interim/    # per-modality, parsed and time-normalized, not yet joined
    processed/  # analysis-ready tables + schema sidecars
```

`data/` is gitignored. Raw data is never committed and never redistributed
outside the permissions attached to the Challenge — the prompt is explicit
about that.

Cleaning is a one-way function `raw -> interim -> processed`. Re-running it on
the same raw input reproduces the same processed output byte-for-byte: fixed
seeds, sorted inputs, no wall-clock or filesystem-order dependence.

## 2. Grouping key and leakage-safe splits

Both datasets contain **many observations per animal**. A random row-level
train/test split therefore leaks: the same cow appears on both sides, and
reported accuracy is inflated by animal identity rather than earned by the
model. The prompt requires the split to avoid exactly this.

Every processed table carries:

| Column | Type | Meaning |
|---|---|---|
| `cow_id` | string (categorical) | stable animal identifier; the grouping unit |
| `ts_utc` | timestamp, UTC, tz-aware | canonical observation time |

Rules for consumers:

- **Never split on rows. Split on `cow_id`.** All records for one cow land
  wholly in train or wholly in test.
- For anything temporal, split on time as well and never train on a window
  that post-dates the evaluation window.
- `cow_id` is an identifier, not a feature. Do not feed it to a model as a
  predictor; use it for grouping, and for the by-animal error reporting the
  prompt asks for.

A single helper owns this so the four roles cannot disagree about it:

```python
from cleaning.splits import group_split      # signature is stable
train_df, test_df = group_split(df, by="cow_id", test_frac=0.25, seed=0)
```

## 3. Missing data

The prompt requires documented missing-data handling and asks how the
prototype behaves when evidence is weak or modalities are absent. Policy:

- **No silent imputation.** Nothing is filled without it being recorded.
- Missingness is preserved, not erased: for any column `x` that gets filled,
  processed output also carries boolean `x_is_imputed`.
- Rows are dropped only for a missing *key* (`cow_id` or `ts_utc`), never for
  a missing feature. Dropped-row counts go in the run report.
- Each processed table ships a sidecar `<table>.schema.json` with per-column
  dtype, units, null count, and imputation method. Analysis and visualization
  should validate against the sidecar rather than assuming a column exists.

## 4. Units and conventions

- Timestamps UTC and tz-aware. Local barn time is derived downstream, never
  stored as a naive local timestamp.
- Temperatures degrees Celsius. One unit per column, stated in the sidecar.
- THI is a **derived** column, computed in cleaning from ambient temperature
  and relative humidity, with the formula recorded in the sidecar so analysis
  is not re-deriving it differently.
- Column names `snake_case`. No spaces, no units embedded in names.

## 5. PENDING: challenge-specific schema

Filled in once the team picks a Challenge. The two differ enough that writing
both now would mean publishing a contract teammates build against and then
throwing half of it away.

- **If Challenge 1 (MMCows):** per-modality interim tables (multi-view RGB
  frame index, UWB location, neck IMU/magnetometer, ambient pressure, core
  body temperature, ankle sensor, indoor temp/humidity/THI, outdoor weather,
  daily milk yield), joined to a single resampled cadence. The open question
  is the join cadence, since the modalities are sampled at very different
  rates and image volume dominates ingestion cost.
- **If Challenge 2 (Mendeley THI):** one tabular table keyed
  `cow_id x THI condition x repeat`, carrying genetic group, rectal
  temperature, respiration rate, pulse rate, dry matter intake, milk yield
  and composition, and blood metabolites. Repeated measures within a THI
  category make `group_split` mandatory, not optional.
