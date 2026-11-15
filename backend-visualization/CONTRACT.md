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
