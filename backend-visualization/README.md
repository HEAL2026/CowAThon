# Backend: Visualization

Owner: @pauraque (Aster).

Owns server-side preparation for charts and dashboards, including query
shaping, summaries, and visualization-ready payloads.

Keep rendering components in `frontend`; this folder provides data contracts
and shaped JSON payloads for them.

## Directory Structure

```
backend-visualization/
  CONTRACT.md             # Schema specifications for all view payloads
  README.md               # Folder guide and execution instructions
  visualization/
    __init__.py           # Package interface
    schemas.py            # Dataclasses and payload models
    payloads.py           # Core payload shaping functions
    fixtures.py           # Reproducible MMCows synthetic data generator
    exporter.py           # CLI tool to export static JSON payloads
    server.py             # Lightweight HTTP server with CORS for frontend
  tests/
    test_payloads.py      # Contract validation and guardrail unit tests
    test_server.py        # HTTP endpoint routing and CORS tests
```

## Contracts & Guardrails

See [CONTRACT.md](CONTRACT.md) for full schema definitions:
1. **Keys & Timestamps:** `cow_id` (`C01`–`C16`) + `ts_utc` (ISO 8601 UTC).
2. **Standard SI Units:** `milk_yield_kg`, `cbt_c`, `uwb_x_m`, `uwb_y_m`.
3. **Imputation Transparency:** Every imputed metric carries `*_is_imputed: true/false`.
4. **No Clinical Diagnoses:** Output adheres strictly to risk/monitoring framing (`baseline`, `moderate_watch`, `priority_watch`). Clinical diagnostic terms (`diagnosed`, `illness`, `disease`) are forbidden.
5. **Synthetic Labeling:** All offline/mock fixtures carry `is_synthetic: true`.

## Running the API Server

Start the zero-dependency HTTP server with CORS enabled:

```bash
python -m visualization.server --port 8000
```

Available endpoints:
- `GET /api/health`
- `GET /api/barn-overview`
- `GET /api/cows/{cow_id}`
- `GET /api/milking-stalls`
- `GET /api/watch-list`
- `GET /api/benchmarks`
- `GET /api/integrations`

## Running Tests

Run the test suite with standard library `unittest` or `pytest`:

```bash
python -m unittest discover -s backend-visualization/tests
```

## Exporting Payloads

To generate static payload files:

```bash
python -m visualization.exporter --output-dir backend-visualization/data/exported
```
