# backend-visualization: I/O Contract

Owner: @pauraque (Aster). This document defines the visualization-ready payload
contracts consumed by `frontend/` and produced by `backend-visualization/`.

## 1. Role Boundary & Responsibilities

In scope for `backend-visualization/`:
- Transforming cleaned timeseries tables from `backend-cleaning/` and analysis
  aggregations from `backend-analysis/` into JSON-ready view payloads.
- Preserving imputation metadata (`x_is_imputed` flags) so the frontend renders
  interpolated or filled values transparently.
- Exposing modality health and missing-modality behavior so UI views degrade
  gracefully when channels (e.g. CBT, IMU, UWB) are unattached or offline.
- Preparing spatial overlays (barn zones, cow positions, heatmaps) and temporal
  trajectories for the frontend charts.

Not in scope (owned elsewhere):
- Raw ingestion, parsing, and time alignment — `backend-cleaning/`.
- Statistical modeling, baseline evaluation, feature training — `backend-analysis/` and `model/`.
- UI DOM rendering, styling, CSS, client-side button interactions — `frontend/`.
- External adapter connectors and protocol drivers — `apis/`.

---

## 2. Core Conventions & Guardrails

1. **Keys & Time:**
   - `cow_id`: Categorical string identifier (e.g. `"Fern_221"`, `"Cow_01"`).
   - `ts_utc`: ISO 8601 formatted UTC timestamp with timezone offset (`YYYY-MM-DDTHH:MM:SSZ`).
2. **Imputation Transparency:**
   - Any metric subject to forward-fill or interpolation carries a corresponding
     boolean flag `*_is_imputed`. The UI uses this to display dotted lines, muted
     markers, or disclaimer badges.
3. **No Clinical Diagnosis (Prompt Mandate):**
   - Wording is strictly monitoring, risk projection, and observation.
   - Allowed terms: `"elevated_risk"`, `"watch_list"`, `"within_baseline"`, `"temperature_anomaly"`.
   - Forbidden in payloads: `"diagnosed"`, `"illness"`, `"sick"`, `"mastitis_confirmed"`.
4. **Synthetic / Mock Labeling:**
   - Any fixture or mock payload generated when running offline or in demo mode
     carries `"is_synthetic": true` and a `"data_source": "mock | mmcows_cleaned"`.

---

## 3. Payload Specifications

### 3.1 Barn Overview Payload (`/api/barn-overview` or `barn_overview.json`)
Supplies cow locations, zone heatmaps, and barn ambient climate for spatial mapping.

```json
{
  "ts_utc": "2026-07-25T14:00:00Z",
  "barn_id": "main_barn_01",
  "indoor_thi": 74.2,
  "indoor_temp_c": 26.5,
  "indoor_humidity_pct": 68.0,
  "is_synthetic": false,
  "cows": [
    {
      "cow_id": "Fern_221",
      "x_coord": 14.2,
      "y_coord": 8.5,
      "zone": "cubicle_row_b",
      "activity_state": "resting",
      "risk_status": "elevated",
      "risk_score": 0.78,
      "factors": ["THI > 72", "CBT elevated +0.8C"],
      "on_watch_list": true,
      "vet_flagged": false,
      "missing_modalities": []
    }
  ],
  "zones": [
    {
      "zone_id": "cubicle_row_b",
      "zone_type": "resting",
      "cow_count": 6,
      "capacity": 10,
      "mean_idling_minutes": 42.0
    }
  ],
  "heatmap_grid": {
    "resolution_m": 1.0,
    "width": 30,
    "height": 20,
    "density_matrix": [[0.0, 0.2], [0.8, 0.1]]
  }
}
```

### 3.2 Cow Timeseries & Detail (`/api/cows/{cow_id}` or `cow_detail_{cow_id}.json`)
Supplies multi-day trajectories for temperature, activity, milk yield, and contact exposure.

```json
{
  "cow_id": "Fern_221",
  "data_range": {
    "start_utc": "2026-07-18T00:00:00Z",
    "end_utc": "2026-07-25T14:00:00Z"
  },
  "summary": {
    "baseline_daily_milk_l": 32.5,
    "current_daily_milk_l": 26.8,
    "mean_cbt_c": 39.4,
    "cbt_anomaly_detected": true,
    "status": "elevated_risk"
  },
  "timeseries": [
    {
      "ts_utc": "2026-07-25T13:00:00Z",
      "cbt_c": 39.6,
      "cbt_c_is_imputed": false,
      "neck_imu_magnitude_mean": 1.25,
      "neck_imu_magnitude_mean_is_imputed": false,
      "daily_milk_yield_l": 26.8,
      "daily_milk_yield_l_is_imputed": true,
      "indoor_thi": 74.0,
      "indoor_thi_is_imputed": false
    }
  ],
  "resting_history": [
    {
      "session_id": "rest_904",
      "zone": "cubicle_row_b",
      "start_utc": "2026-07-25T10:15:00Z",
      "end_utc": "2026-07-25T12:30:00Z",
      "duration_minutes": 135
    }
  ],
  "co_resting_cows": [
    {
      "cow_id": "Poppy_164",
      "shared_zone": "cubicle_row_b",
      "overlap_minutes": 110,
      "last_shared_utc": "2026-07-25T12:30:00Z"
    }
  ]
}
```

### 3.3 Milking Stalls Status (`/api/milking-stalls` or `milking_stalls.json`)
Supplies parlor and stall efficiency, yield tracking, and recent cow traffic.

```json
{
  "ts_utc": "2026-07-25T14:00:00Z",
  "parlor_id": "parlor_alpha",
  "stalls": [
    {
      "stall_number": 1,
      "state": "active",
      "current_cow_id": "Daisy_108",
      "session_yield_l": 14.2,
      "flow_rate_l_min": 3.1,
      "last_completed_cycle": {
        "cow_id": "Fern_221",
        "yield_l": 13.0,
        "completed_at_utc": "2026-07-25T10:20:00Z",
        "flagged_risk": true
      }
    }
  ]
}
```

### 3.4 Watch List & Alerts (`/api/watch-list` or `watch_list.json`)
List of cows with elevated risk or vet flags, stating uncertainty and missing modalities.

```json
{
  "ts_utc": "2026-07-25T14:00:00Z",
  "items": [
    {
      "cow_id": "Fern_221",
      "flag_type": "model_suggestion",
      "watch_reason": "Sustained high CBT under elevated THI accompanied by 18% yield decrease",
      "confidence": 0.84,
      "modalities_present": ["cbt", "neck_imu", "indoor_env", "milk_yield"],
      "modalities_missing": ["uwb"],
      "missing_modality_impact": "Location confidence lower; utilizing last-seen stall beacon",
      "recommended_action": "Check for heat abatement and udder inflammation prior to next cycle"
    }
  ]
}
```

### 3.5 Integration Feasibility (`/api/integrations` or `integrations_feasibility.json`)
Exposes system modularity, capability profiles, and cost metrics for small-farm decision support.

```json
{
  "systems": [
    {
      "adapter_id": "collar_imu_vital",
      "name": "Neck IMU Activity & Rumination",
      "attached": true,
      "cadence": "sub_second_aggregated_1m",
      "annual_cost_per_head_usd": 35.0,
      "feasibility_tier": "recommended",
      "signals": ["activity_index", "rumination_minutes", "head_pitch"],
      "is_synthetic": true
    }
  ]
}
```
