# Backtrace: transmission model and procedure (v2)

Canonical spec, set by the team lead (@hazelLu6) on 2026‑11‑15. Every folder's
`CONTRACT.md` and README aligns to this document; where they disagree, this
document wins until the lead changes it. Maintained by backend‑cleaning.

The model is **forward contact tracing over two fomite routes**: a cow sheds
into a *resting spot* (bedding) or onto a *milking unit* (cluster), and the
cows that use that resource **next** are the ones exposed. It is a monitoring
aid, never a diagnosis: UI copy says *flagged for review* and *exposed*, never
*infected*.

## 1. What the user sees

| User action | Resting screen | Milking screen | Map |
|---|---|---|---|
| flags one cow | its resting spots in the window, drawn apart from the overall spot layer | the units it used | the cows that rested in those spots **after** it (tiered by exposure) and the cows milked on those units **after** it |
| flags several cows | the union of their spots; spots used by **≥ 2 flagged cows** drawn stronger | the union of their units; units used by **≥ 2 flagged cows** drawn stronger | successors of any flagged cow, tiered; a cow that succeeds two flagged cows outranks one that succeeds one |
| nothing flagged | overall spot layer only | unit occupancy only | no exposure tiers |

Highlight *tiers*, not booleans: with 10 cows in one cubicle row every spot is
eventually used by everyone (§6), so "used by ≥ 2 flagged cows" lights up the
whole pen unless it is weighted by *how soon after* and *how long*.

## 2. Inputs

| Table | Source | Provenance today |
|---|---|---|
| `lying_bouts` (`cow_id, start_utc, end_utc, duration_min, x_m, y_m, z_m, n_fixes, in_pen_frac`) | backend‑cleaning | real, 1,462 bouts, 1,296 ≥ 20 min |
| `resting_spots` (§3.2) | backend‑cleaning | real, derived from bouts |
| `milking_log` (`cow_id, milking_time, unit_id, session_id, order_in_session`) | synthetic (`data/synthetic/`) until a farm feed exists | synthetic |
| `sanitation` (`unit_id, sanitized_at, session_id`) | synthetic | synthetic — one event per unit per session, **after** the session ends |
| `bedding` (`zone_id, changed_at`) | synthetic | synthetic — 2023‑07‑21 14:00Z and 2023‑07‑28 14:00Z |
| `flags` (`cow_id, flagged_at, onset_utc?, source, type`) | manual / auto | per request |
| `mastitis_events` (Gram status) | backend‑cleaning | real, 57 dx, none inside the sensor window |

Every output row carries `provenance` per table and `is_synthetic` per
component. A payload is `is_synthetic=false` only if **both** the bouts and the
resource log it used were real; today that is never true for the milking route.

## 3. Definitions

### 3.1 Flags and windows
- `F` — the set of flagged cows. The **index cow** is the earliest `onset_utc`
  (else earliest `flagged_at`).
- **Infectious window** of a flagged cow `f`:
  `[onset_f − 48 h, min(last_flag + 96 h, data_end)]`. If `onset_utc` is
  absent use `flagged_at − 72 h` as the start. Shedding precedes clinical
  signs; the 48 h lead is the pre‑clinical allowance.
- **Investigation window** `W = ⋃ over f ∈ F` of the infectious windows.
  *Never* anchor `W` at `max(flagged_at) − 72 h`: on the synthetic milking
  episode that excludes the planted session entirely (source 07‑29 20:48Z,
  window start 07‑30 13:48Z) and the route is unrecoverable.

### 3.2 Resting spots
Cows do not rest at random coordinates; they use cubicles. A **spot** is a
cluster of bout centres with ≤ 1.5 m linkage, dwell‑weighted centroid, built
once from all bouts ≥ 20 min and stored as `resting_spots`
(`spot_id, center_x_m, center_y_m, radius_m=1.5, n_bouts, n_cows, is_synthetic`).
On the real data this yields **5 spots**, four of them used by all 10 cows
(§6). A bout belongs to the spot whose centre is nearest within 1.5 m; bouts
with no coordinates or `in_pen_frac < 0.5` are excluded.

Per‑bout 1.5 m circles (the current `implicated_resting_areas`) are **not**
spots: 80 bouts of one cow produce 80 circles that overlap each other, and the
contact graph saturates (4,091 events in 72 h, every cow at exposure 1.0).

### 3.3 Bedding and sanitation bounds
- A resting succession counts only if the successor's bout starts **before
  the next `changed_at`** after the flagged bout ends.
- A milking succession counts only if no `sanitized_at` for that unit falls
  between the flagged visit and the successor's visit, and both are in the
  same `session_id`.

## 4. Procedure

**Step 1 — resources of the flagged cows.** For each `f ∈ F` within its
infectious window: the spots it rested in (`S(f)`, with dwell minutes) and the
units it was milked on (`U(f)`, with session and order). For each resource `r`
record `n_flagged(r) = |{f : r ∈ S(f) ∪ U(f)}|`. `n_flagged ≥ 2` is the
"shared" highlight.

**Step 2 — forward successions.** For each flagged bout in spot `s`, take the
next `K = 2` occupants of `s` (any cow, flagged or not) before the next bedding
change. For each flagged milking on unit `u`, take the next `K = 2` cows on `u`
in the same session, stopping at sanitation. Weight each succession

- resting: `w = exp(−lag_h / 12) · min(dwell_min, 120) / 120 · 1 / rank`
- milking: `w = 1 / rank` (rank 1 = the very next cow)

where `lag_h` is hours from the flagged bout's end to the successor's start and
`rank ∈ {1, 2}` is the successor's position.

**Step 3 — exposure of unflagged cows.** `e_rest(c) = Σ w` over resting
successions where `c` is the successor, `e_milk(c)` likewise;
`e(c) = 1 − (1 − min(e_rest, 1))(1 − min(e_milk, 1))` after scaling each by its
herd‑max. Rank; report `primary_route = argmax(e_rest, e_milk)`, the resources
and the flagged predecessors behind the score. **This ranking is the primary
product.** Tiers for the map: top third *high*, next third *moderate*, rest
*low*; zero exposure is *none*.

**Step 4 — route attribution among the flagged cows.** For each route compute
`T_route = Σ w` over successions whose predecessor is a flagged cow and whose
successor is a *different* flagged cow with `onset − succession_time ∈ [6 h, 96 h]`
(the incubation window). Null: keep every onset time, reassign the secondary
identities uniformly among the non‑index cows, `B = 1000`. Report
`z = (T − μ_null) / σ_null` and the exact `p`.

Decision uses **effect size, not a p gate**:

| condition | `likely_route` |
|---|---|
| `max z ≥ 1` and the other `z < max z − 0.5` | the route with max `z` |
| both `z ≥ 1` and within 0.5 | `both` |
| `max z < 1` | `no_common_route` |

`p` is reported next to `z`. With 10 cows the permutation floor is
`1 / C(9, k)` — 0.012 for three secondaries, 0.028 for two — so a 0.05 gate
cannot be cleared reliably even when the route is right, which is exactly why
`main` answers `no_common_route` on both planted episodes today.

**Step 5 — pathogen prior (optional).** If `mastitis_events` carries Gram
status for a flagged cow: Gram‑positive / contagious → prior 0.7 on the milking
route; Gram‑negative / coliform → prior 0.7 on the resting route; unknown →
0.5. Posterior over routes ∝ prior · exp(z). Report both prior and posterior;
never let the prior override Step 4 silently.

**Step 6 — output** (`backtrace_result.json`, `POST /backtrace`):

```
investigation_window: {start_utc, end_utc, anchor: "onset"|"flagged_at"}
flagged_cows: [{cow_id, role: index|secondary, onset_utc?, flagged_at}]
resources:
  resting_spots: [{spot_id, center_x_m, center_y_m, radius_m, n_flagged, flagged_cows[],
                   dwell_min_by_flagged{}, successors[{cow_id, rank, lag_h, w}], until_bedding_change_utc, provenance}]
  milking_units: [{unit_id, n_flagged, flagged_cows[], sessions[], successors[{cow_id, rank, session_id, w}],
                   sanitized_between: bool, provenance}]
exposed_cows: [{cow_id, e, e_rest, e_milk, tier, primary_route, via[{resource, predecessor, w}]}]
route: {likely_route, z_rest, z_milk, p_rest, p_milk, p_floor, prior?, posterior?, n_permutations}
provenance: {lying_bouts: real|synthetic, milking_log: ..., sanitation: ..., bedding: ...}
is_model_suggestion: true
```

Coordinates are in the centred UWB frame (`x −11.99..11.91`, `y −8.81..7.88`),
the same frame `/api/pen-map` now emits.

**Step 7 — highlighting (frontend).** Resting screen: overall spot layer dim;
`S(F)` normal; `n_flagged ≥ 2` strong. Milking screen: `U(F)` normal;
`n_flagged ≥ 2` strong. Map: flagged cows with the flag mark; successor cows
coloured by tier; clicking a resource lists its flagged users and its
successors with `w`. Provenance badge per panel; synthetic milking data is
labelled as such on the milking screen itself, not only in a tooltip.

## 5. Evaluation (S11) — the acceptance test for every folder

Ground truth: `backend-cleaning/data/synthetic/synthetic_labels.parquet`, three
episodes built from the **real** bouts and the synthetic milking log
(`cleaning/synth.py`): a resting episode (index C06 → C07, C10, C01), a
milking episode (index C05 → C04, C08 on unit U2, session 2023‑07‑29_PM), and
a sporadic triple (C02, C03, C09).

Two metrics, measured separately, both reported in `backtrace_eval.json`:

1. **Exposure ranking** — flag the index cow only, forward window
   `[onset − 48 h, dx + 96 h]`, rank the other nine. `precision@k`, `k` =
   number of true secondaries.
2. **Route attribution** — flag index and secondaries, run Step 4.
   `route_accuracy` over the three episodes and `source_hit` (the planted spot
   or unit is in the top resources).

Measured 2026‑11‑15 on the real bouts + synthetic log:

| | `main` (per‑bout circles, p‑gated, window anchored at max dx) | this spec (prototype) |
|---|---|---|
| resting precision@3 | 0 / 3 | **3 / 3** (C01 5.16, C10 4.13, C07 4.01, next C03 3.95) |
| milking precision@2 | 0 / 2 | **1 / 2** (C04 4.0, C01 1.0, C08 0.5) |
| route accuracy | 1 / 3 (only the sporadic case, by default) | resting `p` 0.085, milking `p` 0.09–0.15 (floors 0.012 / 0.028); sporadic `p` 0.96–1.0 |
| contact events, resting, 72 h | 4,091; all 10 cows at exposure 1.0 | bounded; 5 spots |

The evaluator on `main` scores the built‑in C02 fixture unless the real tables
are passed explicitly (`analysis.run` does not pass them), and the live
`POST /backtrace` path calls `backtrace()` without any tables, which triggers
the same fixture. Both must load the real `lying_bouts` and the synthetic
`milking_log` / `sanitation` / `bedding` from `backend-cleaning/data/`.

Acceptance: resting precision@3 ≥ 2/3, milking precision@2 ≥ 1/2, sporadic
`likely_route = no_common_route`, every output row carrying provenance, and
`is_synthetic` honest per §2.

## 6. Limits of this dataset (state them in the UI)

- One cubicle row: all 1,296 bouts cluster into five spots on `y ≈ 0`, four of
  them used by every cow. Location alone cannot separate cows; *timing* can.
- Ten cows, so permutation p‑values have a hard floor (§4, Step 4).
- Milking order, sanitation and bedding changes are synthetic. The synthetic
  sanitation happens after each session, so it never separates two cows in the
  same session; the planted route is distinguished only by who got sick when.
- No real clinical case falls inside the sensor window; the nearest is C12's
  2023‑09‑02 Gram‑positive diagnosis.

## 7. Ownership

| Step | Owner | Folder |
|---|---|---|
| `resting_spots` table; `flags.onset_utc`; data contracts | @hazelLu6 | backend‑cleaning |
| Steps 1–6, evaluator loading real tables, `backtrace_eval.json` metrics | @equan04 | backend‑analysis |
| `/backtrace` delegation passing the real tables; ICAR models | @uiobio | apis |
| `POST /backtrace` and `/api/attribution` surfacing §4 Step 6 unchanged; no fabricated fallback circles | @pauraque | backend‑visualization |
| Step 7 highlighting; resting and milking screens; provenance badges | @uiobio | frontend |
