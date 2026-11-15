# Commercial Vendor Dairy Pipeline Integration & Normalization

Owner: @uiobio (Lei)

This document provides technical justification and data contracts demonstrating how the **CowAThon data pipeline supports major commercial dairy automation equipment as direct inputs to the data modeling pipeline**.

---

## 1. Executive Summary & Architecture

Commercial dairy farms rarely operate homogeneous hardware suites. Instead, operations combine:
1. **Milking Hardware**: Automated Milking Systems (AMS) and Rotary Carousels (**Lely Astronaut**, **DeLaval DelPro**, **Merck FreeFlow / SCR**).
2. **Wearable Animal Telemetry**: Neck collars and ear tags (**Merck SenseHub cSense/eSense**, **CowManager**, **Nedap / Lely Qwes**).
3. **Barn Climate Stations**: Temperature, Relative Humidity, and THI monitors (**Davis WeatherLink**, **Munters Rotem**, **SenseHub Ambient**).
4. **Farm Management Systems (FMS)**: Herd demographic logs (**DairyComp 305**, **BoviSync**, **PCDART**).

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Commercial Equipment & Vendor APIs                   │
├─────────────────┬──────────────────────┬───────────────────────────────┤
│ Lely Horizon    │ Merck SenseHub Dairy │ CowManager                    │
│ - Astronaut AMS │ - cSense Collars     │ - Dual-Temp Ear Sensors       │
│ - Rotary Parlor │ - eSense Ear Tags    │ - Ear Motion Accelerometer    │
│ - Qwes Collars  │ - FreeFlow Meters    │ - 15-min Telemetry Sync       │
│ - Barn Climate  │ - Barn THI Station   │ - DelPro/Lely FMS Connector   │
└────────┬────────┴──────────┬───────────┴───────────────┬───────────────┘
         │                   │                           │
         ▼                   ▼                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│              apis.vendors Adapter & Normalization Layer                │
│ - Normalizes timestamps to UTC tz-aware ISO-8601 ('Z')                 │
│ - Standardizes animal keys to C-scheme ('C01'..'C16')                  │
│ - Calculates standard NRC/Kibler THI: 0.8*T + (RH/100)*(T-14.4) + 46.3 │
│ - Calibrates ear skin temperature to CBT core temperature proxy        │
│ - Converts 4-quarter conductivities (LF, LR, RF, RR) to mS/cm          │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 Reprocessor (apis.vendors.reprocessor)                 │
├──────────────────────────────────┬─────────────────────────────────────┤
│ Ingested & Mapped into           │ Academic Modalities Omitted &       │
│ joined_1min.parquet Schema       │ Justified (Ignored)                 │
│ - milk_yield_kg, unit_id         │ - Top-down RGB multi-camera video   │
│ - cond_lf, cond_lr, cond_rf,     │   (Hostile barn optics, dust, lens  │
│   cond_rr, cond_max              │    fouling, >10x GPU/network cost)  │
│ - peak_flow_rate_kg_min          │ - Continuous 15s 3D UWB (x, y, z)   │
│ - rumination_minutes, lying      │   (Multipath cubicle piping echoes, │
│ - neck_imu_magnitude_mean        │    replaced by stall/chokepoint IDs)│
│ - ear_temp_c, cbt_c (imputed)    ├─────────────────────────────────────┤
│ - indoor_temp_c, indoor_rh_pct,  │ Farm Management Dummy Fallbacks     │
│   indoor_thi                     │ - parity, dim, pregnant_confirmed,  │
│                                  │   last_freshen_utc (is_synthetic)   │
└──────────────────────────────────┴─────────────────────────────────────┘
```

---

## 2. Vendor API Specifications

### 2.1 Lely (Lely Horizon & Astronaut / Qwes)
* **API Documentation & Protocol**: REST API via OpenAPI 3.0 / Swagger (`https://api-integration.lely.com/swagger/v1/swagger.json`), OAuth 2.0 Client Credentials, ICAR ADE standard.
* **Relevant Endpoints**:
  | Endpoint | Description | Key Raw Fields |
  |---|---|---|
  | `GET /api/v1/milkvisits` | Per-visit milking box / rotary telemetry | `animal_id`, `visit_datetime`, `device_id`, `milk_yield_kg`, `milking_duration_seconds`, `box_time_seconds`, `peak_flow_rate_kg_min`, `average_flow_rate_kg_min` |
  | `GET /api/v1/milkvisitrobotdata` | Sensor metrics per teat/quarter | `conductivity_lf`, `conductivity_lr`, `conductivity_rf`, `conductivity_rr` (mS/cm), `temperature_c`, `blood_detected`, `mqc_scc_indication` |
  | `GET /api/v1/ruminations` | Qwes neck collar rumination blocks | `animal_id`, `timestamp`, `rumination_minutes_2h`, `eating_minutes_2h` |
  | `GET /api/v1/activities` | Cow activity and restlessness | `animal_id`, `timestamp`, `activity_relative_score`, `inactivity_minutes_2h` |
  | `GET /api/v1/barns/{id}/climate` | Horizon barn environmental monitor | `station_id`, `timestamp`, `temperature_c`, `relative_humidity_pct`, `thi` |

### 2.2 Merck Animal Health (SenseHub Dairy / Allflex / SCR)
* **API Documentation & Protocol**: SenseHub Cloud B2B Partner API (`https://api.sensehub.merck.com/v1`), OAuth 2.0 Bearer tokens, DataFlow II bridge.
* **Relevant Endpoints**:
  | Endpoint | Description | Key Raw Fields |
  |---|---|---|
  | `GET /api/v1/herds/{id}/cows/{id}/activities` | cSense neck collar & eSense ear tag activity | `cow_id`, `timestamp_utc`, `device_model`, `rumination_minutes_2h`, `eating_minutes_2h`, `resting_minutes_2h`, `activity_score`, `panting_minutes_2h` |
  | `GET /api/v1/herds/{id}/cows/{id}/milk-sessions` | FreeFlow optical milk meters on carousel/parlor | `cow_id`, `milking_time`, `parlor_stall_id`, `yield_kg`, `duration_sec`, `flow_rate_peak_kg_min`, `conductivity_ms_cm`, `cond_lf/lr/rf/rr`, `temperature_c` |
  | `GET /api/v1/herds/{id}/climate/ambient` | SenseHub barn climate & THI station | `sensor_id`, `timestamp_utc`, `temp_c`, `rh_percent`, `thi` |
  | `GET /api/v1/herds/{id}/cows/{id}/health-monitoring` | Estrus and health exception flags | `cow_id`, `heat_index_prob`, `health_index_deviation`, `panting_alert` |

### 2.3 CowManager
* **API Documentation & Protocol**: CowManager Cloud API (`https://api.cowmanager.com/v2`), local Router sync, ICAR ADE and JSON REST endpoints.
* **Relevant Endpoints**:
  | Endpoint | Description | Key Raw Fields |
  |---|---|---|
  | `GET /api/v2/cows/{id}/behavior` | 15-min / 1-hour ear accelerometer classifications | `cow_id`, `timestamp_utc`, `rumination_minutes`, `eating_minutes`, `resting_minutes`, `active_minutes`, `high_active_minutes` |
  | `GET /api/v2/cows/{id}/temperature` | Dual-sensor ear skin surface thermistors | `cow_id`, `timestamp_utc`, `ear_surface_temp_c`, `temperature_status` |
  | `GET /api/v2/cows/{id}/alerts` | Health, nutrition, and heat alert levels | `cow_id`, `health_status`, `heat_alert`, `transition_risk` |
  | `GET /api/v2/cows/{id}/milkings` | Bridged DeLaval/Lely milk recording data | `cow_id`, `milking_time`, `yield_kg`, `conductivity_ms_cm`, `stall_id` |

---

## 3. Reprocessing & Signal Mapping to `joined_1min`

The reprocessor converts raw vendor JSON payloads into rows that match `backend-cleaning/CONTRACT.md`:

| Target Column in `joined_1min` | mmcows Raw Native Source | Commercial Vendor Source & Mapping Logic | Imputation / Calibration Policy |
|---|---|---|---|
| `cow_id` | Cow number C01..C16 | Lely `animal_id`, SenseHub `cow_id`, CowManager `cow_id` | Standard string categorical |
| `ts_utc` | Unix epoch / Chicago ISO | Vendor ISO-8601 timestamps normalized to UTC `Z` | Native timestamp preservation |
| `milk_yield_kg` | Daily weight / visit weight | Lely Astronaut `milk_yield_kg`, SenseHub FreeFlow `yield_kg` | Native measurement (kg) |
| `unit_id` | Milking stall code | Lely `device_id` (e.g. `ASTRONAUT-01`), SenseHub `parlor_stall_id` (e.g. `ROTARY-BAIL-14`) | Clean stall/box identifier |
| `cond_lf, lr, rf, rr` | Synthetic 4-quarter | Lely `conductivity_lf..rr`, SenseHub `cond_lf..rr` | Quarter electrical conductivity in mS/cm |
| `cond_max` | $\max(\text{cond})$ | Derived: `max(cond_lf, cond_lr, cond_rf, cond_rr)` | Clean indicator for unilateral acute mastitis |
| `peak_flow_rate_kg_min`| Flow sensor | Lely `peak_flow_rate_kg_min`, SenseHub `flow_rate_peak_kg_min` | Native milk speed (kg/min) |
| `lying` | 0/1 from ankle tag | Derived from resting budget: `1` if resting > 50% of interval, else `0` | Behavioral mode thresholding |
| `neck_imu_magnitude_mean`| 10 Hz accelerometer ($m/s^2$) | Calibrated proxy from vendor activity score: `1.2 + 3.0 * norm_activity_score` | Imputed proxy ($m/s^2$) |
| `indoor_temp_c` | Barn climate S01..S06 | Lely `temperature_c`, SenseHub `temp_c`, Davis `temp` | Degrees Celsius (°C) |
| `indoor_rh_pct` | Barn RH sensor | Lely `relative_humidity_pct`, SenseHub `rh_percent` | Relative humidity (0–100%) |
| `indoor_thi` | Formula-derived | Computed via Kibler formula: $0.8 \cdot T + \frac{RH}{100} \cdot (T - 14.4) + 46.3$ | Unified barn heat stress index |
| `cbt_c` | smaXtec rumen bolus | CowManager ear surface temperature ($T_{ear}$) calibrated to core body temperature: $\text{CBT}_{\text{est}} = 38.6 + 0.45 \cdot (T_{ear} - 33.5) - 0.05 \cdot (T_{\text{ambient}} - 20.0)$ | `cbt_c_is_imputed: True`, `cbt_c_age_s: 0.0` |

---

## 4. Omitted Modalities & Commercial Justification

The following academic modalities present in `mmcows` are **intentionally omitted from commercial vendor ingestion pipelines**:

### 4.1 Top-Down Multi-Camera RGB Video Streams
* **Status**: **Ignored and Omitted**.
* **Technical & Economic Rationale**:
  1. **Harsh Barn Environment**: Commercial dairy barns experience high concentrations of airborne particulate matter (feed dust, bedding lime, dried manure dust), high relative humidity (up to 95%), and ammonia outgassing. Optical camera lenses suffer rapid lens occlusion, fly specking, and manure splashing, requiring continuous manual cleaning that is operationally unviable.
  2. **Stall & Animal Occlusion**: Top-down line-of-sight is obstructed by steel roof purlins, overhead ventilation fans, high-density lighting fixtures, and cubicle partition piping. When cows cluster or stand beneath headlocks, visual bounding boxes and keypoint trackers suffer severe identity swapping.
  3. **Bandwidth & Compute Overhead**: Streaming continuous 1080p RGB video from 10–20 overhead cameras across a 200-head barn requires gigabit local fiber and multi-GPU server infrastructure costing >$30,000 in capital outlay and hundreds of watts of power. In contrast, ultra-low-power sub-GHz RF collars and ear tags transmit behavioral metrics over several hundred meters to a single base station with 5–7 year battery life at <10% of the cost.
* **Pipeline Impact**: **Zero negative impact**. Neck collars (Lely Qwes, SenseHub cSense) and ear tags (CowManager, SenseHub eSense) directly measure head movement, rumination chewing, and resting bouts via 3D accelerometry, eliminating the need for visual pose estimation.

### 4.2 Continuous 15-Second High-Resolution 3D UWB Coordinates $(x, y, z)$
* **Status**: **Replaced by Zone & Chokepoint Tracking**.
* **Technical & Economic Rationale**:
  1. **Multipath Reflection**: High densities of galvanized steel cubicle rails and metal barn roofs cause severe radio-frequency multipath reflections and phase distortion, requiring extensive antenna calibration arrays to maintain sub-meter accuracy.
  2. **Capital Cost**: Full-barn UWB coverage requires 12–24 synchronized anchor beacons per pen, adding substantial installation and wiring cost.
* **Pipeline Impact & Fallback**: Commercial farms utilize choke-point RFID antennas at rotary carousel entry bails, robotic milking boxes, sort gates, and concentrate feeding stations. Milking visit stall IDs (`unit_id`) and feeding timestamps provide sufficient spatio-temporal resolution for S8–S11 transmission attribution without continuous millimetric tracking.

---

## 5. Manually Entered Data Policy (Dummy Fallback)

Commercial dairy producers manage reproductive events, health treatments, and lactation demographics in separate Farm Management Systems (FMS) like **DairyComp 305**, **BoviSync**, or **PCDART**, rather than sensor hardware APIs.

As specified by team protocol:
* Fields: `parity`, `dim`, `pregnant_confirmed`, `last_freshen_utc`, `last_preg_check_utc`.
* Behavior: When a commercial hardware feed is connected without an authenticated FMS integration, the pipeline supplies deterministic, realistic dummy records from `apis.vendors.reprocessor.VendorReprocessor` or `apis.icar.store.StateStore`.
* Invariant: All supplied dummy records carry `"is_synthetic": True`.

---

## 6. Verification & Test Suite

The vendor integration package is covered by automated unit tests in `apis/tests/test_vendors.py`:
* `test_thi_computation`: Validates Kibler/NRC THI formula against test vectors ($25^\circ\text{C}, 60\% \to \text{THI } 72.7$).
* `test_lely_horizon_adapter`: Validates 4-quarter conductivities, flow rates, Qwes collar rumination, and climate normalization.
* `test_sensehub_adapter`: Validates rotary parlor FreeFlow milk sessions, cSense/eSense resting and panting minutes.
* `test_cowmanager_adapter`: Validates ear temperature calibration to CBT proxy with `cbt_c_is_imputed: True`.
* `test_vendor_reprocessor`: Verifies unified ingestion into `joined_1min` rows with automatic synthetic manual entry injection.
* `test_compatibility_audit_report`: Confirms transparent documentation of omitted RGB video and UWB coordinates.

Run test suite:
```bash
python -m unittest discover -s apis/tests
# Ran 43 tests in 0.224s - OK
```
