# backend-cleaning: I/O contract

Owner: @hazelLu6 — of `backend-cleaning/` only. This document describes what
this folder *produces*, so that consumers have something stable to read
against. It claims no ownership over the folders that consume it;
`backend-analysis/`, `backend-visualization/`, and `frontend/` are owned by
@equan04, @pauraque, and @uiobio respectively and they decide how their own
code uses this output. If something here changes, it gets announced on the
board (issue #1) before it lands.

Status: **Challenge 1 (MMCows) is the team's Challenge** — called by the lead
on 2026-11-13. Dataset: <https://huggingface.co/datasets/neis-lab/mmcows>.
Sections 1-4 are the invariants; section 5 is the Challenge 1 schema.

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

A single helper owns this so the roles cannot disagree about it:

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

## 5. Challenge 1 schema (MMCows)

14 days of synchronized dairy-cow data. The modalities are sampled at wildly
different rates, so cleaning produces **one interim table per modality** at
its native rate, then **one joined table** at a single declared cadence.

### 5.1 Interim tables, native rate

One table per modality in `data/interim/`, each keyed `cow_id` + `ts_utc`,
each with its own schema sidecar:

| Table | Holds |
|---|---|
| `frames` | multi-view RGB **index** — one row per (view, timestamp), with a relative path into `data/raw/`. Never the pixels. |
| `uwb` | UWB location: `x_m`, `y_m`, plus whatever quality flag the source carries |
| `neck_imu` | neck-mounted inertial + magnetic channels |
| `pressure` | ambient pressure |
| `cbt` | core body temperature |
| `ankle` | ankle sensing |
| `indoor_env` | indoor temperature, relative humidity, `thi` |
| `outdoor_env` | outdoor weather |
| `milk_yield` | daily milk yield, one row per cow-day |

`frames` carries a path, not image bytes. Image volume dominates ingestion
cost, so nothing downstream re-decodes frames it does not need — `model/`
reads bytes lazily from the path.

### 5.2 Joined table and the cadence question

`data/processed/joined_<cadence>.parquet`, keyed `cow_id` + `ts_utc`, with
the cadence written into both the filename and the sidecar so nobody has to
guess what a row means.

**Open decision, and it is mine to make — I will post it before it lands:**
the join cadence. Milk yield is daily while IMU is sub-second, so any single
cadence either forward-fills slow channels or aggregates fast ones. Starting
point is **1 minute**, with fast channels aggregated (mean/min/max/std per
window) and slow channels forward-filled with `*_is_imputed` set, since the
prompt's heat-load and behavior questions live at minutes, not milliseconds.

Consumers should read the cadence from the sidecar rather than hardcoding it.

### 5.3 What each consumer can rely on

Not instructions — availability. Each owner decides how their folder uses
this; these are the guarantees they can count on, and the gotchas worth
knowing about.

- **For `model/`** — `frames` gives the frame index; the sensor tables join to
  it on `cow_id` + `ts_utc` for labels and context.
- **For `backend-analysis/`** — `joined_<cadence>` is the analysis-ready
  table. `assert_no_group_leakage` is available if you want a cheap guard
  before training.
- **For `backend-visualization/`** — `joined_<cadence>` plus the daily
  `milk_yield` table. Worth knowing: a modality can be legitimately absent
  for a given cow-window, so the sidecar is the reliable source of what
  exists in a given run.
- **For `frontend/`** — nothing here is a direct dependency; the data path
  runs through `backend-visualization/`.

Requests for a different shape, extra columns, or another cadence are welcome
on the board — that is a cleaning change and I will make it.
