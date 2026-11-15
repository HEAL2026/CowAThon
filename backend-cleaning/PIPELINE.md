# The cleaning pipeline, in three stages

Presentation notes for the Challenge 1 (MMCows) data layer. What each stage
does, why, and the numbers from the real run. The authoritative column list
is [CONTRACT.md §5](CONTRACT.md); this page is the story.

**The problem.** Fourteen days, sixteen cows, nine sensor streams sampled
anywhere from 10 Hz (collar IMU) to once a day (milk). Two ID schemes. Two
daily holes when the cows leave for milking. A weather file in Fahrenheit
strings. If the dashboard's numbers are going to be trusted, every one of
those has to be handled once, visibly, and in the same place.

```
raw (CSV/XLSX, as downloaded)  ->  interim (one table per stream, native rate)
                                ->  processed/joined_1min.parquet (one row per cow-minute)
                                ->  reports + sidecars (what was dropped, filled, flagged)
```

Reruns are byte-identical. Nothing is filled silently.

---

## Stage 1 — ingest: raw → one table per stream, native rate

Each stream is parsed by a small pure function and written to
`data/interim/<stream>.parquet` with a `.schema.json` sidecar (dtype, units,
null count per column). What gets fixed here:

| Issue in the raw data | What Stage 1 does |
|---|---|
| Two ID schemes: `Cxx` = cow, `Txx` = collar tag | One key, `cow_id` (C-scheme). Tag → cow map from the official loaders. |
| Unix-epoch timestamps, barn in Chicago time | `ts_utc`, tz-aware. Local hour derived downstream, never stored twice. |
| Weather is `.xlsx`, cells like `"60.7 °F"`, `"29.65 in"`, no date column | Regex parse, imperial → SI (°C, m/s, hPa, mm), date from the filename. |
| `thi/average.csv` header says `temperature_F`, values are °C | Unit checked against the file's own THI column; header not trusted. |
| UWB has null coordinates ~5 % of the time | **Not missing data.** Nulls cluster at 04–05h and 15–16h local — the two milking trips. Kept as `out_of_pen = True`, never filled. |
| 0.4 % of UWB fixes are physically impossible (12 m underground) | Kept, flagged `uwb_suspect`, excluded from minute means. |
| T13/T14 in uwb/immu/pressure are not cows (stationary reference tags) | Kept apart in `uwb_unmapped` / `collar_unmapped` as the **data-scarce fixture** — see Stage 3. |
| IMU + pressure are 10 Hz, 11 GB | Aggregated to the minute at ingest (`collar_1min`): \|accel\| mean/std, pressure mean, sample counts. Native rate stays in raw. |
| Behaviour labels use code 0 = "unknown" | Kept and flagged `behavior_known = False`; never treated as a class. |

Rows are dropped only for a missing **key** (`cow_id` or `ts_utc`), and the
count goes in `ingest.report.json`. Real run: **0 rows dropped**, in every
stream.

## Stage 2 — join: one row per cow per minute

`data/processed/joined_1min.parquet`: 10 sensored cows × every minute from
2023‑07‑21 12:30 to 08‑04 07:00 local = **198,310 rows × 61 columns**. The
cadence is in the filename and the sidecar so no consumer has to guess what a
row means.

The rule that makes a single cadence honest:

> **Fast channels are aggregated. Slow channels are forward-filled and
> flagged. Per-cow channels are never forward-filled.**

| Channel | Native rate | How it reaches 1 min |
|---|---|---|
| CBT, lying (ankle), indoor THI | 1 min | as is; gaps stay empty |
| UWB location | 15 s | mean of the minute's in-bounds fixes; `out_of_pen` = any null; `uwb_suspect_frac` |
| Collar IMU, pressure | 10 Hz | per-minute mean/std (+ sample counts) from Stage 1 |
| Outdoor weather | 5 min | forward-filled → `outdoor_*_is_imputed`, `outdoor_*_age_s` (seconds since the real reading); dropped as missing after 30 min |
| Milk yield, DIM | daily | carried through the local day → `milk_yield_kg_is_imputed`, `milk_yield_kg_age_s` |
| Behaviour labels | 1 s, 07/25 only | dominant known code per minute, `behavior_known_frac`, `behavior_lying_frac`; null on other days |

So every filled value carries two companions: **is it real or carried** and
**how old is it**. The dashboard can show staleness, the analysis can weight
by it, and nobody discovers after the fact that a "reading" was eight hours
old. `out_of_pen` propagates to the minute, so a cow in the milking parlour is
a known state on the grid, not a hole.

(The original plan was mean/min/max/std for every fast channel. The real data
made that unnecessary: location wants a mean, IMU wants magnitude mean + std,
pressure wants a mean. Fewer columns, same information.)

## Stage 3 — report and guards

Two reports and two guards, so the numbers downstream are defensible:

- `ingest.report.json` — rows dropped for a null key per stream (0), stationary
  tags separated, source file counts.
- `joined_1min.report.json` — rows, cows, span, and per column: how many
  values are imputed and how many are null. Imputation is a reported quantity,
  not a side effect.
- `cleaning.splits.group_split` / `group_kfold` — the **only** way to split:
  whole animals, never rows. The same cow appears in ~20,000 minutes; a
  row-level split would score animal identity, not signal. `assert_no_group_leakage`
  runs on every fold.
- **The data-scarce fixture (T13/T14).** The two stationary reference tags
  have location and collar streams but no body temperature, no lying sensor,
  no milk, no labels — and no motion. We keep them on purpose, apart from the
  herd, as a test subject for "most modalities missing": the confidence score
  should fall, missing modalities should be *reported* rather than imputed,
  and motion or behaviour inference on a tag that never moves should read
  as "no activity", not as a lying cow. It is the prompt's "behaviour when a
  modality is absent" question, answered with real sensor noise instead of a
  synthetic hole. Materialised: `uwb_unmapped` 156,151 rows and
  `collar_unmapped` 39,212 rows over both tags. They behave as advertised —
  position standard deviation 0.13–0.25 m (a cow's is metres) and collar
  \|accel\| 9.87/10.06 m/s² with a standard deviation of 0.11/0.20, i.e.
  gravity and nothing else.

## What the real run says

- Out-of-pen: 75–85 min/day per cow, 4,739 + 3,898 minutes at the 04h and 15h
  milking hours vs ≤ 90 at any other hour — the milking-trip hypothesis
  confirmed from data, which is why it is a state and not missingness.
- Behaviour label `lying` vs the ankle sensor's `lying` agree on **99.2 %** of
  labelled minutes — two independent instruments, one answer.
- Core body temperature 38.4–38.6 °C per cow, indoor THI 58–83, outdoor
  13–33 °C, milk 31–58 kg/day: all in the physiologically sensible range, no
  unit slips.

Rebuild everything from raw: `python3 -m cleaning` (≈3 min, or ≈6 s with
`--skip-heavy` to leave out the 10 Hz aggregate).
