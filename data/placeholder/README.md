# Placeholder Datasets

Per `docs/data_contracts.md`:
These datasets serve as placeholders for the mastitis backtrace pipeline until real telemetry / management files arrive.

## Tables
1. **`bedding.json`**:
   - Boundary for resting-route exposure tracing across `changed_at` timestamps per `zone_id`.
   - `is_synthetic: true`
2. **`milk.json`**:
   - Milking visits per cow with unit_id, stall_number, and quarter conductivities (`cond_lf`, `cond_lr`, `cond_rf`, `cond_rr`, `cond_max`) and SCC.
   - `is_synthetic: true`
3. **`milking_log.json`**:
   - Milking sequence and session ordering for milking machine contact exposure tracing.
   - `is_synthetic: true`
4. **`sanitation.json`**:
   - Milking unit disinfection events bounding milking-route transmission windows.
   - `is_synthetic: true`

All tables adhere strictly to non-diagnostic framing and `is_synthetic` transparency.
