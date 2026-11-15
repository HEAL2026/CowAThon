# Behaviour classifier — evaluation

Protocol: **leave_one_cow_out (n=10)**, 70,936 labelled 10 s windows, 10 cows, 2023‑07‑25.
RandomForest (300 trees, balanced subsample), 27 IMU features. Seed 0.

**Macro F1 0.566 · accuracy 0.754** on unseen animals.

## Per class

| class | precision | recall | F1 | support |
|---|---|---|---|---|
| walking | 0.497 | 0.208 | 0.293 | 1122 |
| standing | 0.622 | 0.673 | 0.647 | 19024 |
| feed_up | 0.500 | 0.397 | 0.443 | 5364 |
| feed_down | 0.765 | 0.791 | 0.778 | 7796 |
| licking | 0.565 | 0.698 | 0.625 | 582 |
| drinking | 0.556 | 0.214 | 0.309 | 810 |
| lying | 0.864 | 0.871 | 0.867 | 36238 |

## Confusion matrix (rows = true, cols = predicted)

| | walking | standing | feed_up | feed_down | licking | drinking | lying |
|---|---|---|---|---|---|---|---|
| **walking** | 233 | 664 | 62 | 102 | 4 | 11 | 46 |
| **standing** | 184 | 12809 | 1009 | 631 | 46 | 105 | 4240 |
| **feed_up** | 17 | 1451 | 2132 | 1044 | 88 | 5 | 627 |
| **feed_down** | 13 | 571 | 828 | 6165 | 168 | 9 | 42 |
| **licking** | 3 | 88 | 19 | 64 | 406 | 0 | 2 |
| **drinking** | 13 | 556 | 12 | 42 | 4 | 173 | 10 |
| **lying** | 6 | 4456 | 200 | 11 | 2 | 8 | 31555 |

## Per cow (held out)

| cow | windows | macro F1 | accuracy |
|---|---|---|---|
| C01 | 7110 | 0.483 | 0.737 |
| C02 | 7087 | 0.644 | 0.753 |
| C03 | 7100 | 0.521 | 0.806 |
| C04 | 7107 | 0.397 | 0.677 |
| C05 | 7078 | 0.487 | 0.773 |
| C06 | 7082 | 0.488 | 0.716 |
| C07 | 7096 | 0.569 | 0.700 |
| C08 | 7087 | 0.626 | 0.784 |
| C09 | 7109 | 0.609 | 0.795 |
| C10 | 7080 | 0.583 | 0.797 |

## Reading it

- Lying vs not‑lying is the decision the health index depends on most; see its row.
- `licking`, `drinking`, `walking` have < 1.5 % of windows each; low F1 there is expected and is why the
  pipeline maps them to `other` for daily features (brief S4).
- Lying from the ankle sensor overrides the classifier wherever they disagree (brief S4).

## Independent grouped train/calibration/test benchmark

This is a fixed cow-disjoint holdout, separate from the primary LOCO score.
Fit, calibration, and test windows come from disjoint cows; no rows are split
independently. The classifier uses neck IMU only. The ankle signal remains a
downstream production override and is not used in this benchmark.

- Fit cows: C02, C03, C04, C06, C09, C10
- Calibration cows: C01, C08
- Test cows: C05, C07
- Calibrated macro F1: **0.595**
- Calibrated accuracy: **0.766**
- Mean one-vs-rest Brier score: **0.0474**

The seven-state report is intentional: lying, standing, walking, feed-up,
feed-down, licking, and drinking are all retained so daily state patterns
can be compared with each cow's baseline. The health pipeline should allow
normal cow-to-cow and day-to-day variation rather than treating one state
as universally abnormal.

Probability calibration uses cows outside the fit and test groups. It makes
`pred_prob_calibrated` interpretable as a confidence signal, but does not
turn a behavior state into a clinical diagnosis.
