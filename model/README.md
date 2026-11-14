# Model

Owner: @hazelLu6

Owns the computer-vision and modeling work for **Challenge 1 (MMCows)**:
multi-view RGB handling, training, evaluation, checkpoints, and the inference
interface the other roles call.

## Boundary

In scope here:

- Multi-view RGB preprocessing that is *model-specific* (resize, crop,
  augmentation, batching, frame sampling).
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

Reads the frame index and aligned sensor tables produced by
`backend-cleaning/`, keyed on `cow_id` + `ts_utc`. Image bytes are read from
`backend-cleaning/data/raw/` paths referenced by the frame index; this folder
does not re-ingest or re-time-align anything.

Challenge data is never committed here. Checkpoints and prediction dumps are
gitignored — they are build artifacts, not source.

## Two rules that are not negotiable

These come straight from the track prompt, and getting either wrong
invalidates the result:

1. **Split on animals, never on rows or frames.** The same cow appears across
   many frames and many views, so a random frame-level split leaks animal
   identity into the test set. Use the shared helper:

   ```python
   from cleaning.splits import group_split, assert_no_group_leakage

   train, test = group_split(frame_index, by="cow_id", test_frac=0.25, seed=0)
   assert_no_group_leakage(train, test)
   ```

   Views of the same cow at the same timestamp must not straddle the split
   either — group on `cow_id` first, and keep all views of a held-out animal
   held out.

2. **Ship a defensible baseline before anything clever.** The prompt requires
   at least one baseline and a stated definition of what counts as an
   improvement over it. Record both, and report uncertainty plus behavior when
   a modality is missing.

No unsupported clinical diagnosis in any output — monitoring and prediction
framing only.
