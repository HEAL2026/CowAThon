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
  tests/
    test_payloads.py      # Contract validation and guardrail unit tests
```

## Contracts & Guardrails

See [CONTRACT.md](CONTRACT.md) for full schema definitions:
1. **Keys & Timestamps:** `cow_id` (string categorical) + `ts_utc` (ISO 8601 UTC).
2. **Imputation Transparency:** Every imputed metric carries `*_is_imputed: true/false`.
3. **No Clinical Diagnoses:** Output adheres strictly to risk/monitoring framing (e.g. `elevated_risk`, `watch_list`). Clinical diagnostic terms (`diagnosed`, `illness`, `disease`) are forbidden.
4. **Synthetic Labeling:** All offline/mock fixtures carry `is_synthetic: true`.

## Running Tests

Run the test suite with standard library `unittest` or `pytest`:

```bash
python -m unittest discover -s backend-visualization/tests
```

## Exporting Payloads

To generate static payload files for the frontend:

```bash
python -m visualization.exporter --output-dir backend-visualization/data/exported
```
