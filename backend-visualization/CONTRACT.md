# backend-visualization: I/O Contract

Owner: @pauraque (Aster). This document defines the visualization-ready payload
contracts consumed by `frontend/` and produced by `backend-visualization/`.
Fully reconciled with `backend-cleaning/CONTRACT.md` and `backend-analysis/CONTRACT.md`.

## 1. Role Boundary & Responsibilities

In scope for `backend-visualization/`:
- Transforming cleaned timeseries tables from `backend-cleaning/` (`joined_1min.parquet`)
  and analysis outputs from `backend-analysis/` (`cow_risk_summary.json`, `benchmark_results.json`)
  into JSON view payloads for the dashboard.
- Preserving imputation metadata (`*_is_imputed` flags) and data age (`*_age_s`)
  so the frontend renders interpolated values and freshness transparently.
- Exposing modality health and missing-modality behavior so UI views degrade
  gracefully when channels (e.g. CBT, IMU, UWB) are unattached or offline (e.g. C11–C16).
- Preparing spatial overlays (barn zones, UWB coordinates in meters, out-of-pen milking states,
  and heatmaps) and multi-day physiological trajectories.

Not in scope (owned elsewhere):
- Raw ingestion, parsing, and time alignment — `backend-cleaning/`.
- Statistical modeling, baseline evaluation, feature training — `backend-analysis/` and `model/`.
- UI DOM rendering, styling, CSS, client-side button interactions — `frontend/`.
- External adapter connectors and protocol drivers — `apis/`.

---

## 2. Core Conventions & Guardrails

1. **Keys & Time:**
   - `cow_id`: Categorical string identifier (`"C01"` through `"C16"`).
   - `ts_utc`: ISO 8601 formatted UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`).
2. **Standard Units (SI):**
   - Milk yield: `milk_yield_kg` (kg of milk weight).
   - Temperatures: `cbt_c`, `indoor_temp_c` (°C).
   - Spatial: `uwb_x_m`, `uwb_y_m` (meters).
   - Accelerations: `neck_imu_magnitude_mean` (m/s²).
3. **State vs Missingness:**
   - `out_of_pen`: Boolean flag denoting daily milking trips out of the pen (~04–05h and 15–16h local).
     This is an explicit operational state, never filled across or treated as missing telemetry.
4. **Imputation Transparency:**
   - Any metric subject to forward-fill or aggregation carries a corresponding
     boolean flag `<col>_is_imputed` and `<col>_age_s` (seconds since real observation).
5. **No Clinical Diagnosis (Prompt Mandate):**
   - Wording is strictly monitoring, risk projection, and observation.
   - Categories: `"baseline"`, `"moderate_watch"`, `"priority_watch"`.
   - Score: `0` to `100`.
   - Every inference payload carries `"is_model_suggestion": true`.
6. **Synthetic / Mock Labeling:**
   - Any fixture or mock payload generated when running offline or in demo mode
     carries `"is_synthetic": true` and `"data_source": "mock | mmcows_cleaned"`.

---

## 3. Payload Specifications

### 3.1 Barn Overview Payload (`/api/barn-overview` or `barn_overview.json`)
Supplies cow locations, zone heatmaps, out-of-pen states, and barn ambient climate.

```json
{
  "ts_utc": "2023-07-28T14:00:00Z",
  "barn_id": "main_barn_01",
  "indoor_thi": 74.2,
  "indoor_temp_c": 26.8,
  "indoor_humidity_pct": 66.0,
  "is_synthetic": false,
  "cows": [
    {
      "cow_id": "C01",
      "display_name": "Fern (C01)",
      "uwb_x_m": 12.4,
      "uwb_y_m": 8.2,
      "zone": "cubicle_row_b",
      "activity_state": "resting",
      "out_of_pen": false,
      "risk_status": "priority_watch",
      "risk_score": 0.84,
      "factors": ["THI > 72", "CBT elevated +0.85C", "Milk drop 18%"],
      "on_watch_list": true,
      "vet_flagged": false,
      "is_instrumented": true,
      "missing_modalities": []
    }
  ],
  "zones": [
    {
      "zone_id": "cubicle_row_b",
      "zone_type": "resting",
      "cow_count": 6,
      "capacity": 15,
      "mean_idling_minutes": 42.0
    }
  ],
  "heatmap_grid": {
    "resolution_m": 1.5,
    "width": 20,
    "height": 10,
    "density_matrix": [[0.0, 0.2], [0.8, 0.1]]
  }
}
```

### 3.2 Cow Timeseries & Detail (`/api/cows/{cow_id}` or `cow_detail_{cow_id}.json`)
Supplies multi-day trajectories for temperature, activity, lying behavior, milk weight, and contact exposure.

```json
{
  "cow_id": "C01",
  "data_range": {
    "start_utc": "2023-07-21T12:30:00Z",
    "end_utc": "2023-07-28T14:00:00Z"
  },
  "summary": {
    "baseline_daily_milk_kg": 26.5,
    "current_daily_milk_kg": 21.8,
    "mean_cbt_c": 39.85,
    "cbt_anomaly_detected": true,
    "risk_category": "priority_watch"
  },
  "timeseries": [
    {
      "ts_utc": "2023-07-28T13:00:00Z",
      "cbt_c": 39.85,
      "cbt_c_is_imputed": false,
      "neck_imu_magnitude_mean": 1.15,
      "neck_imu_magnitude_mean_is_imputed": false,
      "daily_milk_yield_kg": 21.8,
      "daily_milk_yield_kg_is_imputed": true,
      "lying": 1,
      "indoor_thi": 74.2,
      "indoor_thi_is_imputed": false,
      "out_of_pen": false
    }
  ],
  "resting_history": [
    {
      "session_id": "rest_C01_01",
      "zone": "cubicle_row_b",
      "start_utc": "2023-07-28T09:30:00Z",
      "end_utc": "2023-07-28T12:00:00Z",
      "duration_minutes": 150
    }
  ],
  "co_resting_cows": [
    {
      "cow_id": "C02",
      "shared_zone": "cubicle_row_b",
      "overlap_minutes": 110,
      "last_shared_utc": "2023-07-28T12:00:00Z"
    }
  ]
}
```

### 3.3 Milking Stalls Status (`/api/milking-stalls` or `milking_stalls.json`)
Supplies parlor stall status, milk weight yields, and recent cow visits.

```json
{
  "ts_utc": "2023-07-28T14:00:00Z",
  "parlor_id": "parlor_alpha",
  "stalls": [
    {
      "stall_number": 1,
      "state": "active",
      "current_cow_id": "C01",
      "session_yield_kg": 12.2,
      "flow_rate_kg_min": 2.7,
      "last_completed_cycle": {
        "cow_id": "C03",
        "yield_kg": 13.8,
        "completed_at_utc": "2023-07-28T10:20:00Z",
        "flagged_risk": false
      }
    }
  ]
}
```

### 3.4 Watch List & Alerts (`/api/watch-list` or `watch_list.json`)
List of cows with elevated risk or vet flags, stating uncertainty and missing modalities.

```json
{
  "ts_utc": "2023-07-28T14:00:00Z",
  "items": [
    {
      "cow_id": "C01",
      "flag_type": "model_suggestion",
      "risk_category": "priority_watch",
      "watch_risk_score": 84.5,
      "watch_reason": "Sustained high CBT under elevated THI accompanied by 18% yield decrease",
      "confidence": 0.88,
      "modalities_present": ["cbt", "neck_imu", "indoor_env", "milk_yield", "ankle"],
      "modalities_missing": ["uwb"],
      "missing_modality_impact": "Location confidence lower; utilizing last-seen stall beacon",
      "recommended_action": "Check for heat abatement and udder inflammation prior to next cycle",
      "is_model_suggestion": true
    }
  ]
}
```

### 3.5 Cross-Validation Benchmarks Summary (`/api/benchmarks` or `benchmarks_summary.json`)
Directly reflects `backend-analysis/CONTRACT.md §4.2`: animal-disjoint cross-validation results comparing single-sensor baselines against the multimodal classifier.

```json
{
  "dataset": "MMCows Challenge 1",
  "evaluation_protocol": "GroupKFold by cow_id (zero animal leakage)",
  "n_groups": 10,
  "n_splits": 5,
  "baselines": {
    "thi_threshold_baseline": {
      "description": "Environmental rule: Alert when THI >= 68.0",
      "roc_auc_mean": 0.612,
      "roc_auc_std": 0.048
    },
    "cbt_threshold_baseline": {
      "description": "Single-sensor physiological rule: Alert when CBT >= 39.3C",
      "roc_auc_mean": 0.724,
      "roc_auc_std": 0.039
    }
  },
  "multimodal_model": {
    "description": "Multimodal feature-weighted classifier (Thermal + IMU + Env + Production)",
    "roc_auc_mean": 0.887,
    "roc_auc_std": 0.028
  },
  "multimodal_lift_over_env_baseline_auc": 0.275,
  "multimodal_lift_over_cbt_baseline_auc": 0.163
}
```

### 3.6 Integration Feasibility (`/api/integrations` or `integrations_feasibility.json`)
Exposes system modularity, capability profiles, and cost metrics for small-farm decision support.

```json
{
  "systems": [
    {
      "adapter_id": "collar_imu_vital",
      "name": "Neck IMU Activity & Rumination",
      "attached": true,
      "cadence": "10Hz_aggregated_1m",
      "annual_cost_per_head_usd": 35.0,
      "feasibility_tier": "recommended",
      "signals": ["accel_mps2", "mag_uT", "kinetic_activity_index"],
      "is_synthetic": true
    }
  ]
}
```

### 3.7 2D Pen Map (`/api/pen-map` or `pen_map.json`)
Visualizes pen layout, resting density heatmap generated from lying bouts (duration >= 20 min), real-coordinate 1.5m resting circles bounded by bedding change cutoff, contact event overlays, flagged cows, and exposed cows shaded by continuous exposure score.

```json
{
  "ts_utc": "2023-07-28T14:00:00Z",
  "barn_id": "main_barn_01",
  "pen_id": "pen_01",
  "grid": {
    "width_m": 30.0,
    "height_m": 15.0,
    "cell_size_m": 1.0,
    "heatmap": [[0.0, 0.65], [0.85, 0.0]]
  },
  "cows": [
    {
      "cow_id": "C01",
      "display_name": "Fern (C01)",
      "uwb_x_m": 12.4,
      "uwb_y_m": 8.2,
      "zone": "cubicle_row_b",
      "activity_state": "resting",
      "out_of_pen": false,
      "flag_status": "flagged",
      "exposure_score": 0.92,
      "exposure_tier": "priority_watch",
      "is_source_candidate": true
    }
  ],
  "implicated_elements": {
    "grid_cells": [{"x": 12, "y": 10, "risk_density": 0.88}],
    "milking_units": ["unit_04"],
    "resting_zones": ["cubicle_row_b"]
  },
  "resting_areas": [
    {
      "area_id": "rest_circle_01",
      "center_x_m": 12.4,
      "center_y_m": 10.2,
      "radius_m": 1.5,
      "zone_id": "cubicle_row_b",
      "target_cow_id": "C01",
      "target_cows": ["C01"],
      "until_bedding_change_utc": "2023-07-29T08:15:00Z",
      "contact_cows": ["C02", "C07"],
      "cumulative_shed_duration_min": 140.0,
      "n_contacts": 2
    }
  ],
  "implicated_circles": [
    {
      "center_x_m": 12.4,
      "center_y_m": 10.2,
      "radius_m": 1.5,
      "target_cow_id": "C01",
      "contact_cows": ["C02", "C07"],
      "until_bedding_change_utc": "2023-07-29T08:15:00Z"
    }
  ],
  "contact_events": [
    {
      "event_id": "contact_event_01",
      "shedding_cow": "C01",
      "exposed_cow": "C02",
      "center_x_m": 12.4,
      "center_y_m": 10.2,
      "radius_m": 1.5,
      "source_time": "2023-07-26T10:15:00Z",
      "exposed_time": "2023-07-26T14:30:00Z",
      "hours_since_shedding": 4.25,
      "exposure_score": 0.78
    }
  ],
  "is_synthetic": false
}
```

### 3.8 Herd Health & Vitality Table (`/api/herd-health` or `herd_health.json`)
Displays herd-wide cows with 0–100 health vitality index, acute mastitis risk split into rule vs anomaly components, cold-start baseline tier, active watch-list flags, and aggregate herd group trends.

```json
{
  "ts_utc": "2023-07-28T14:00:00Z",
  "cows": [
    {
      "cow_id": "C01",
      "health_index": 58.5,
      "health_breakdown": {
        "thermal_vitality": 18.0,
        "rumination_vitality": 14.0,
        "activity_vitality": 16.5,
        "production_vitality": 10.0
      },
      "mastitis_risk": 82.4,
      "risk_components": {
        "rule_score": 88.0,
        "anomaly_score": 74.0,
        "top_contributing_signals": ["conductivity_spike_quarter_rf", "cbt_elevation", "milk_yield_drop"]
      },
      "baseline_tier": "own_history",
      "baseline_confidence": 0.95,
      "active_flag": {
        "flag_id": "auto_C01_20230728",
        "source": "auto",
        "type": "suspected",
        "quarter": "RF",
        "confidence": 0.824,
        "reason": "Quarter conductivity elevation (6.2 mS/cm) and CBT increase",
        "status": "active"
      },
      "is_synthetic": false
    }
  ],
  "group_trends": {
    "cohort_size": 16,
    "mean_health_index": 82.4,
    "mean_mastitis_risk": 22.8,
    "watch_counts": {
      "priority_watch": 1,
      "moderate_watch": 1,
      "baseline": 14
    },
    "route_exposure_summary": {
      "resting_contact_cows_count": 2,
      "milking_contact_cows_count": 1
    },
    "daily_trends": [
      {"date": "2023-07-26", "mean_health_index": 86.2, "flagged_count": 1},
      {"date": "2023-07-27", "mean_health_index": 84.1, "flagged_count": 1},
      {"date": "2023-07-28", "mean_health_index": 82.4, "flagged_count": 1}
    ]
  },
  "is_synthetic": false
}
```
    {
      "cow_id": "C01",
      "health_index": 58.5,
      "health_breakdown": {
        "thermal_vitality": 18.0,
        "rumination_vitality": 14.0,
        "activity_vitality": 16.5,
        "production_vitality": 10.0
      },
      "mastitis_risk": 82.4,
      "risk_components": {
        "rule_score": 88.0,
        "anomaly_score": 74.0,
        "top_contributing_signals": ["conductivity_spike_quarter_rf", "cbt_elevation", "milk_yield_drop"]
      },
      "baseline_tier": "own_history",
      "baseline_confidence": 0.95,
      "active_flag": {
        "flag_id": "auto_C01_20230728",
        "source": "auto",
        "type": "suspected",
        "quarter": "RF",
        "confidence": 0.824,
        "reason": "Quarter conductivity elevation (6.2 mS/cm) and CBT increase",
        "status": "active"
      },
      "is_synthetic": false
    }
  ],
  "is_synthetic": false
}
```

### 3.9 Outbreak Transmission Attribution Panel (`/api/attribution`, `POST /backtrace`, or `attribution.json`)
Exposes backtrace transmission attribution comparing resting cubicles vs milking machine contact, permutation test p-values, implicated source, real-coordinate 1.5m resting circles, and non-clinical pathogen group likelihood.

Supports `POST /backtrace` and `POST /api/backtrace` accepting frontend manual flags (`flags: [{cow_id, timestamp}]` or `animal_ids: [...]`) and `lookback_hours: 72`, returning dynamic attribution and economic impact.

```json
{
  "ts_utc": "2023-07-28T14:00:00Z",
  "lookback_hours": 72,
  "likely_route": "resting_area",
  "likely_route_alias": "resting_cubicle_route",
  "route_probabilities": {
    "resting_area": 0.78,
    "milking_equipment": 0.18,
    "both": 0.0,
    "no_common_route": 0.04
  },
  "p_values": {
    "resting_permutation_p": 0.008,
    "milking_permutation_p": 0.24
  },
  "transmission_source": {
    "type": "resting_zone",
    "identifier": "cubicle_row_b",
    "primary_index_cow": "C01",
    "bedding_window_start_utc": "2023-07-25T08:30:00Z",
    "shared_hours_prior": 14.5
  },
  "implicated_resting_areas": [
    {
      "area_id": "rest_circle_01",
      "center_x_m": 12.4,
      "center_y_m": 10.2,
      "radius_m": 1.5,
      "zone_id": "cubicle_row_b",
      "target_cow_id": "C01",
      "target_cows": ["C01"],
      "until_bedding_change_utc": "2023-07-29T08:15:00Z",
      "contact_cows": ["C02", "C07"],
      "cumulative_shed_duration_min": 140.0,
      "n_contacts": 2
    }
  ],
  "resting_areas": [
    {
      "area_id": "rest_circle_01",
      "center_x_m": 12.4,
      "center_y_m": 10.2,
      "radius_m": 1.5,
      "zone_id": "cubicle_row_b",
      "target_cow_id": "C01",
      "target_cows": ["C01"],
      "until_bedding_change_utc": "2023-07-29T08:15:00Z",
      "contact_cows": ["C02", "C07"],
      "cumulative_shed_duration_min": 140.0,
      "n_contacts": 2
    }
  ],
  "contact_cows": ["C02", "C07"],
  "pathogen_group_likelihood": {
    "coliform_environmental_gram_negative": 0.76,
    "streptococci_environmental_gram_positive": 0.18,
    "contagious_staph_aureus": 0.06,
    "statement": "Environmental transmission pattern consistent with coliform/environmental challenge in resting area. Not a clinical diagnosis."
  },
  "recommended_actions": [
    "Immediate bedding cleanout and lime dressing in cubicle_row_b stalls 4-8",
    "Verify teat pre-dip coverage and contact time prior to unit attachment",
    "Segregate C01 milking order to end of session"
  ],
  "impact": {
    "total_affected_cows": 3,
    "flagged_early_count": 1,
    "mean_lead_time_hours": 18.5,
    "estimated_milk_saved_kg": 142.0,
    "transmission_prevented_cases_est": 2.4,
    "estimated_savings_usd": 4200.0,
    "clean_up_cost_usd": 650.0,
    "roi_ratio": 6.46,
    "early_detection_rate_pct": 66.7,
    "is_synthetic": false
  },
  "is_model_suggestion": true,
  "is_synthetic": false
}
```

### 3.10 Mitigation & Economic Impact Panel (`/api/impact` or `impact.json`)
Quantifies early detection lead time and prevented cross-contamination impact.

```json
{
  "ts_utc": "2023-07-28T14:00:00Z",
  "cohort_size": 16,
  "total_affected_cows": 3,
  "flagged_early_count": 2,
  "early_detection_rate_pct": 66.7,
  "mean_lead_time_hours": 18.5,
  "estimated_milk_saved_kg": 142.0,
  "transmission_prevented_cases_est": 2.4,
  "is_synthetic": false
}
```

---

## 4. Placeholder Datasets (`data/placeholder/`)

Shipped as deterministic fixtures (`is_synthetic: true`) adhering to `docs/data_contracts.md`:
1. `bedding.json`: Bedding refresh intervals per `zone_id` bounding resting exposure windows.
2. `milk.json`: Per-milking visit records with `unit_id`, `stall_number`, quarter conductivity (`cond_lf`, `cond_lr`, `cond_rf`, `cond_rr`, `cond_max`), and `scc_kcells_ml`.
3. `milking_log.json`: Visit sequence ordering per milking stall session.
4. `sanitation.json`: Milking stall disinfection timestamps.

