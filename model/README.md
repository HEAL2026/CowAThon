# Model

Owner: @hazelLu6

Owns the trained models for **Challenge 1 (MMCows)**. Scope changed on
2026‑11‑15 with the mastitis‑backtrace brief: RGB / computer vision is **out**
(the 21 GB `visual_data.zip` is not pulled), and the one trained model is the
**behaviour classifier on neck‑IMU windows** (brief S4). Everything else in
the pipeline is rules, statistics or unsupervised.

## Behaviour classifier (`behavior/`)

```bash
cd model && python3 -m pip install -r requirements.txt
python3 behavior/features.py     # 10 s windows x IMU features for 2023-07-25, labelled   (~2 min)
python3 behavior/train.py        # LOCO + grouped holdout/calibration, report + checkpoint (~5 min)
python3 behavior/apply.py        # all 14 days -> behavior_minute                            (~15 min)
```

- **Input**: 10 Hz `immu` (accel xyz m/s², mag xyz µT) from `backend-cleaning/data/raw/`,
  and the 1 s ground‑truth labels from `backend-cleaning/data/interim/behavior.parquet`
  (10 sensored cows, 2023‑07‑25, 7 classes; code 0 = unknown is never a class).
- **Windows**: 10 s, non‑overlapping, whole‑second aligned. Label = majority
  known label when ≥ 80 % of the window is labelled; otherwise unlabelled
  (kept for inference, dropped from training).
- **Features** (~35): per‑axis mean/std/min/max, |a| mean/std, ODBA, VeDBA,
  pitch/roll from the gravity estimate, FFT dominant frequency, spectral
  energy and 0.5–2.5 Hz band share, magnetometer heading mean, circular std
  and mean |Δheading| (head direction derived here; the 6 GB `head_direction`
  sub_data is not needed).
- **Model**: RandomForest, 300 trees, `class_weight=balanced_subsample`.
- **Evaluation**: **leave‑one‑cow‑out** over the 10 cows — the score is for an
  unseen animal, never for rows of a cow the model has seen. Per‑class F1,
  confusion matrix and per‑cow table in [`reports/behavior_eval.md`](reports/behavior_eval.md).
- **Grouped holdout**: training also runs a deterministic cow-disjoint
  fit/calibration/test split. Test cows are selected first; the remaining cows
  are split into fitting and probability-calibration groups. No cow appears in
  more than one group. Leave-one-cow-out remains the primary estimate across
  all animals.
- **Probability calibration**: sigmoid calibration is fit only on calibration
  cows and reported with a multiclass Brier score. Calibrated confidence is
  separate from the predicted state and is not a diagnosis.
- **Output**: `behavior_minute` (cow_id, ts_utc, behavior, prob) for all 14
  days; the ankle `lying` channel **overrides** the classifier where they
  disagree (brief S4). `checkpoints/behavior_rf.joblib` is gitignored.

Rare classes (`licking`, `drinking`, `walking`, each < 1.5 % of windows) are
reported honestly and mapped to `other` for daily features downstream.

### State overview and tolerance

The model is deliberately not reduced to binary lying. The seven states
(`lying`, `standing`, `walking`, `feed_up`, `feed_down`, `licking`, and
`drinking`) remain available for the cow's activity overview. A normal cow may
spend different amounts of time in each state, so downstream interpretation
should compare each cow with its own history and cohort baseline, use daily
state proportions/bouts, and tolerate ordinary variation. A state prediction
is evidence for monitoring, not a claim that the cow is unwell.

The neck-only classifier is evaluated directly. The ankle channel is not a
separate model benchmark: it is retained only as the existing production
override at minute resolution, where available.

### How cow-disjoint evaluation differs from raw data

Raw MMCows data has many time windows from each cow. A row-level split would
put windows from the same animal into both train and test, allowing collar
orientation, body shape, and other animal-specific signatures to inflate the
score. Cow-disjoint evaluation instead partitions the animal IDs first:

```text
all labelled windows
  ├─ test cows          -> never used for fitting or calibration
  └─ remaining cows
       ├─ calibration cows -> only used to calibrate probabilities
       └─ fit cows         -> used to fit the Random Forest
```

Every window from one cow stays in exactly one partition. This changes the
question from “can the model recognize more windows from familiar cows?” to
“does it generalize to a cow it has never observed?” The raw rows and their
timestamps remain intact; only their use in evaluation is partitioned.

### Feed-intake timing

When optional `dmi_kg` is available, the analysis layer retains two- and
three-day lagged DMI features because intake changes can affect milk production
after approximately 2–3 days. Same-day intake is not treated as the only
explanation for same-day milk changes. The model and health pipeline continue
without DMI when it is unavailable.

## Boundary

In scope here:

- IMU windowing and feature extraction that is *model-specific* (window length,
  feature set, label alignment).
- Model definition, training loops, hyperparameters, checkpoints.
- Evaluation of the model itself: metrics, baseline comparison, per-animal
  and per-view error breakdowns.
- The inference entry point other roles call.

Not in scope, and owned elsewhere:

- Ingestion, time alignment, unit normalization, and missing-value policy —
  `backend-cleaning/` ([CONTRACT.md](../backend-cleaning/CONTRACT.md)).
- Statistical analysis and documented metrics over results —
  `backend-analysis/`.
- Visualization-ready payload shaping — `backend-visualization/`.
- Rendering and presentation state — `frontend/`.

## Inputs

Reads the interim/processed tables produced by `backend-cleaning/`, keyed on
`cow_id` + `ts_utc`, and the raw 10 Hz IMU CSVs under
`backend-cleaning/data/raw/` (the native rate is not re‑materialised); this
folder does not re‑ingest or re‑time‑align anything.

Challenge data is never committed here. Checkpoints and prediction dumps are
gitignored — they are build artifacts, not source.

An optional external milk/physiology example is documented in
[`backend-cleaning/README.md`](../backend-cleaning/README.md): Mendeley Data
[954f6g36sb/2](https://data.mendeley.com/datasets/954f6g36sb/2), DOI
`10.17632/954f6g36sb.2`, CC BY 4.0. It can supply normalized milk features
for calibration or an explicitly mapped evaluation cohort, but it is never
required for cow-health evaluation. Missing milk features remain missing and
reduced modality coverage must be reported when the file is unavailable.

## Two rules that are not negotiable

These come straight from the track prompt, and getting either wrong
invalidates the result:

1. **Split on animals, never on rows or frames.** The same cow appears across
   many minutes and many windows, so a random row-level split leaks animal
   identity into the test set. Use the shared helper:

   ```python
   from cleaning.splits import group_split, assert_no_group_leakage

   train, test = group_split(windows, by="cow_id", test_frac=0.25, seed=0)
   assert_no_group_leakage(train, test)
   ```

   The behaviour classifier uses leave‑one‑cow‑out for exactly this reason.

2. **Ship a defensible baseline before anything clever.** The prompt requires
   at least one baseline and a stated definition of what counts as an
   improvement over it. Record both, and report uncertainty plus behavior when
   a modality is missing.

No unsupported clinical diagnosis in any output — monitoring and prediction
framing only.

## MMCows pretrained sensor weights

The official MMCows `sensor_model_weights.zip` was downloaded locally for
compatibility investigation at `model/external/` (ignored and never committed).
Its IMMU behavior checkpoint is a TensorFlow/Keras 2.13 HDF5 model with input
shape `(100, 4)` and seven output classes. Official preprocessing uses
10-second, 50%-overlap windows at 10 Hz, Haar DWT features for the three
accelerometer axes, and a fourth `relative_angle` head-direction feature,
standardized per feature. The network is Flatten -> Dense(300) -> Dense(256) ->
Dense(128) -> seven-class softmax.

This checkpoint is not directly compatible with the current neck pipeline:
local IMMU files contain accelerometer plus magnetometer columns, while the
checkpoint expects the separately derived `relative_angle` head-direction
stream. The archive also contains UWB and UWB-HD pickle models with different
input schemas. Use the archive for a controlled baseline or fine-tuning
experiment only after reproducing the official preprocessing and verifying
the required head-direction input. Do not commit or publicly upload the
archive; MMCows data and derived weights are CC BY-NC-SA 4.0 and subject to
the project restricted-data policy.
