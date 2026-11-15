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
from cleaning.splits import group_split, group_kfold   # signatures are stable
train_df, test_df = group_split(df, by="cow_id", test_frac=0.25, seed=0)

# cross-validation: every cow held out exactly once, all its rows together.
# analysis and model call this with the same (n_splits, seed) so their
# cross-validated numbers are on identical animal folds.
for train_df, val_df in group_kfold(df, by="cow_id", n_splits=5, seed=0):
    ...
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

### 5.1 Raw layout and interim tables, native rate

Raw lives at `data/raw/sensor_data/main_data/<section>/…`, fetched by
[scripts/fetch_mmcows.py](scripts/fetch_mmcows.py) straight out of the
official HuggingFace `sensor_data.zip` (RGB excluded). Every raw file keys on
`timestamp` = Unix epoch seconds; the barn is `America/Chicago`; the span is
2023-07-21 12:30 → 2023-08-04 07:00 local. Two ID schemes: `Cxx` = cow
(C01–C16), `Txx` = collar tag; T01–T10 map one-to-one onto C01–C10. T13 and
T14 are the dataset's two **stationary reference tags** (official README), not
cows: their uwb rows are kept apart in `uwb_unmapped` (useful as a drift
check on the UWB system), their collar rows skipped and listed in
`ingest.report.json`.

One interim table per section in `data/interim/`, each keyed `cow_id`
(C-scheme string, or null for barn/outdoor tables) + `ts_utc`, each with a
`<table>.schema.json` sidecar. Raw column names are kept where they already
carry units; conversions are listed.

| Table | Rate | Cows | Columns (after cleaning) | From raw |
|---|---|---|---|---|
| `milk` | daily | C01–C16 | `milk_yield_kg`, `dim` | `milk_weight_kg`, `DIM` |
| `behavior` | 1 s | C01–C16, **2023‑07‑25 only** | `behavior` (code), `behavior_name`, `behavior_known` | `behavior_labels/individual/Cxx_0725.csv`. Ground truth. Legend (official benchmark code): 0 unknown, 1 walking, 2 standing, 3 feed_up, 4 feed_down, 5 licking, 6 drinking, 7 lying. **0 is not a class**: kept, flagged `behavior_known=False`, excluded from any mode/count. Code 7 agrees with the ankle `lying` channel 99.3 % of minutes |
| `cbt` | 1 min | C01–C10 | `cbt_c` | `temperature_C` |
| `thi` | 1 min | barn | `sensor_id` (S01–S06, `avg`), `indoor_temp_c`, `indoor_rh_pct`, `indoor_thi` | `temperature_C`, `humidity_per`, `THI`. `average.csv` is headed `temperature_F` but holds °C — cleaning verifies the unit against the file's own THI column instead of trusting the header |
| `ankle` | 1 min | C01–C10 | `lying` (0/1) | `lying`; `datetime` string dropped |
| `uwb` | 15 s | C01–C10 | `uwb_x_m`, `uwb_y_m`, `uwb_z_m`, `out_of_pen`, `uwb_suspect` | `coord_*_cm` / 100; null coords → `out_of_pen=True`, row kept. Frame is pen-centred (x ±10 m, y −8.7…5.7 m, z neck height); a reading outside x ±12, y [−9, 8], z [−0.5, 3] m is a ranging error → `uwb_suspect=True`, row kept (~0.4 %) |
| `uwb_unmapped` | 15 s | T13, T14 | as `uwb` plus `tag_id` | **data-scarce fixture** (see below) |
| `collar_unmapped` | 1 min | T13, T14 | as `collar_1min` plus `tag_id` | **data-scarce fixture** (see below) |
| `collar_1min` | 1 min | C01–C10 | `neck_imu_magnitude_mean`, `neck_imu_magnitude_std`, `neck_imu_n`, `collar_pressure_hpa`, `collar_pressure_n` | per-minute aggregate of the 10 Hz `immu` (|accel| in m/s²) and `pressure` (`pressure_Pa` / 100). The 10 Hz rows (7 + 4 GB) are **not** re-materialised; `data/raw/.../immu` and `pressure` are the native-rate source |
| `weather` | 5 min | outdoor | `outdoor_temp_c`, `outdoor_dewpoint_c`, `outdoor_rh_pct`, `outdoor_wind_dir`, `outdoor_wind_mps`, `outdoor_gust_mps`, `outdoor_pressure_hpa`, `outdoor_precip_rate_mm_h`, `outdoor_precip_mm`, `outdoor_uv`, `outdoor_solar_wm2` | `.xlsx` cells are strings with imperial units (`"60.7 °F"`, `"29.65 in"`, `"2.3 mph"`); date comes from the filename |

**T13/T14 as the data-scarce test fixture.** The two stationary reference
tags carry location and collar streams only — no CBT, no ankle, no milk, no
behaviour labels, and no motion. They are kept on purpose, apart from the
herd, so `backend-analysis/` and `model/` can test how a subject with most
modalities missing is handled: the confidence score should drop, missing
modalities should be reported rather than imputed, and a motion or behaviour
inference on a tag that never moves should read as "no activity", not as a
lying cow. Never join them onto the cow grid; they are not animals.

`out_of_pen` is a **state**, not missingness: the cows leave the pen for
milking twice a day (~04–05h and ~15–16h local) and UWB has nothing to
report. It is never forward-filled across and never counted as imputed.

### 5.2 Joined table: `joined_1min`

`data/processed/joined_1min.parquet` + `joined_1min.schema.json`. One row =
one cow × one minute, keys `cow_id` (C01–C10) + `ts_utc`. Cadence is in the
filename and the sidecar; consumers read it from the sidecar rather than
hardcoding it.

| Group | Columns | How it gets to 1 min |
|---|---|---|
| body | `cbt_c` | native |
| barn env | `indoor_temp_c`, `indoor_rh_pct`, `indoor_thi` | native (the S01–S06 average; per-sensor stays in interim) |
| outdoor | `outdoor_temp_c`, `outdoor_dewpoint_c`, `outdoor_rh_pct`, `outdoor_wind_mps`, `outdoor_gust_mps`, `outdoor_pressure_hpa`, `outdoor_precip_mm`, `outdoor_uv`, `outdoor_solar_wm2` | 5 min → forward-filled, `_is_imputed` set |
| production | `milk_yield_kg`, `dim` | daily → carried through the local day, `_is_imputed` set |
| behaviour / location | `lying`, `uwb_x_m`, `uwb_y_m`, `uwb_z_m`, `out_of_pen`, `uwb_suspect_frac` | `lying` native; uwb 15 s → 1-min mean excluding suspect samples; `out_of_pen` = any null in the minute; `uwb_suspect_frac` = share of the minute's samples that were out of bounds |
| collar | `neck_imu_magnitude_mean`, `neck_imu_magnitude_std`, `collar_pressure_hpa` | 10 Hz → per-minute |accel| mean/std, pressure mean |
| ground truth (07/25 only, else null) | `behavior_mode`, `behavior_mode_name`, `behavior_known_frac`, `behavior_lying_frac` | 1 s labels → dominant known code in the minute, share of the minute labelled at all, share of known seconds that are `lying`. Labels for C11–C16 are in interim `behavior` only (no sensors → not on the grid) |
| provenance | `<col>_is_imputed` for every filled column; `<col>_age_s` for every slow channel (seconds since the last real observation) | — |

Fast channels are aggregated, slow channels are forward-filled and flagged —
never the reverse — and nothing is filled across an `out_of_pen` gap.

### 5.3 What each consumer can rely on

Not instructions — availability. Each owner decides how their folder uses
this; these are the guarantees they can count on, and the gotchas worth
knowing about.

- **For `model/`** — the interim tables at native rate, and `joined_1min` for
  labels and context; RGB is out of scope for now so there is no frame index.
- **For `backend-analysis/`** — `joined_1min` is the analysis-ready
  table. `assert_no_group_leakage` is available if you want a cheap guard
  before training.
- **For `backend-visualization/`** — `joined_1min` plus the daily
  `milk` table. Worth knowing: a modality can be legitimately absent
  for a given cow-window, so the sidecar is the reliable source of what
  exists in a given run.
- **For `frontend/`** — nothing here is a direct dependency; the data path
  runs through `backend-visualization/`.

Requests for a different shape, extra columns, or another cadence are welcome
on the board — that is a cleaning change and I will make it.
