# MMCows data notes

Working notes for Challenge 1. Sources: the track prompt, the official repo
(<https://github.com/neis-lab/mmcows>), the project page
(<https://engineering.purdue.edu/neis/research/projects/mmcows/>), and a live
listing of the Kaggle mirror.

Status: CONTRACT.md §5 now carries the real schema (2026-11-15); the
pipeline in `cleaning/` implements items 1–4 and 6 of [Open items](#open-items).

---

## 1. Quirks that will bite

Ordered by how much damage they do if missed.

### 1.1 Two deliberate ~30-minute holes every day

> "The cows are housed in a 20x12m pen where they only leave for milking twice
> daily for approximately 30 min each time." — project page

Twice a day every cow leaves the pen. UWB goes blank, cameras see nothing.
**These gaps are not sensor failures.** Consequences:

- Forward-filling across them invents a location for a cow that is not in the
  barn.
- Any anomaly detector flags them as the top anomaly, twice a day, per cow.
- A staleness column would report ~30 min of staleness as a data-quality
  problem rather than a normal daily event.

Cleaning needs an explicit `is_milking` / `out_of_pen` flag so downstream
treats this as a known state, not missingness.

### 1.2 Two ID schemes, same integer index

The official loaders build both from one `cow_id` integer:

```python
tag_name = f'T{cow_id:02d}'   # T01..T10 -> uwb, immu, pressure, head_direction
cow_name = f'C{cow_id:02d}'   # C01..C16 -> ankle, behavior_labels
```

`T01`-`T10` are the **10 instrumented cows** (collar tag + vaginal temperature
logger + ankle accelerometer). `C01`-`C16` are **all 16 cows**, which the
cameras identify and which have behavior labels. Paths differ per modality:
`main_data/uwb/T01/T01_0725.csv` vs `main_data/ankle/C01/C01_0725.csv`.

Joining on the wrong prefix silently yields an empty frame. Cleaning must
normalise both to one key.

**Hard ceiling:** multimodal fusion is capped at **10 animals**, and
cow-disjoint folds come out of those 10.

### 1.3 `main_data` is derived; `sub_data` is raw

Inverted from what the names suggest. Per the project page's processing flow:

| `main_data` (derived) | computed from | `sub_data` (raw) |
|---|---|---|
| `uwb` — 3D neck location | ← | `uwb_distance` — 8 anchor ranges |
| `ankle` — lying behavior | ← | `ankle_accel` |
| `head_direction` | ← | `immu` |

Do not re-derive these, and do not present them as measurements. This is also
why `uwb` is 29.7 MB while `uwb_distance` is 288 MB — solved position vs raw
ranging.

### 1.4 `behavior == 0` means UNKNOWN

Official code drops it: `label_df[label_df['behavior'] != 0]`, commented
"Remove unknown behavior". It is **not** a class. Training on it models noise.

Labels otherwise: **7 behaviors, 1-second granularity, one day (07/25), all 16
cows**, from 20k UWB-synced frames selected out of 4.8M.

### 1.5 Timestamps are Unix epoch integers, barn is America/Chicago

The join column is `timestamp` (Unix seconds). A `datetime` column exists and
the official code drops it. Timezone appears only in the temporal-split code:
`pytz.timezone('America/Chicago')`.

Epoch → UTC is unambiguous, so a `ts_utc` contract holds. But any local-hour
feature (milking times, day/night) needs Central, not UTC.

Trust is good: *"All sensors are synchronized to the internet time"* (NTP), so
cross-modality timestamps line up.

### 1.6 The official grid is 15 s, anchored on UWB — not our 1 minute

Their downsampling cascade:

1. 10 Hz → 1 Hz: `floor(timestamp)` then `groupby('timestamp').mean()`
2. 1 Hz → 1/15 Hz: subset by `isin(uwb_timestamps)` — **UWB is the master
   clock**
3. ankle attached via `merge_asof(..., direction='nearest')`

We signed off on a **1-minute** joined cadence, which is 4x coarser. Still
defensible for heat load, but it is a divergence from the published protocol
and means we cannot compare to their numbers at matched resolution. Worth
stating explicitly in the writeup.

### 1.7 Their split protocol does not satisfy the track prompt

- `configs/config_s1.json` — folds **by cow** (train 1-6, val 7-8, test 9-10).
  Their own comment calls it *"Object-wide split"*. Animal-disjoint. **Use
  this shape.**
- `configs/config_s2.json` — folds **by time window** within 07/25, with all
  cows in train, val *and* test. Comment: *"Temporal split"*.

**The entire RGB vision pipeline README uses `config_s2`.** Following it as
documented puts the same cow on both sides of the split, which is exactly the
leakage the prompt forbids. `config_s2` also hardcodes `id_list = [1..10]`
despite 16 cows having labels.

### 1.8 Official preprocessing is silently lossy

`data_df.dropna()` and `fillna(method='ffill')` with no record of what was
dropped or filled. Their reported sample counts are post-`dropna` — a hidden
source of sample loss. Our contract is deliberately stricter.

### 1.9 Smaller gotchas

- Uneven modality coverage, by file count: `cbt` 10, `milk` 16, `ankle` 150,
  `uwb` 180, `immu` 180, `pressure` 180, `thi` 7, `weather` 17. Not every cow
  has every modality.
- IMMU columns embed units: `accel_x_mps2`, `accel_y_mps2`, `accel_z_mps2`.
- `thi/average.csv` is headed `temperature_F` but the values are °C (25.7 with
  THI 73 only works in Celsius). `shape_thi` checks the unit against the
  file's own THI column rather than trusting the header.
- T13/T14 are the **two stationary tags** (official README: "The data of two
  stationary tags is provided in folders T13 and T14"), present in `uwb`,
  `immu` (T13) and `pressure`. Not cows — but a free UWB drift/noise reference.
- UWB frame is anchor-centred: the README lists the 8 anchors at x ∈ ±6.1 m,
  y ∈ [0, 5.13] m, z ≈ 4–5 m, which matches the pen-centred coordinates we see.
- Behaviour labels (`behavior_labels/individual/Cxx_0725.csv`): 1 s, 07/25
  only, all 16 cows, 86,400 rows each, columns `timestamp, datetime, behavior`
  with integer codes 0–7; 0 = unknown (official code drops it). Legend from
  `benchmarks/1_behavior_cls/immu/*.py` `behav_list`: 1 walking, 2 standing,
  3 feed up, 4 feed down, 5 licking, 6 drinking, 7 lying. Verified: code 7 ↔
  ankle `lying` agree on 99.3 % of minutes; codes 1–6 ↔ not lying ≥ 96 %.
  Class balance (all 16 cows, seconds): lying 604k, standing 287k, unknown
  243k, feed_down 130k, feed_up 80k, walking 17k, drinking 14k, licking 8k.
- Kaggle paths carry a **doubled prefix**: `sensor_data/sensor_data/main_data/...`
- `configs/path.yaml` ships the authors' hardcoded `/Users/test/Dropbox/...`
  paths.
- Benchmarks directory is misspelled: `benchmarks/2_beahvior_analysis`.
- Their IMMU benchmark uses raw 10 Hz windows → **Haar** DWT (the code sets
  `waveletname = 'haar'` while the comment says Daubechies). Matching it needs
  native-rate IMU, not summary stats.
- There is **no cleaning pipeline** in the repo. Preprocessing is embedded in
  five near-identical `data_loader.py` files; the rest is a vendored YOLOv8.

---

## 2. Size and access

Official release totals **3.74 TB**. The useful slice is far smaller.

### 2.1 The slow channels are tiny — laptop-viable

| Modality | Size | Rate |
|---|---|---|
| `main_data/uwb` | 29.7 MB | 15 s |
| `main_data/weather` | 9.1 MB | 300 s |
| `main_data/ankle` | 7.1 MB | 60 s |
| `main_data/thi` | 4.7 MB | 60 s |
| `main_data/cbt` | 3.9 MB | 60 s |
| `sub_data/visual_location` | 2.5 MB | 15 s |
| `sub_data/health_records` | 0.2 MB | — |
| `main_data/milk` | ~16 KB | daily |
| **Total** | **~57 MB** | |

The heat-load, milk-yield and behavior-summary work — the tabular core of
Challenge 1 — fits in ~57 MB. No remote compute required for it.

### 2.2 The heavy parts

`visual_data/images` 11.3 GB (truncated listing; ~21 GB full) ·
`main_data/immu` 7.27 GB · `sub_data/head_direction` 6.12 GB ·
`main_data/pressure` 4.34 GB · `sub_data/uwb_distance` 288 MB.

Remote compute is only justified for these.

### 2.2a Official HF release: sensor data is ONE 18.1 GB zip

`huggingface.co/datasets/neis-lab/mmcows` (ungated) has no per-section files:
`sensor_data.zip` (18.1 GB) holds everything tabular, `visual_data.zip`
(21.2 GB) the RGB. Member layout inside `sensor_data.zip`, sizes uncompressed:

| member prefix | files | size |
|---|---|---|
| `sensor_data/main_data/immu/T01..T10/Txx_MMDD.csv` | 180 | 7.27 GB |
| `sensor_data/main_data/pressure/T01..T10/` | 180 | 4.34 GB |
| `sensor_data/main_data/uwb/T01..T10 + T13,T14/` (12 tags × 15 days; T13/T14 unmapped) | 180 | 29.7 MB |
| `sensor_data/main_data/weather/07_21_2023.xlsx` … | 17 | 9.1 MB |
| `sensor_data/main_data/ankle/C01..C10/Cxx_MMDD.csv` (10 cows × 15 days) | 150 | 7.1 MB |
| `sensor_data/main_data/thi/average.csv` … | 7 | 4.7 MB |
| `sensor_data/main_data/cbt/Cxx.csv` | 10 | 3.9 MB |
| `sensor_data/main_data/milk/Cxx.csv` | 16 | 16 KB |
| `sensor_data/sub_data/head_direction` | 181 | 6.12 GB |
| `sensor_data/sub_data/uwb_distance` | 180 | 288 MB |
| `sensor_data/sub_data/{ankle_accel,health_records,neck_dev_temp,visual_location}` | 54 | 27 MB |
| `sensor_data/behavior_labels/individual/Cxx_0725.csv` | 16 | 32 MB |

Verified on disk 2026-11-15: uwb null coords cluster at 04–05h and 15–16h
local — the milking trips of §1.1, confirmed. Weather xlsx cells are strings
with imperial units ("60.7 °F", "29.65 in", "2.3 mph") and no date column.

Note `weather` is **.xlsx**, not CSV, and `cbt`/`milk` are one file per cow
(no per-day split), whereas uwb/immu/pressure/ankle are per cow per day.

**Fetch without the full zip:** [scripts/fetch_mmcows.py](scripts/fetch_mmcows.py)
reads the zip's central directory over HTTP range requests (`remotezip`) and
extracts only the chosen sections into `data/raw/sensor_data/...`, so RGB is
never downloaded. Resumable (skips members already present at the right size).
Default sections — the eight Hazel asked for — total **740 files / 11.66 GB**,
of which immu + pressure are 99.5 %. Verified 2026-11-15 after a mid-pull
network drop: every member byte-exact against the zip's central directory,
no partials. `thi/S05.csv` has no trailing newline and starts 5.5 h late
(19,500 rows vs 19,832) — that is the source file, not a truncation.

### 2.3 Kaggle mirror is partial

<https://www.kaggle.com/datasets/hienvuvg/mmcows> — **39.35 GB**, and
**pre-extracted CSVs, not zips** (so no 20 GB extraction problem).

Contains: all 14 days of `sensor_data`, plus `visual_data` (annotated 07/25
images, labels, projection matrices).

Missing vs the official HuggingFace release:

| Missing | Size | Matters? |
|---|---|---|
| `trained_models.zip` | 929 MB | **Yes** — pretrained vision weights |
| `sensor_model_weights.zip` | 370 MB | **Yes** — pretrained sensor weights |
| `cropped_bboxes.zip` | 13.7 GB | Regenerable via their `crop_bboxes_7b.py` |
| `cow_gallery.zip` | 1.92 GB | Reference photos, optional |
| `pred_labels.zip` | 20 MB | Their predictions, optional |
| `uwb_synced_images/` | ~310 GB | Not needed |
| `1s_interval_images/` | ~3 TB | Not needed |
| `15s_interval_combined_videos/` | ~40 GB | `0725_w_bbox.mp4` is a ready-made demo clip |

The two weight bundles total **1.3 GB** — small enough to pull locally from
HuggingFace and push up as a private Kaggle dataset.

Note: the Kaggle API returns **429** under heavy pagination. Cache the file
listing to disk rather than re-paginating.

### 2.4 Licensing

Two licenses, not a contradiction:

- **Code** — MIT (the GitHub repo).
- **Data** — **CC BY-NC-SA 4.0** (official project page and Kaggle).
  Non-commercial, attribution required, **share-alike on derivatives**.

Plus the track prompt forbids redistributing source data. So any derived
Kaggle dataset we create **must be private**.

---

## 3. Prior art

The project page lists **12 papers** using MMCows with a modality matrix.
Overlaps with plausible picks:

- **Milk-yield prediction — done twice** (Kim & Sohn; Sailunaz et al., from
  postures, explainable AI)
- **Behavior classification — three times** (Kumar; Marin; plus the official
  benchmark)
- CBT forecasting (Alvi, digital twin) · posture + barn localization
  (Avanzato) · health/stress with federated learning (Gulati) · multi-camera
  tracking (Nidhi) · feed/water intake on edge (Tekulapalli)

Not a reason to avoid those tasks — strong baselines are what the prompt asks
us to compare against. But "we predicted milk yield" is not novel. The gap no
paper on that list covers, and which the prompt explicitly rewards, is
**decision support**: prioritisation, confidence, staleness, and a
recommended next action.

---

## 4. Where we got to

Decisions made:

- **Challenge 1 (MMCows)**, called by the lead (@hazelLu6). CV work is
  @hazelLu6's.
- **1-minute joined cadence**, signed off by all three consuming roles
  (@uiobio frontend, @pauraque visualization, @equan04 analysis). Fast
  channels aggregated mean/min/max/std; slow channels forward-filled with
  `*_is_imputed` set; native-rate interim tables preserved.
- @equan04 will use **GroupKFold over the 10 wearable cows**, reporting
  mean ± std across animal folds.

Landed on `main` (PR #3):

- [CONTRACT.md](CONTRACT.md) — I/O contract: layout, `cow_id` + `ts_utc` keys,
  missing-data policy, units.
- [cleaning/splits.py](cleaning/splits.py) — `group_split`,
  `assert_no_group_leakage`. 7 tests passing.

Merged since: **#5** (`model/` folder, Challenge 1 decision, AGENTS.md §5
code review), **#7** (`apis/` folder, owner @uiobio, modular farm-system
integrations + mocks), **#14** (`group_kfold`).

Raw data: fetched locally via `scripts/fetch_mmcows.py` into
`data/raw/sensor_data/main_data/{milk,cbt,thi,ankle,weather,uwb,pressure,immu}`
(RGB excluded). Gitignored; never committed.

Tooling: Kaggle CLI installed at `~/Library/Python/3.12/bin/kaggle`, token at
`~/.kaggle/access_token` (mode 600), auth verified against the live API.
**That token was pasted in plaintext and should be rotated.**

---

## Open items

CONTRACT.md changes queued, ordered by severity. **None applied yet.**

1. **`is_milking` / out-of-pen flag** (§1.1) — highest impact.
2. **Dual `T`/`C` ID normalisation** (§1.2) — silent-empty-join risk.
3. **Derived-vs-raw provenance** (§1.3) — stop `main_data` reading as measured.
4. **Real schema**: Kaggle paths, `C01` naming, Unix-epoch `timestamp`,
   America/Chicago, doubled path prefix.
5. **`x_age_s` staleness column** — requested by @uiobio for the UI; cheap in
   cleaning, awkward downstream.
6. ~~**`group_kfold` helper**~~ — **done**, PR #14 (2026-11-15). @equan04
   consuming it with `n_splits=5, seed=0`; model/ must use the same.

Also unresolved: whether to move the joined cadence from 1 minute to the
official 15 s grid (§1.6).
