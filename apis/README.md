# APIs: Modular Farm-System Integration Layer

Owner: @uiobio (Lei)

Provides the **integration layer** that connects the dashboard to external dairy farm
monitoring and management systems, alongside realistic offline mocks and small-farm
economic feasibility profiles.

For full schema definitions, field shapes, units, and signatures, see
[CONTRACT.md](CONTRACT.md).

---

## Why this folder exists

Small and medium dairy farms cannot afford every sensor platform on the market, and
available technologies differ farm to farm. The dashboard enables operators to
**modularly attach or detach integrations** (wearables, parlor meters, weather, RTLS)
without system rebuilds, maintaining graceful degradation when signals are absent.

## Key Features

- **Unified Adapter Interface (`apis.BaseAdapter`)**: Standardized interface for querying
  windowed telemetry keyed on `cow_id` (`Cxx`) and tz-aware UTC `ts_utc`.
- **System Registry (`apis.IntegrationRegistry`)**: Discovery, dynamic attachment toggling,
  health state tracking, and multi-system queries.
- **Economic Feasibility Profiles**: Annual cost per head, initial hardware overhead,
  feasibility tiers (`recommended`, `optional`, `high_cost_specialized`), and small-farm
  ROI guidance matching `backend-visualization/CONTRACT.md §3.5`.
- **Realistic Offline Mock Adapters**: First-class synthetic mocks simulating DeLaval milking
  parlors, SmaXtec rumen boluses, Munters barn climate, Nedap leg pedometers, Ubisense UWB,
  Nedap/Allflex collar IMU, Tomorrow.io weather, and VAS PULSE herd management.
- **Contract Conformance**: Strictly avoids duplicate cleaning or silent imputation; carries
  `*_is_imputed` flags, and labels all synthetic records with `is_synthetic = True`.
- **S1 ICAR ADE Mock Vendor API Server**: Replays farm equipment feeds (`/animals`, `/locations`,
  `/imu`, `/behaviors`, `/milkvisits`, `/environment`, `/bodytemp`, `/healthevents`) with standard
  ICAR ADE naming, and handles interactive state endpoints (`/manual`, `/flags`, `/backtrace`).

---

## Directory Structure

```
apis/
  __init__.py           # Package exports (BaseAdapter, IntegrationRegistry, etc.)
  __main__.py           # CLI interface (list, export-feasibility, fetch, serve-icar)
  base.py               # Core interfaces, health states, and ObservationRecord
  registry.py           # Registry implementation and create_default_registry()
  fixtures.py           # Synthetic fixture generator and export helpers
  CONTRACT.md           # Formal I/O contract, signal shapes, and SI units
  adapters/             # System adapters
    __init__.py
    milking.py          # DeLaval automated milking parlor
    bolus.py            # SmaXtec reticulorumen CBT bolus
    climate.py          # Munters FarmConnect barn climate & THI (barn-level)
    pedometer.py        # Nedap SmartTag leg / pedometer lying states
    location.py         # Ubisense UWB indoor positioning & out_of_pen state
    collar.py           # Nedap / Allflex collar IMU activity & pressure
    weather.py          # Tomorrow.io / Davis weather station (farm-level)
    herd.py             # VAS PULSE / DairyComp 305 herd management
  icar/                 # S1 ICAR ADE mock vendor services & HTTP server
    __init__.py
    models.py           # ICAR ADE standard domain models
    store.py            # In-memory thread-safe state store for manual logs & flags
    service.py          # Replay telemetry feeds & backtrace executor
    server.py           # CORS-enabled HTTP REST server
  tests/                # Full unit test suite (36/36 passing)
    __init__.py
    test_base.py
    test_registry.py
    test_adapters.py
    test_icar.py
```

---

## Usage

```bash
# Run unit tests
python -m unittest discover -s apis/tests

# List all integrations, status, and feasibility
python -m apis list

# Export feasibility JSON payload
python -m apis export-feasibility

# Fetch window records from DeLaval milking parlor mock
python -m apis fetch --adapter milking_parlor_delaval --cow-ids C01 C02

# Run ICAR ADE Mock Vendor API Server (port 8001)
python -m apis serve-icar --port 8001
```
