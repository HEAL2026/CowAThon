# backend-analysis: I/O Contract and Metric Definitions

Owner: @equan04 — of `backend-analysis/` only.
Consumers: `backend-visualization/` (@pauraque) and `frontend/` (@uiobio).

This document specifies the contracts, input expectations, output schemas, metric definitions, and evaluation guarantees provided by the `backend-analysis/` pipeline for Challenge 1 (MMCows).

---

## 1. Core Principles & Non-Clinical Framing

1. **Non-Diagnostic Monitoring & Risk Scoring Only**:
   Per the challenge prompt and team agreement, the system produces **monitoring and risk prediction metrics** only. It **never declares or outputs unsupported clinical diagnoses** (such as "mastitis", "ill", or clinical disease entities).
   - Valid labels: `baseline`, `moderate_watch`, `priority_watch`.
   - Score range: `watch_risk_score` from `0` to `100`.
   - Every inference payload includes an advisory flag: `"is_model_suggestion": true`.

2. **Zero Leakage Evaluation Guarantee**:
   All evaluation metrics and baseline comparisons enforce animal-disjoint group splitting:
   - Data is partitioned by `cow_id` via `cleaning.splits.group_split` or `cleaning.splits.group_kfold`.
   - Repeated observations for a cow never span train and test sets.
   - Evaluated across $K$-fold animal cross-validation, reporting mean $\pm$ standard deviation.

3. **Explicit Uncertainty & Missing-Modality Handling**:
   - Missing channels degrade confidence gracefully rather than producing errors or silent assumptions.
   - Every risk output carries a `confidence_score` ($0.0 \le c \le 1.0$) and an inventory of `modalities_present` vs `missing_modalities`.

---

## 2. Directory Layout & Artifacts

```
backend-analysis/
  analysis/                 # Analysis and modeling source
    env_thermal.py          # THI, thermal load, environmental risk
    cbt_strain.py           # Core body temperature dynamics & fever/spike detection
    behavior.py             # IMU kinetic activity, rumination proxy, resting bout analysis
    risk_scorer.py          # Multimodal watch-list scoring with graceful degradation
    baselines.py            # Single-sensor baselines vs multimodal benchmark
    evaluation.py           # Group-aware cross-validation engine
    pipeline.py             # Full analysis pipeline execution
  CONTRACT.md               # This contract
  README.md                 # Usage, architecture, and metric formulas
  requirements.txt          # Python dependencies
  tests/                    # Test suite & deterministic fixtures
```

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

### 3.3 Behavioral Activity & Rumination Proxy
- Computed from 1-minute aggregated neck IMU components:
  - **Kinetic Activity Index**:
    $$\text{activity\_index} = \sqrt{\sigma_{\text{acc\_x}}^2 + \sigma_{\text{acc\_y}}^2 + \sigma_{\text{acc\_z}}^2}$$
  - **Posture State**:
    - `resting`: $\text{activity\_index} < \tau_{\text{rest}}$ (low kinetic motion)
    - `active`: $\text{activity\_index} \ge \tau_{\text{rest}}$
  - **Rumination Proxy ($0 - 100$)**:
    Quantifies characteristic rhythmic jaw movements during resting windows. Drops during severe heat distress or physiological disruption.

### 3.4 Multimodal Watch-List Risk Score ($0 - 100$)
Composite weighted score reflecting multi-system deviation:
$$\text{watch\_risk\_score} = S_{\text{thermal}} + S_{\text{behavior}} + S_{\text{production}} + S_{\text{movement}}$$
- **Thermal component ($S_{\text{thermal}}$, max 40)**: From CBT elevation and THI exposure.
- **Behavioral component ($S_{\text{behavior}}$, max 30)**: From rumination drop, abnormal lethargy, or restless agitation.
- **Production component ($S_{\text{production}}$, max 20)**: From sudden milk yield deviation below 3-day baseline.
- **Movement / Spatial component ($S_{\text{movement}}$, max 10)**: Prolonged displacement from comfort/ventilation zones.

**Watch-List Risk Categories**:
- `baseline` ($0 - 39$): Within normal physiological parameters.
- `moderate_watch` ($40 - 69$): Monitored deviation; recommend closer observation.
- `priority_watch` ($70 - 100$): Marked multi-system strain; prompt inspection recommended.

---

## 4. Output Schemas (Consumed by Visualization & Frontend)

### 4.1 Cow Risk Summary Schema (`cow_risk_summary.json`)
Dictionary keyed by `cow_id`:
```json
{
  "cow_id": "cow_01",
  "latest_ts_utc": "2026-07-25T14:30:00Z",
  "watch_risk_score": 74.5,
  "risk_category": "priority_watch",
  "confidence_score": 0.92,
  "metrics": {
    "cbt_c": 39.85,
    "cbt_strain_score": 26.2,
    "ambient_thi": 74.1,
    "thi_category": "moderate_strain",
    "activity_index": 0.12,
    "rumination_proxy": 32.0,
    "daily_milk_yield_kg": 28.4,
    "milk_drop_pct": 14.2
  },
  "modalities_present": ["cbt", "indoor_env", "neck_imu", "milk_yield"],
  "missing_modalities": [],
  "contributing_factors": [
    "CBT elevated +0.85C above baseline",
    "THI in moderate heat strain zone (74.1)",
    "Rumination proxy depressed 35% below expected"
  ],
  "recommended_actions": [
    "Verify barn fan and misting operation in resting stalls",
    "Inspect water availability and intake",
    "Queue for veterinary health check at next milking"
  ],
  "is_model_suggestion": true
}
```

### 4.2 Benchmark Results Schema (`benchmark_results.json`)
Results of animal-disjoint group cross-validation comparing single-sensor baselines against the multimodal predictor:
```json
{
  "dataset": "MMCows Challenge 1",
  "evaluation_protocol": "GroupKFold by cow_id (zero animal leakage)",
  "n_groups": 10,
  "n_splits": 5,
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
      "description": "Single-sensor physiological rule: Alert when CBT >= 39.3C",
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
