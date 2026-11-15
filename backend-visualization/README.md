# Backend: Visualization

Owner: @pauraque (Aster).

Owns server-side preparation for dashboard views, including data loading, query shaping, summaries, non-clinical risk projections, outbreak backtrace presentation, and visualization-ready JSON payloads.

All UI rendering components live in `frontend/`; this folder provides strict contract adherence, data loaders with deterministic fallback, and a zero-dependency HTTP server with CORS.

---

## Directory Structure

```
backend-visualization/
  CONTRACT.md                       # Comprehensive schema specifications for all payloads
  README.md                         # Folder documentation and execution instructions
  data/
    benchmarks/
      farm_housing_mastitis_risk.json   # Cleaned 88-herd Quebec mastitis housing risk benchmark
      farm_housing_mastitis_risk.csv    # Tabular benchmark format
  visualization/
    __init__.py                     # Package interface exporting generators
    schemas.py                      # Strongly-typed Dataclasses for all payloads
    payloads.py                     # Core payload shaping and non-clinical guardrails
    data_loader.py                  # CWD-independent data loader with synthetic gating
    fixtures.py                     # Deterministic MMCows synthetic data generator
    exporter.py                     # CLI tool to export static JSON payloads
    server.py                       # Zero-dependency HTTP server with CORS for frontend
    clean_uploaded_dataset.py       # Pipeline for commercial housing mastitis benchmarks
  tests/
    test_payloads.py                # Schema validation, contract adherence, non-clinical tests
    test_server.py                  # Live HTTP server, routing, and CORS header tests
    test_data_loader.py             # CWD independence, sidecar parsing, and fallback tests
    test_s12_payloads.py            # S12 outbreak backtrace, pen map, herd health, impact tests
```

---

## Core Contracts & Guardrails

See [CONTRACT.md](CONTRACT.md) for full schema definitions:
1. **Keys & Timestamps:** `cow_id` (`C01`–`C16`) + `ts_utc` (ISO-8601 UTC string).
2. **Standard SI Units:** `milk_yield_kg` (kg), `cbt_c` and `indoor_temp_c` (°C), `uwb_x_m` and `uwb_y_m` (m), `neck_imu_magnitude_mean` (m/s²).
3. **Imputation Transparency:** Every metric carries `<col>_is_imputed: true/false` and `<col>_age_s`.
4. **Strictly Non-Clinical Framing:** Wording is limited to monitoring, risk observation, and likelihoods (`baseline`, `moderate_watch`, `priority_watch`). Unsupported clinical diagnoses (`diagnosed`, `illness`, `disease`, `sick`, `cured`) are forbidden.
5. **Real Data Ingestion & Synthetic Labeling:**
   - Consumes `backend-cleaning` via `cleaning.locate.find_joined()` and `sidecar_for()`.
   - `is_synthetic` is gated strictly on path resolution: `False` when real data is resolved, `True` when falling back to fixtures.
   - Resolves robustly regardless of current working directory (`cwd`).

---

## HTTP API Endpoints

Start the HTTP server on port 8000:

```bash
python backend-visualization/visualization/server.py --port 8000
```

All endpoints support CORS (`Access-Control-Allow-Origin: *`):

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Service health check and endpoint directory |
| `/api/barn-overview` | GET | Spatial cow locations, UWB coords, thermal zones, and heat density |
| `/api/cows/{cow_id}` | GET | 7-day cow physiological timeseries, CBT, lying, milk yield, co-resters |
| `/api/milking-stalls` | GET | Milking parlor stalls status, flow rates, and last completed cycles |
| `/api/watch-list` | GET | Suspected high-risk cows, missing-modality impacts, suggested actions |
| `/api/benchmarks` | GET | Animal-disjoint group CV baselines vs. multimodal model lift |
| `/api/integrations` | GET | Commercial dairy systems (Nedap, Allflex, Munters, Tomorrow.io, VAS) |
| `/api/pen-map` | GET | S12 2D pen map with resting heatmap from lying bouts and exposed cows |
| `/api/herd-health` | GET | S12 Herd table with 0–100 health index and acute mastitis risk split |
| `/api/attribution` | GET | S12 Outbreak backtrace route attribution and permutation p-values |
| `/api/impact` | GET | S12 Mitigation lead time, milk saved, and prevented cases impact |

---

## Running Tests

The test suite requires zero external pip dependencies and runs with standard library `unittest`:

```bash
python -m unittest discover -s backend-visualization/tests
```

All 26 tests validate payload schemas, non-clinical guardrails, CWD independence, and server wire behavior.

---

## Exporting Payloads

To dump static payload files for frontend offline development or static deployment:

```bash
python backend-visualization/visualization/exporter.py --output-dir backend-visualization/data/exported
```
