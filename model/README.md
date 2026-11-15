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
python3 behavior/train.py        # RandomForest, leave-one-cow-out, report + checkpoint     (~5 min)
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
- **Output**: `behavior_minute` (cow_id, ts_utc, behavior, prob) for all 14
  days; the ankle `lying` channel **overrides** the classifier where they
  disagree (brief S4). `checkpoints/behavior_rf.joblib` is gitignored.

Rare classes (`licking`, `drinking`, `walking`, each < 1.5 % of windows) are
reported honestly and mapped to `other` for daily features downstream.

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
