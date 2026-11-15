# backend-analysis: I/O Contract and Metric Definitions

Owner: @equan04 — of `backend-analysis/` only.
Consumers: `backend-visualization/` (@pauraque) and `frontend/` (@uiobio).

This document specifies the contracts, input expectations, output schemas, metric definitions, and evaluation guarantees provided by the `backend-analysis/` pipeline for Challenge 1 (MMCows).

---

## 1. Input Data Contract

Analysis consumes the canonical processed joined table produced by `backend-cleaning/`:
- **File**: `backend-cleaning/data/processed/joined_1min.parquet` (+ `joined_1min.schema.json`)
- **Cadence**: 1-minute rows, keyed by `cow_id` (`C01`–`C10`, string categorical) + `ts_utc` (tz-aware UTC timestamp).
- **Core Input Fields**:
  - `cbt_c`: Core body temperature in °C.
  - `indoor_temp_c`, `indoor_rh_pct`, `indoor_thi`: Barn-level environmental metrics.
  - `neck_imu_magnitude_mean`, `neck_imu_magnitude_std`: 1-minute neck IMU acceleration magnitude ($|\vec{a}|$) in $\text{m/s}^2$.
  - `milk_yield_kg`, `dim`: Daily milk weight in kg and days in milk.
  - `lying`: Ankle sensor binary indicator ($0$ = standing/walking, $1$ = lying).
  - `out_of_pen`: Boolean flag denoting scheduled milking excursion trips (04–05h and 15–16h local), where coordinate nulls represent a known state rather than missing sensor data.
  - `<col>_is_imputed`, `<col>_age_s`: Missingness and staleness tracking flags.
- **Optional External Physiology & Nutrition Inputs** (e.g. Mendeley `doi:10.17632/954f6g36sb.2` or commercial vendor telemetry; optional pass-through, MMCows pipeline remains completely self-contained when absent):
  - `rectal_temp_c`: Alternative core body temperature in °C (serves as fallback for CBT strain when `cbt_c` is absent).
  - `respiration_rate_bpm`, `pulse_rate_bpm`: Physiological respiration and pulse rate in breaths/beats per minute.
  - `dmi_kg`: Daily dry matter intake in kg.
  - `milk_fat_pct`, `milk_protein_pct`, `milk_lactose_pct`: Milk solids composition percentages (aliases: `fat_pct`, `protein_pct`, `lactose_pct`).

---

## 2. Core Principles & Non-Clinical Framing

1. **Non-Diagnostic Monitoring & Risk Scoring Only**:
   Per the challenge prompt and team agreement, the system produces **monitoring and risk prediction metrics** only. It **never declares or outputs unsupported clinical diagnoses** (such as "mastitis", "ill", or clinical disease entities).
   - Valid labels: `baseline`, `moderate_watch`, `priority_watch`.
   - Score range: `watch_risk_score` from `0` to `100`.
   - Every inference payload includes an advisory flag: `"is_model_suggestion": true`.

2. **Zero Leakage Evaluation Guarantee**:
   All evaluation metrics and baseline comparisons enforce animal-disjoint group splitting:
   - Data is partitioned by `cow_id` via `cleaning.splits.group_kfold(df, by="cow_id", n_splits=5, seed=0)`.
   - Repeated observations for a cow never span train and test sets.
   - Evaluated across $K$-fold animal cross-validation, reporting mean $\pm$ standard deviation.

3. **Explicit Uncertainty & Missing-Modality Handling**:
   - Missing channels degrade confidence gracefully rather than producing errors or silent assumptions.
   - Every risk output carries a `confidence_score` ($0.0 \le c \le 1.0$) and an inventory of `modalities_present` vs `missing_modalities`.

---

## 3. Metric Definitions

### 3.1 Temperature-Humidity Index (THI) & Thermal Load
- **THI Formula** (NRC / Thom standard):
  $$\text{THI} = (1.8 \times T + 32) - (0.55 - 0.0055 \times \text{RH}) \times (1.8 \times T - 26)$$
  where $T$ is dry-bulb ambient temperature in °C, and $\text{RH}$ is relative humidity in %.
- **Thermal Strain Categories**:
  - `comfort`: $\text{THI} < 68.0$
  - `mild_strain`: $68.0 \le \text{THI} < 72.0$
  - `moderate_strain`: $72.0 \le \text{THI} < 79.0$
  - `severe_strain`: $\text{THI} \ge 79.0$
- **Cumulative Thermal Load (Degree-Hours)**:
  $$\text{CTL} = \sum_{t \in W} \max(0, \text{THI}(t) - 68.0) \times \Delta t_{\text{hours}}$$

### 3.2 Core Body Temperature (CBT) Strain
- Normal physiological CBT range: $38.5^\circ\text{C} - 39.2^\circ\text{C}$.
- **CBT Strain Score ($0 - 40$ points)**:
  - If $\text{CBT} \le 39.2^\circ\text{C}$: Strain = 0
  - If $39.2^\circ\text{C} < \text{CBT} \le 40.0^\circ\text{C}$: Linear scale from 0 to 30 points
  - If $\text{CBT} > 40.0^\circ\text{C}$: Scaled up to 40 points (elevated thermal strain)

### 3.3 Behavioral Activity & Posture Metrics
- Computed from 1-minute aggregated neck IMU components (`neck_imu_magnitude_std`), ankle lying sensor (`lying`), and trained Random Forest behavior classifier predictions (`behavior`, `behavior_name`, `prob`) from `model/behavior`:
  - **Kinetic Activity Index**:
    $$\text{activity\_index} = \sigma_{|\vec{a}|}$$
  - **Posture State**:
    - `resting`: $\text{activity\_index} < \tau_{\text{rest}}$ or `lying == 1` or classified `lying` (code 7)
    - `active`: $\text{activity\_index} \ge \tau_{\text{rest}}$ or classified active states (1 walking, 2 standing, 3 feed_up, 4 feed_down, 5 licking, 6 drinking)
  - **Trained Behavior Classifier Durations (`cow_day_features.parquet`)**:
    Aggregates verified daily durations across the MMCows 8-class vocabulary:
    - `clf_lying_time_min`: Total daily recumbent rest duration.
    - `clf_standing_time_min`: Total daily upright standing duration.
    - `clf_walking_time_min`: Total daily walking locomotion duration.
    - `clf_feed_up_time_min` / `clf_feed_down_time_min`: Total daily head-up / head-down bunk visits.
    - `clf_feeding_time_min`: Total daily feeding duration (sum of feed_up + feed_down).
    - `clf_drinking_time_min` / `clf_licking_time_min`: Total daily hydration and grooming duration.
    If classifier columns are absent, these fields degrade gracefully to `None` preserving backward compatibility.
  - **Ground Truth Validation**: Pristine `behavior_mode` in 2023-07-25 ground-truth windows remains unaltered as the validation target, computing `behavior_classifier_ground_truth_concordance` (overall accuracy, lying F1 score).
  - **No Synthetic Rumination**: MMCows contains no ground-truth annotations for rumination; ungrounded synthetic rumination proxies are explicitly deprecated in favor of verified lying and feeding duration deviations.

### 3.4 Multimodal Watch-List Risk Score ($0 - 100$)
Composite weighted score reflecting multi-system deviation:
$$\text{watch\_risk\_score} = S_{\text{thermal}} + S_{\text{behavior}} + S_{\text{production}} + S_{\text{movement}}$$
- **Thermal component ($S_{\text{thermal}}$, max 40)**: From CBT elevation and THI exposure.
- **Behavioral component ($S_{\text{behavior}}$, max 30)**: From profound kinetic lethargy ($< 0.15\text{ m/s}^2$ outside rest), acute kinetic agitation/restlessness ($> 0.85\text{ m/s}^2$, calibrated to empirical p90), and recumbent rest deficits.
- **Production component ($S_{\text{production}}$, max 20)**: From sudden milk yield deviation below rolling baseline.
- **Movement / Spatial component ($S_{\text{movement}}$, max 10)**: Prolonged displacement from comfort/ventilation zones, respecting `out_of_pen` milking trips.

### 3.5 Dairy Health Vitality Index ($0 - 100$)
Comprehensive welfare index aggregating 4 orthogonal physiological vitality components (each $0 - 25$ points, strictly summing to $100$):
$$\text{health\_index} = V_{\text{thermal}} + V_{\text{behavior}} + V_{\text{activity}} + V_{\text{production}}$$
- **Thermal Vitality ($V_{\text{thermal}}$, max 25)**: Starts at 25 points, penalized by CBT fever elevation ($z_{\text{cbt}} > 0$, up to 25 pt penalty).
- **Behavior & Rest Vitality ($V_{\text{behavior}}$, max 25)**: Starts at 25 points, penalized by abnormal lying duration drop below baseline ($z_{\text{lying}} < 0$, up to 15 pt penalty) or depressed feeding duration ($z_{\text{feed}} < 0$, up to 10 pt penalty). Derived strictly from empirical ankle lying and classifier durations (`clf_lying_time_min`, `clf_feeding_time_min`).
- **Activity & Kinetic Vitality ($V_{\text{activity}}$, max 25)**: Starts at 25 points, penalized by profound kinetic lethargy ($z_{\text{act}} < -1.0$) or extreme restlessness ($z_{\text{act}} > 2.5$).
- **Production Vitality ($V_{\text{production}}$, max 25)**: Starts at 25 points, penalized by milk yield drop below rolling baseline ($z_{\text{yield}} < 0$, up to 25 pt penalty).
- **Vitality Tiers**:
  - `thriving`: $\text{health\_index} \ge 85.0$
  - `stable_monitoring`: $65.0 \le \text{health\_index} < 85.0$
  - `moderate_strain`: $45.0 \le \text{health\_index} < 65.0$
  - `acute_attention`: $\text{health\_index} < 45.0$

---

## 4. Output Schemas (Consumed by Visualization & Frontend)

### 4.1 Cow Risk Summary Schema (`cow_risk_summary.json`)
Dictionary keyed by `cow_id`:
```json
{
  "cow_id": "C01",
  "latest_ts_utc": "2023-07-25T14:30:00Z",
  "watch_risk_score": 74.5,
  "risk_category": "priority_watch",
  "confidence_score": 0.92,
  "health_index": 72.5,
  "vitality_tier": "stable_monitoring",
  "vitality_components": {
    "thermal_vitality": 18.0,
    "behavior_vitality": 17.5,
    "activity_vitality": 19.0,
    "production_vitality": 18.0
  },
  "acute_mastitis_risk": 34.2,
  "mastitis_rule_score": 38.0,
  "mastitis_anomaly_score": 28.5,
  "mastitis_top_signals": [
    "Daily Milk Yield Kg depressed (z=-1.4)"
  ],
  "baseline_tier": "own_history",
  "baseline_confidence": 0.92,
  "metrics": {
    "cbt_c": 39.85,
    "cbt_strain_score": 26.2,
    "ambient_thi": 74.1,
    "thi_category": "moderate_strain",
    "activity_index": 0.12,
    "posture_state": "resting",
    "daily_milk_yield_kg": 28.4,
    "milk_drop_pct": 14.2,
    "out_of_pen": false,
    "is_stationary_hardware": false
  },
  "modalities_present": ["cbt", "indoor_env", "neck_imu", "milk_yield", "uwb"],
  "missing_modalities": [],
  "contributing_factors": [
    "CBT elevated (39.85°C)",
    "THI indicates heat stress (74.1)"
  ],
  "recommended_actions": [
    "Verify barn fan and misting operation in resting stalls",
    "Inspect water availability and intake",
    "Queue for closer observation at next milking"
  ],
  "is_model_suggestion": true,
  "is_synthetic": false
}
```

### 4.2 Auto-Flags Schema (`auto_flags.json`)
List of triggered auto-flags when `acute_mastitis_risk >= 70.0`:
```json
[
  {
    "cow_id": "C02",
    "flag_type": "auto_mastitis_watch",
    "risk_score": 78.4,
    "rule_score": 75.0,
    "anomaly_score": 83.5,
    "threshold": 70.0,
    "top_contributing_signals": [
      "Conductivity Max elevated (z=+3.2)",
      "Daily Milk Yield Kg depressed (z=-2.8)",
      "Cbt Mean elevated (z=+2.6)"
    ],
    "recommended_actions": [
      "Perform California Mastitis Test (CMT) & foremilk check at next milking",
      "Inspect udder quarter swelling, heat, or abnormal milk consistency",
      "Log observation in farm health event records"
    ],
    "is_model_suggestion": true
  }
]
```

### 4.3 Benchmark Results Schema (`benchmark_results.json`)
Results of animal-disjoint group cross-validation comparing single-sensor baselines against the multimodal predictor.
The `evaluation_protocol` explicitly distinguishes `group_kfold_K (n=N)`, `leave_one_animal_out (n=N)`, or `insufficient_animals_for_cv (n=N)`:
```json
{
  "dataset": "MMCows Challenge 1",
  "evaluation_protocol": "group_kfold_5 (n=10)",
  "n_groups": 10,
  "n_splits": 5,
  "cv_unavailable": false,
  "is_synthetic": false,
  "baselines": {
    "thi_threshold_baseline": {
      "description": "Classical environmental rule: Alert when THI >= 68.0",
      "roc_auc_mean": 0.612,
      "roc_auc_std": 0.048,
      "balanced_accuracy_mean": 0.584,
      "balanced_accuracy_std": 0.052,
      "f1_mean": 0.541,
      "f1_std": 0.061
    },
    "cbt_threshold_baseline": {
      "description": "Single-sensor physiological rule: Alert when CBT >= 39.3°C",
      "roc_auc_mean": 0.724,
      "roc_auc_std": 0.039,
      "balanced_accuracy_mean": 0.701,
      "balanced_accuracy_std": 0.044,
      "f1_mean": 0.683,
      "f1_std": 0.051
    }
  },
  "multimodal_model": {
    "description": "Multimodal feature-weighted classifier (Thermal + IMU + Env + Production)",
    "roc_auc_mean": 0.887,
    "roc_auc_std": 0.028,
    "balanced_accuracy_mean": 0.835,
    "balanced_accuracy_std": 0.033,
    "f1_mean": 0.822,
    "f1_std": 0.037
  },
  "multimodal_lift_over_env_baseline_auc": 0.275,
  "multimodal_lift_over_cbt_baseline_auc": 0.163
}
```

### 4.4 Backtrace Result Schema (`backtrace()` / `POST /backtrace`)
Returned by `analysis.backtrace(flags, lookback_hours=72)` and consumed by `apis/` and dashboard attribution panels.

#### Route Attribution Vocabulary (Aligned with `cleaning/synth.py:make_cases` `true_route`)
- **Canonical Vocabulary**:
  - `"resting_area"`: Statistically significant spatial cubicle co-occupancy clustering ($p < 0.05$).
  - `"milking_equipment"`: Statistically significant un-sanitized serial milking stall contacts ($p < 0.05$).
  - `"both"`: Both resting and milking routes exhibit statistically significant clustering ($p < 0.05$).
  - `"no_common_route"`: No statistically significant transmission clustering ($p \ge 0.05$).
- **Legacy Aliases (provided via `likely_route_alias` and `analysis.backtrace.CANONICAL_TO_LEGACY_ROUTES`)**:
  - `"resting_area"` $\leftrightarrow$ `"resting_environment"`
  - `"milking_equipment"` $\leftrightarrow$ `"milking_equipment"`
  - `"both"` $\leftrightarrow$ `"mixed_transmission"`
  - `"no_common_route"` $\leftrightarrow$ `"sporadic_inconclusive"`

```json
{
  "investigation_id": "trace_20230725_143000",
  "generated_at_utc": "2023-07-25T14:30:00Z",
  "lookback_hours": 72,
  "flagged_cows": ["C02", "C01"],
  "likely_route": "milking_equipment",
  "likely_route_alias": "milking_equipment",
  "route_p_values": {
    "resting_p_value": 0.35,
    "milking_p_value": 0.025
  },
  "p_values": {
    "resting_route": 0.35,
    "milking_equipment": 0.025
  },
  "pathogen_group_likelihood": {
    "contagious_milking_associated": 0.85,
    "environmental_bedding_associated": 0.15,
    "note": "Significant un-sanitized serial milking stall contacts; typical of contagious pathogens (e.g. Staph aureus)"
  },
  "implicated_units_or_cells": ["STALL-01"],
  "implicated_resting_areas": [],
  "implicated_circles": [],
  "implicated_resources": {
    "primary_unit_or_cell": "STALL-01",
    "all": ["STALL-01"],
    "resting_areas": []
  },
  "exposed_cows": [
    {
      "cow_id": "C03",
      "combined_exposure_score": 0.72,
      "resting_exposure_score": 0.10,
      "milking_exposure_score": 0.69,
      "primary_route": "milking_equipment",
      "contact_adjusted_risk": 46.8,
      "recommended_preventative_action": "Sanitize teat cluster before attaching; inspect teat end condition"
    }
  ],
  "high_risk_contacts": [
    {
      "cow_id": "C03",
      "combined_exposure_score": 0.72,
      "resting_exposure_score": 0.10,
      "milking_exposure_score": 0.69,
      "primary_route": "milking_equipment",
      "contact_adjusted_risk": 46.8,
      "recommended_preventative_action": "Sanitize teat cluster before attaching; inspect teat end condition"
    }
  ],
  "recommended_actions": [
    "Inspect teat cup liner condition and vacuum stability on implicated milking units",
    "Enforce automatic cluster backflush / hot water acid disinfection between milkings",
    "Enforce strict individual teat drying towels and pre-milking teat dip contact time"
  ],
  "is_model_suggestion": true,
  "is_synthetic": false
}
```

### 4.5 S11 Outbreak Backtrace Benchmark Schema (`backtrace_benchmark.json`)
Produced by `analysis.evaluate_backtrace_against_synthetic()`:
```json
{
  "benchmark_protocol": "S11 Outbreak Backtrace & Route Attribution Benchmark",
  "evaluated_at_utc": "2026-11-15T06:30:00Z",
  "total_episodes": 3,
  "route_accuracy": 1.0,
  "source_hit_rate": 1.0,
  "overall_precision_at_1": 1.0,
  "overall_recall_at_1": 1.0,
  "episodes": [
    {
      "scenario": "resting_route",
      "true_route": "resting_area",
      "predicted_route": "resting_area",
      "route_match": true,
      "p_values": {
        "resting_route": 0.01,
        "milking_equipment": 0.35
      },
      "source_hit": true,
      "true_source": {"cells": [[2, 1]], "cell_id": "cubicle_row_a:cell_X2_Y1"},
      "implicated_sources": ["cubicle_row_a:cell_X2_Y1"],
      "index_cow": "C02",
      "secondary_cows": ["C01"],
      "precision_at_k": {"1": 1.0, "2": 0.5, "3": 0.33},
      "recall_at_k": {"1": 1.0, "2": 1.0, "3": 1.0}
    }
  ],
  "is_synthetic": true
}
```

## 5. Parquet Schema Sidecars & Export Bundles (`.schema.json`, `backtrace_result.json`)
Every generated Parquet dataset ships an accompanying `.schema.json` sidecar matching the canonical `backend-cleaning` CONTRACT:
- `analyzed_timeseries.schema.json`: Documents cadence (`1m`), primary keys (`cow_id`, `ts_utc`), row count, and per-column dtypes and null counts.
- `cow_day_features.schema.json`: Documents cadence (`1d`), primary keys (`cow_id`, `date`), row count, and per-column dtypes and null counts.

Additionally, pipeline execution exports `backtrace_result.json` (adhering to Schema §4.4) for direct ingestion by `backend-visualization/visualization/data_loader.py` to prevent synthetic fallback across pen-map, attribution, and impact endpoints.
