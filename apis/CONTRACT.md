# apis: I/O Contract & Integration Specification

Owner: @uiobio (Lei)

This document defines the interface and data contracts for the external farm
monitoring and management integration layer (`apis/`). Consumed by `frontend/`
(for integration management & modular toggles), `backend-visualization/`
(for integration feasibility payloads and telemetry charts), and
`backend-cleaning/` (for ingestion alignment).

---

## 1. Architecture & Boundaries

```
[ External Systems / Mocks ]
            │ (fetch & shape)
            ▼
    [ apis.BaseAdapter ]  <───>  [ apis.IntegrationRegistry ]
            │                               │
            ├───────────────────────────────┤
            ▼                               ▼
 [ Normalized ObservationRecords ]    [ Feasibility Payloads ]
   - cow_id (C01..C16 or None)          - adapter_id, vendor
   - ts_utc (tz-aware UTC ISO)          - attached, cadence
   - values, *_is_imputed, *_age_s      - annual_cost_per_head_usd
   - is_synthetic: True                 - feasibility_tier, signals
            │                               │
            ▼                               ▼
    backend-cleaning/             backend-visualization/ & frontend/
```

### Invariants & Non-Negotiables
1. **Fetch and Shape Only**: Adapters do not become a second cleaning pipeline. They normalize external data formats to standard keys without performing silent imputation.
2. **Canonical Keys**:
   - `cow_id`: String categorical (`"C01"`..`"C16"`) for animal-level systems; `None` for barn-level / farm-level systems (climate, weather).
   - `ts_utc`: Tz-aware ISO-8601 UTC timestamp ending in `"Z"` (e.g. `"2023-07-25T14:00:00Z"`). Never local barn time, never naive.
3. **No Silent Imputation**: If an adapter interpolates or fills gaps, it carries `<col>_is_imputed: True` and `<col>_age_s: float`.
4. **Graceful Degradation**: Detached or unhealthy integrations return empty records (`[]`) rather than throwing exceptions.
5. **Synthetic Transparency**: Every mock payload and fixture carries `is_synthetic: True`.

---

## 2. Core Python Interfaces

### 2.1 Adapter Interface (`apis.BaseAdapter`)

```python
class BaseAdapter(ABC):
    @property
    @abstractmethod
    def metadata(self) -> SystemMetadata:
        """Static capability, cost, and vendor metadata."""
        ...

    @abstractmethod
    def health(self) -> AdapterHealth:
        """Live connection state: attached, reachable, mocked, detached, etc."""
        ...

    @property
    def is_attached(self) -> bool:
        """Whether the operator has enabled this integration."""
        ...

    def attach(self) -> None: ...
    def detach(self) -> None: ...

    @abstractmethod
    def fetch_window(
        self,
        start_utc: str,
        end_utc: str,
        cow_ids: Optional[List[str]] = None,
    ) -> List[ObservationRecord]:
        """Fetch records within time window [start_utc, end_utc]."""
        ...
```

### 2.2 System Registry (`apis.IntegrationRegistry`)

```python
class IntegrationRegistry:
    def register(self, adapter: BaseAdapter) -> None: ...
    def unregister(self, adapter_id: str) -> Optional[BaseAdapter]: ...
    def get(self, adapter_id: str) -> Optional[BaseAdapter]: ...
    def list_adapters(self) -> List[BaseAdapter]: ...
    def list_attached_adapters(self) -> List[BaseAdapter]: ...
    def attach(self, adapter_id: str) -> bool: ...
    def detach(self, adapter_id: str) -> bool: ...
    def health_summary(self) -> List[Dict[str, Any]]: ...
    def to_feasibility_payload(self) -> Dict[str, Any]: ...
    def fetch_all(self, start_utc: str, end_utc: str, ...) -> Dict[str, List[ObservationRecord]]: ...
```

---

## 3. Per-Adapter Record Shapes & Metadata

| Adapter ID | Vendor & Name | Category | Level | Cadence | Cost/Head/Yr | Feasibility |
|---|---|---|---|---|---|---|
| `milking_parlor_delaval` | DeLaval DelPro Automated Milk Metering | `milking` | Animal (`Cxx`) | Daily | $18.00 | Recommended |
| `cbt_bolus_smaxtec` | SmaXtec Reticulorumen Thermal Bolus | `bolus_temperature` | Animal (`Cxx`) | 1 min | $42.00 | Optional |
| `barn_climate_munters` | Munters FarmConnect Barn Climate & THI | `barn_climate` | Barn (`None`) | 1 min | $4.50 | Recommended |
| `ankle_pedometer_nedap` | Nedap SmartTag Leg / IceRobotics Pedometer | `ankle_pedometer` | Animal (`Cxx`) | 1 min | $28.00 | Recommended |
| `uwb_location_ubisense` | Ubisense / CowView RTLS Barn UWB | `uwb_location` | Animal (`Cxx`) | 15 s | $85.00 | High-Cost Specialized |
| `collar_imu_nedap` | Nedap CowControl / Allflex SenseHub | `collar_imu` | Animal (`Cxx`) | 1 min (agg) | $35.00 | Recommended |
| `weather_station_tomorrow_io` | Tomorrow.io / Davis Micro-Weather | `weather` | Farm (`None`) | 5 min | $2.00 | Recommended |
| `herd_management_vas_pulse` | VAS PULSE / DairyComp 305 Core | `herd_management` | Animal (`Cxx`) | Daily sync | $12.00 | Recommended |

### Detailed Field Definitions & SI Units

#### 1. `milking_parlor_delaval`
- `cow_id`: string categorical (e.g. `"C01"`).
- `ts_utc`: daily sync timestamp (e.g. `"2023-07-25T12:00:00Z"`).
- `milk_yield_kg`: float, daily milk weight in **kg** (not liters).
- `dim`: integer, days in milk.

#### 2. `cbt_bolus_smaxtec`
- `cow_id`: string categorical (e.g. `"C01"`).
- `ts_utc`: 1-minute timestamp.
- `cbt_c`: float, core body temperature in **°C**.

#### 3. `barn_climate_munters`
- `cow_id`: `null` (farm/barn-level invariant).
- `ts_utc`: 1-minute timestamp.
- `indoor_temp_c`: float, ambient indoor barn temperature in **°C**.
- `indoor_rh_pct`: float, relative humidity percentage (0.0–100.0%).
- `indoor_thi`: float, Temperature-Humidity Index (NRC formula).

#### 4. `ankle_pedometer_nedap`
- `cow_id`: string categorical (e.g. `"C01"`).
- `ts_utc`: 1-minute timestamp.
- `lying`: integer (`1` = lying, `0` = standing/walking).

#### 5. `uwb_location_ubisense`
- `cow_id`: string categorical (e.g. `"C01"`).
- `ts_utc`: 15-second / 1-minute timestamp.
- `uwb_x_m`: float or `null`, X position in meters inside barn coordinates.
- `uwb_y_m`: float or `null`, Y position in meters inside barn coordinates.
- `uwb_z_m`: float or `null`, Z elevation in meters.
- `out_of_pen`: boolean (`true` during milking trips or off-pen transit, coordinates `null`).

#### 6. `collar_imu_nedap`
- `cow_id`: string categorical (e.g. `"C01"`).
- `ts_utc`: 1-minute aggregated timestamp.
- `neck_imu_magnitude_mean`: float, mean acceleration magnitude in **m/s²**.
- `neck_imu_magnitude_std`: float, standard deviation of acceleration magnitude in **m/s²**.
- `collar_pressure_hpa`: float, atmospheric barometric pressure at collar in **hPa**.

#### 7. `weather_station_tomorrow_io`
- `cow_id`: `null` (farm-level invariant).
- `ts_utc`: 5-minute timestamp.
- `outdoor_temp_c`: float, outdoor temperature in **°C**.
- `outdoor_dewpoint_c`: float, outdoor dewpoint in **°C**.
- `outdoor_rh_pct`: float, relative humidity (0.0–100.0%).
- `outdoor_wind_mps`: float, wind speed in **m/s**.
- `outdoor_gust_mps`: float, wind gust in **m/s**.
- `outdoor_pressure_hpa`: float, barometric pressure in **hPa**.
- `outdoor_precip_mm`: float, precipitation accumulation in **mm**.
- `outdoor_uv`: float, UV index.
- `outdoor_solar_wm2`: float, solar radiation in **W/m²**.

#### 8. `herd_management_vas_pulse`
- `cow_id`: string categorical (e.g. `"C01"`).
- `ts_utc`: daily sync timestamp.
- `parity`: integer, lactation count.
- `days_in_milk`: integer.
- `reproductive_status`: string (`"pregnant"`, `"open"`, `"bred"`, `"fresh"`).
- `pen_number`: integer.
- `mastitis_history_count`: integer, recorded lifetime cases.

---

## 4. Integration Feasibility Schema (`/api/integrations`)

Directly consumed by `backend-visualization/CONTRACT.md §3.5` and `frontend/`:

```json
{
  "systems": [
    {
      "adapter_id": "collar_imu_nedap",
      "name": "Nedap CowControl / Allflex SenseHub Neck Collar",
      "vendor": "Nedap",
      "attached": true,
      "cadence": "sub_second_aggregated_1m",
      "annual_cost_per_head_usd": 35.0,
      "hardware_setup_cost_usd": 1600.0,
      "feasibility_tier": "recommended",
      "signals": [
        "neck_imu_magnitude_mean",
        "neck_imu_magnitude_std",
        "collar_pressure_hpa"
      ],
      "is_synthetic": true,
      "roi_summary": "Industry workhorse. Rumination drop precedes clinical mastitis symptoms by 24-48 hours."
    }
  ]
}
```

---

## 5. CLI Quickstart

```bash
# List all registered adapters and small-farm feasibility
python -m apis list

# Export integrations feasibility JSON payload
python -m apis export-feasibility --output backend-visualization/fixtures/integrations_feasibility.json

# Query window records from an attached adapter
python -m apis fetch --adapter milking_parlor_delaval --cow-ids C01 C02 --start 2023-07-25T00:00:00Z --end 2023-07-26T00:00:00Z

# Run ICAR ADE Mock Vendor API Server on port 8001
python -m apis serve-icar --port 8001

# Run unit test suite
python -m unittest discover -s apis/tests
```

---

## 6. S1 ICAR ADE Mock Vendor API Specification

Provides commercial equipment replay feeds and interactive state endpoints matching ICAR ADE standard naming (`animal.id`, `eventDateTime`, `unitCode`, `is_synthetic`):

### 6.1 Replay Telemetry Endpoints

| Endpoint | Method | Params | Response Payload Shape |
|---|---|---|---|
| `/animals` | GET | `cows` | `{"animals": [{"animal": {"id": "C01", "officialTag": "..."}, "parity": 2, "daysInMilk": 120, ...}]}` |
| `/locations` | GET | `start`, `end`, `cows` | `{"locations": [{"animal": {"id": "C01"}, "eventDateTime": "...", "unitCode": "...", "location": {"x_m": 12.4, "y_m": 8.1, "in_pen": true, "zone_id": "cubicle_row_b"}}]}` |
| `/imu` | GET | `start`, `end`, `cows` | `{"imuObservations": [{"animal": {"id": "C01"}, "eventDateTime": "...", "kinematics": {"accelMagnitudeMean_mps2": 9.85, ...}}]}` |
| `/behaviors` | GET | `start`, `end`, `cows`, `bucket_hours` | `{"behaviorBuckets": [{"animal": {"id": "C01"}, "period": {"startTime": "...", "endTime": "...", "durationMinutes": 120}, "metrics": {"lyingMinutes": 75.0, ...}}]}` |
| `/milkvisits` | GET | `start`, `end`, `cows` | `{"milkVisits": [{"animal": {"id": "C01"}, "eventDateTime": "...", "unitCode": "STALL-02", "milking": {"yield_kg": 13.8, "duration_s": 380, "conductivity_ms_cm": 4.9}}]}` |
| `/environment` | GET | `start`, `end` | `{"environment": [{"eventDateTime": "...", "stationId": "...", "indoorClimate": {"temperature_c": 23.5, "thi": 72.1}, "outdoorClimate": {...}}]}` |
| `/bodytemp` | GET | `start`, `end`, `cows` | `{"bodyTemperatures": [{"animal": {"id": "C01"}, "eventDateTime": "...", "unitCode": "BOLUS-01", "bodyTemperature_c": 38.9}]}` |
| `/healthevents` | GET | `start`, `end`, `cows` | `{"healthEvents": [{"animal": {"id": "C02"}, "eventDateTime": "...", "eventType": "elevated_cbt_warning", "severity": "watch", "source": "cbt_bolus"}]}` |

### 6.2 Interactive State Endpoints

| Endpoint | Method | Body / Params | Description |
|---|---|---|---|
| `/manual` | GET | `type`, `animal_id` | Retrieve manual farm logs (`bedding`, `sanitation`, `pregnancy`, `dim`, `parity`). |
| `/manual` | POST | `{"entry_type": "...", "animal_id": "...", "details": {...}}` | Record new manual bedding changes, stall sanitation washes, or cow events. |
| `/flags` | GET | `animal_id`, `status` | List watch-list flags (`status`: `"active"`, `"cleared"`). |
| `/flags` | POST | `{"animal_id": "C02", "flag_type": "manual", "reason": "...", "flagged_by": "vet"}` | Add new manual or automated watch flag. |
| `/backtrace` | POST | `{"animal_id": "C02", "lookback_days": 7}` | Execute outbreak transmission backtrace (evaluates resting cubicle co-resters vs milking stall sequence). |

---

## 7. Frontend / Backend Integration Specification & Contract Alignment

This section formalizes the integration contract between the `apis/` layer, `backend-visualization/` HTTP server (port 8000), `apis/icar/server.py` (port 8001), and `frontend/app.js`.

### 7.1 Dashboard Screen Bindings

| Screen / Endpoint | Bound Fields | Explicitly Ignored Fields | Semantics & UI Handling |
|---|---|---|---|
| **Pen Map**<br>`GET /api/pen-map` | `grid.width_m`, `grid.height_m`<br>`cows[cow_id, display_name, uwb_x_m, uwb_y_m, zone, flag_status, exposure_score, is_source_candidate]`<br>`resting_areas[center_x_m, center_y_m, radius_m, zone_id, until_bedding_change_utc]`<br>`contact_cows` | `grid.cell_size_m`<br>`grid.heatmap`<br>`cows.activity_state`<br>`cows.out_of_pen`<br>`cows.exposure_tier`<br>`contact_events` | UWB coordinates positioned via `(x / width_m) * 100%` and `(y / height_m) * 100%`. Flags trigger red dot highlights; exposure > 0.35 triggers orange amber aura; resting contacts show dashed perimeter. |
| **Herd Health**<br>`GET /api/herd-health` | `cows[cow_id, health_index, mastitis_risk, baseline_tier]` | `cows.risk_components`<br>`cows.health_breakdown`<br>`cows.baseline_confidence`<br>`cows.active_flag`<br>`group_trends` | Sorted ascending by `health_index`. Top 8 cows rendered with progress bars and risk badges. Clicking cow row focuses and highlights dot on Pen Map. |
| **Attribution**<br>`GET /api/attribution` | `likely_route`<br>`p_values[resting_permutation_p, milking_permutation_p]`<br>`transmission_source[identifier, primary_index_cow]`<br>`resting_areas`<br>`recommended_actions` | `route_probabilities`<br>`pathogen_group_likelihood`<br>`lookback_hours`<br>`is_model_suggestion` | Supports canonical 4-route vocabulary (`"resting_area"`, `"milking_equipment"`, `"both"`, `"no_common_route"`). Renders permutation p-values, real resting circle coordinates, primary index source, and top 3 recommended interventions. |
| **Impact**<br>`GET /api/impact` | `total_affected_cows`<br>`flagged_early_count`<br>`mean_lead_time_hours`<br>`estimated_milk_saved_kg` | `cohort_size`<br>`early_detection_rate_pct`<br>`transmission_prevented_cases_est` | Renders headline 4-stat metric grid (affected count, early detection count, mean lead time hours, milk saved in kg). |
| **Interactive Backtrace**<br>`POST /backtrace` | `summary`<br>`likely_route`<br>`p_values`<br>`implicated_resting_areas`<br>`resting_areas`<br>`implicated_circles`<br>`contact_cows`<br>`transmission_source`<br>`recommended_actions`<br>`impact` | N/A | Request sends `{ flags: [{ cow_id: "Cxx" }], lookback_hours: int }` or `{ target_cows: ["Cxx"], lookback_days: int }`. Normalizer binds attribution route, resting circle overlays, and impact cards synchronously. |

### 7.2 Refresh Cadence & Query Parameter Handling

1. **Cadence**: Single as-of snapshot on initial page load (`Promise.all([fetchApi('/api/pen-map'), ...])`). Avoids continuous client-side polling overhead during static reviews.
2. **Date / Pen Filtering**: When the user interacts with the time slider or pen filter, requests include standard query parameters:
   - `ts_utc`: ISO 8601 UTC timestamp (e.g. `?ts_utc=2023-07-28T14:00:00Z`).
   - `pen_id`: String identifier (e.g. `&pen_id=pen_01`).
3. **HTTP Server Contract**: The backend server must parse query parameters and pass them through to underlying payload generators (`generate_pen_map_payload(ts_utc, pen_id)`, etc.).

### 7.3 Coordinate System & Spatial Layout

- **Geometry**: Real-world UWB coordinates in metres (`uwb_x_m`, `uwb_y_m`) defined against a bounding grid (`grid.width_m` = 30.0, `grid.height_m` = 15.0).
- **Frontend Normalization**: Dot and resting circle percentages are computed relative to grid extents:
  $$\text{left} = \frac{x - \text{radius}}{\text{width\_m}} \times 100\%$$
  $$\text{top} = \frac{y - \text{radius}}{\text{height\_m}} \times 100\%$$
- **Resting Circles**: Default 1.5 m radius circles around real resting cubicles, bounded by bedding change timestamps (`until_bedding_change_utc`), eliminating synthetic grid-cell naming.

### 7.4 Data Provenance & Synthetic Badge Semantics

Every payload carries a top-level `is_synthetic: bool` indicator reflecting whether data originates from real telemetry (`backend-cleaning/data/processed/joined_1min.parquet`) or mock fallback fixtures:

- **`all(is_synthetic == False)`**: UI displays green **"Live data"** badge and status **"API connected"**.
- **`all(is_synthetic == True)`**: UI displays **"Demo data"** badge and status **"Demo service"**.
- **Mixed**: UI displays **"Mixed data"** badge (e.g., real pen-map and herd-health alongside synthetic watch-list fixtures before `analysis.run` is generated).

### 7.5 Port Topology

- **Port 8000 (Default)**: `backend-visualization/visualization/server.py` serving GET endpoints (`/api/pen-map`, `/api/herd-health`, `/api/attribution`, `/api/impact`, `/api/integrations`, etc.) and `POST /backtrace`.
- **Port 8001 (Optional)**: `apis/icar/server.py` standalone ICAR ADE server supporting official ICAR ADE telemetry feeds (`/animals`, `/locations`, `/imu`, `/behaviors`, `/milkvisits`, etc.), state store (`/manual`, `/flags`), and backtrace delegation.


