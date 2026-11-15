# Data contracts for the mastitis backtrace pipeline

Draft for @pauraque (Aster) to confirm the bedding and milk shapes; everyone
else consumes. Keys are **`cow_id`** (C‑scheme, `C01`…) and **tz‑aware UTC
timestamps**, matching `backend-cleaning/CONTRACT.md` §5 so these tables join
onto `joined_1min` without a translation layer. (The brief says `animal_id`;
we use `cow_id` everywhere already — one name.)

Every table carries **`is_synthetic`** (bool). Real and synthetic rows are
never mixed without it. Placeholders live in `data/placeholder/` with
`is_synthetic=true`; swapping in a real file is a path change in config only.
If a real file arrives in a different shape, the **loader** adapts — nothing
downstream does.

## bedding — Aster

| column | type | notes |
|---|---|---|
| `barn_id` | string | |
| `pen_id` | string | MMCows has one pen |
| `zone_id` | string | **Aster: per zone** (e.g. `cubicle_row_a`, `cubicle_row_b`); resting traces are bounded per zone between `changed_at` rows |
| `bedding_type` | string | e.g. `sand`, `straw`, `sawdust`, `recycled_manure_solids` |
| `changed_at` | timestamp UTC | **the bedding window boundary**; all bedding in the barn changes at once (brief §1) |
| `bacterial_count` | float, opt | CFU/g, if measured |
| `dry_matter_pct` | float, opt | |
| `notes` | string, opt | |
| `is_synthetic` | bool | |

A *bedding window* is the interval between consecutive `changed_at` rows for
the same pen. Resting-route exposure (S8) is only counted **within** a window.

## milk — Aster (possible); per milking visit

| column | type | notes |
|---|---|---|
| `cow_id` | string | |
| `milking_time` | timestamp UTC | start of the visit |
| `unit_id` | string | milking unit |
| `stall_number` | string, opt | **Aster: present**, per-visit rows confirmed |
| `yield_kg` | float | MMCows gives **daily** `milk_yield_kg`; per‑visit yield is synthetic unless Aster's data has it |
| `cond_lf`, `cond_lr`, `cond_rf`, `cond_rr`, `cond_max` | float, opt | mS/cm, **per quarter** (Aster), `cond_max` = max over quarters; ICAR ADE / DeLaval / Lely naming |
| `scc_kcells_ml` | float, opt | somatic cell count, thousand cells/mL |
| `fat_pct`, `protein_pct`, `lactose_pct` | float, opt | |
| `blood_flag` | bool, opt | |
| `is_synthetic` | bool | |

## milking_log — synthetic unless `milk` carries it

| column | type | notes |
|---|---|---|
| `cow_id` | string | |
| `milking_time` | timestamp UTC | |
| `unit_id` | string | |
| `session_id` | string | one per milking (2/day in MMCows: ~04:00 and ~15:00 local — observed in UWB `out_of_pen`) |
| `order_in_session` | int | 1 = first cow on that unit in that session |
| `is_synthetic` | bool | |

## sanitation — synthetic or manual

| column | type | notes |
|---|---|---|
| `unit_id` | string | |
| `sanitized_at` | timestamp UTC | milking‑route exposure (S9) stops at the unit's next sanitation |
| `is_synthetic` | bool | |

## flags — manual or auto

| column | type | notes |
|---|---|---|
| `flag_id` | string | |
| `cow_id` | string | |
| `flagged_at` | timestamp UTC | |
| `onset_utc` | timestamp UTC, opt | first clinical sign if known; the backtrace infectious window starts 48 h before it (see `docs/backtrace_spec.md` §3.1) |
| `source` | `manual` \| `auto` | |
| `type` | `clinical` \| `subclinical` \| `suspected` | |
| `quarter` | `LF` \| `RF` \| `LR` \| `RR`, opt | |
| `confidence` | float 0–1, opt | manual defaults to 1.0; auto = `mastitis_risk` |
| `reporter` | string, opt | |
| `reason` | string, opt | auto: top contributing signals |
| `notes` | string, opt | |
| `is_synthetic` | bool | |

Wording rule carried from the frontend review: a flag is a **watch‑list /
suspected** state, not a diagnosis. UI copy says "flagged for review", never
"ill".

## lying_bouts and resting_spots — real, backend‑cleaning

`lying_bouts.parquet` (real): `cow_id, start_utc, end_utc, duration_min, x_m, y_m, z_m, n_fixes, in_pen_frac`
— 1,462 bouts, 1,296 of them ≥ 20 min, in the centred UWB frame
(x −11.99..11.91, y −8.81..7.88).

`resting_spots.parquet` (real, derived): one row per cubicle‑level spot,
clusters of bout centres with ≤ 1.5 m linkage, dwell‑weighted centroid.

| column | type | notes |
|---|---|---|
| `spot_id` | string | `spot_01`… ordered by total dwell |
| `center_x_m`, `center_y_m` | float | centred UWB frame |
| `radius_m` | float | 1.5 |
| `n_bouts`, `n_cows` | int | over all bouts ≥ 20 min |
| `dwell_min` | float | total |
| `is_synthetic` | bool | False |

On the real data: 5 spots, four used by all 10 cows. The backtrace (spec §3.2)
assigns each bout to its spot; per‑bout circles are a rendering, not a resource.

## manual — farmer‑entered, per cow

| column | type | notes |
|---|---|---|
| `cow_id` | string | |
| `parity` | int | |
| `dim` | int | days in milk — MMCows has this daily in `milk` as `dim` |
| `pregnant` | bool | |
| `pregnancy_date` | date, opt | |
| `recorded_at` | timestamp UTC | |
| `is_synthetic` | bool | |

**Real version exists:** `backend-cleaning/data/processed/manual.parquet` is
derived from the farm event log (`sub_data/health_records`) — parity from
Freshen events, DIM cross‑checked against the farm's own counter, pregnancy
from the latest Preg Check. `source=derived_from_health_records`,
`is_synthetic=False`. Farmer‑entered rows, when they exist, override it.

## What MMCows already gives us (real, on `main`)

From `backend-cleaning/data/processed/joined_1min.parquet` (10 cows, 14 days,
1‑min): `cbt_c`, `lying`, `uwb_x_m/y_m/z_m`, `out_of_pen` (the milking trips —
the exclusion the brief asks for), `neck_imu_magnitude_mean/std`,
`collar_pressure_hpa`, `indoor_thi`, outdoor weather, daily `milk_yield_kg`
and `dim`, and ground‑truth `behavior_mode` on 2023‑07‑25. Native‑rate tables
in `data/interim/` (uwb 15 s, labels 1 s; 10 Hz IMU stays in raw CSV).

**Not in MMCows, so synthetic:** per‑visit milk, unit assignment and order,
sanitation, conductivity/SCC, mastitis cases, bedding changes. Health records
exist in `sub_data/health_records` (16 small files) and are being pulled.

## Backtrace windows and bounds

Set in `docs/backtrace_spec.md`. The investigation window is anchored at the
flagged cows' `onset_utc` (fallback `flagged_at`), never at `max(flagged_at) − 72 h`.
Resting successions stop at the next `bedding.changed_at`; milking successions
stop at the unit's next `sanitation.sanitized_at` and at the session boundary.
The synthetic sanitation table fires once per unit **after** each session, so it
never separates two cows milked in the same session.

## Answers from Aster (board, 2026‑11‑15)

1. Bedding per **zone** (`zone_id`), not whole barn — resting traces bounded per zone.
2. Milk: **per‑visit rows with `unit_id` / `stall_number`** — `milking_log` can be real, not synthetic.
3. Conductivity **per quarter** `cond_lf/lr/rf/rr` + `cond_max`.
4. Licence stated as CC‑BY‑4.0. (MMCows itself is CC BY‑NC‑SA 4.0; the two are not the same — keep the attributions separate in the README.)

## Original open questions (kept for the record)

1. Is bedding one `changed_at` series for the whole barn (brief assumption), or per pen?
2. Does the milk data have per‑visit rows with `unit_id`? If not, `milking_log` is fully synthetic and I will say so in every payload.
3. Conductivity per quarter or per cow?
4. Licence of each file — the track prompt forbids redistributing source data; placeholders only until confirmed.
