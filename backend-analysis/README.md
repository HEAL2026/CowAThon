# Backend: Data Analysis

Owner: @equan04 (Emmett)
Consumers: `backend-visualization/` (@pauraque) and `frontend/` (@uiobio)

Owns statistical analysis, aggregations, feature generation, physiological/behavioral modeling, and analysis results for Challenge 1 (MMCows).

## Key Guarantees

1. **Zero Animal Leakage in Evaluation**:
   Repeated measures on the same cow never appear in both train and validation splits. All evaluation uses `cleaning.splits.group_kfold` (grouped strictly on `cow_id`), reporting cross-validated performance (mean ± std across animal folds).

2. **Defensible Single-Sensor Baselines**:
   Benchmarks our multimodal predictive model directly against:
   - **Baseline 1 (Environmental)**: Classical THI threshold rule ($THI \ge 68.0$).
   - **Baseline 2 (Physiological)**: Single-channel Core Body Temperature rule ($CBT \ge 39.3^\circ\text{C}$).

3. **Non-Diagnostic Monitoring & Watch-List Scoring**:
   Per track prompt constraints, all outputs are framed as monitoring risk indicators rather than clinical diagnoses. Outputs are categorized as `baseline`, `moderate_watch`, or `priority_watch` ($0 - 100$ scale).

4. **Explicit Uncertainty & Missing-Modality Handling**:
   Outputs include a confidence score ($0.0 - 1.0$), explicit lists of `modalities_present` and `missing_modalities`, and graceful fallback re-weighting.

## Directory Structure

```
backend-analysis/
  analysis/
    env_thermal.py          # THI, heat load accumulation, environmental risk
    cbt_strain.py           # Core body temperature modeling & spike detection
    behavior.py             # IMU kinetic activity, rumination proxy, posture classification
    risk_scorer.py          # Multimodal watch-list risk scoring with graceful degradation
    baselines.py            # Single-sensor baselines vs multimodal benchmark
    evaluation.py           # GroupKFold leak-free evaluation harness
    pipeline.py             # End-to-end analysis runner producing exportable payloads
  tests/
    fixtures.py             # Deterministic synthetic MMCows dataset generator (C01–C10)
    test_thermal.py         # Unit tests for thermal strain & THI calculations
    test_behavior.py        # Unit tests for behavior and activity metrics
    test_risk_scorer.py     # Unit tests for risk scoring & missing modality handling
    test_leak_free_eval.py  # Unit tests ensuring group-aware animal isolation and baselines
    test_pipeline.py        # Integration test verifying output schemas against CONTRACT.md
  CONTRACT.md               # I/O contract for downstream consumers
  requirements.txt          # Python dependencies
```

## Running Tests

From repository root:
```bash
cd backend-analysis
python3 -m unittest discover tests
```

## Executing the Pipeline

```python
from analysis.pipeline import run_analysis_pipeline
import pandas as pd

# Load canonical joined data
df = pd.read_parquet("backend-cleaning/data/processed/joined_1min.parquet")

# Run analysis and export payloads to output directory
results = run_analysis_pipeline(df, output_dir="data/analysis_export", n_cv_splits=5, seed=0)

# Access summaries and benchmark metrics
cow_summaries = results["cow_summaries"]
benchmarks = results["benchmarks"]
```
