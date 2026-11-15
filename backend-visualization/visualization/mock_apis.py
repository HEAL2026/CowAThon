"""
Mock API structures and schemas based on major commercial dairy technology companies.
Provides realistic vendor schemas for Cow Collars, Barn THI, and Local Weather.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone


# ==============================================================================
# 1. COW COLLAR & WEARABLE TELEMETRY: NEDAP AGRI & ALLFLEX (MSD ANIMAL HEALTH)
# ==============================================================================

NEDAP_COWCONTROL_METADATA = {
    "vendor": "Nedap N.V. (Netherlands)",
    "product_name": "Nedap CowControl Smarttag Neck",
    "category": "wearable_collar",
    "base_url": "https://api.nedap-agri.com/cowcontrol/v2",
    "auth_type": "OAuth2 Bearer Token",
    "sampling_cadence": "Continuous raw sensor -> 1-minute summary batches",
    "cost_per_head_usd_year": 38.0,
    "signals": [
        "rumination_minutes", "eating_minutes", "inactive_minutes",
        "kinetic_activity_index", "heat_probability"
    ],
}


def get_mock_nedap_collar_response(
    cow_id: str = "C01",
    collar_id: str = "T01",
    ts_utc: str = "2023-07-28T14:00:00Z"
) -> Dict[str, Any]:
    """
    Mock response representing Nedap CowControl's REST endpoint:
    GET /farms/{farm_id}/collars/{collar_id}/behavior?timestamp={ts_utc}
    """
    return {
        "status": "success",
        "api_version": "2.4.1",
        "server_time": ts_utc,
        "is_synthetic": True,
        "vendor": "Nedap N.V.",
        "data": {
            "farm_id": "NL_FARM_8091",
            "collar_tag_id": collar_id,
            "animal_id": cow_id,
            "timestamp_utc": ts_utc,
            "behavior_summary_last_24h": {
                "rumination_minutes": 420.0,
                "eating_minutes": 275.0,
                "inactivity_minutes": 680.0,
                "rumination_drop_alert": True if cow_id in ["C01", "C02"] else False,
            },
            "last_interval_metrics_1m": {
                "kinetic_activity_mean": 1.15,
                "neck_imu_magnitude_std": 0.28,
                "head_pitch_degrees": -18.4,
            },
            "estrus_heat_index": 12.0,
            "health_distress_warning": True if cow_id == "C01" else False,
        }
    }


ALLFLEX_SENSEHUB_METADATA = {
    "vendor": "MSD Animal Health / Allflex (SCR Dairy)",
    "product_name": "SenseHub Dairy Collar / Ear Sensor",
    "category": "wearable_collar",
    "base_url": "https://api.sensehub.msd-animal-health.com/v1",
    "auth_type": "API Key (x-sensehub-token)",
    "sampling_cadence": "2-minute telemetry stream",
    "cost_per_head_usd_year": 42.0,
    "signals": [
        "health_index_0_100", "rumination_minutes_2h", "activity_deviation_pct",
        "panting_motion_indicator"
    ],
}


def get_mock_allflex_sensehub_response(
    cow_id: str = "C01",
    ts_utc: str = "2023-07-28T14:00:00Z"
) -> Dict[str, Any]:
    """
    Mock response representing Allflex SenseHub API:
    GET /herds/{herd_id}/cows/{cow_id}/health-index
    """
    health_idx = 48.0 if cow_id == "C01" else (62.0 if cow_id == "C02" else 88.0)
    return {
        "herd_id": "US_WI_HERD_104",
        "cow_id": cow_id,
        "timestamp": ts_utc,
        "is_synthetic": True,
        "vendor": "MSD Animal Health / Allflex",
        "metrics": {
            "health_index": health_idx,  # 0 to 100 (lower = distressed)
            "rumination_minutes_2h": 22.0 if cow_id == "C01" else 46.0,
            "activity_deviation_pct": -24.5 if cow_id == "C01" else 3.2,
            "panting_motion_detected": True if cow_id == "C01" else False,
            "group_consistency_score": 0.81,
        },
        "alerts": [
            {
                "alert_type": "thermal_behavior_deviation",
                "severity": "high" if cow_id == "C01" else "low",
                "triggered_at": ts_utc,
            }
        ] if cow_id in ["C01", "C02"] else [],
    }


# ==============================================================================
# 2. BARN THI & ENVIRONMENTAL CONTROL: MUNTERS & DAVIS INSTRUMENTS
# ==============================================================================

MUNTERS_FARMCONNECT_METADATA = {
    "vendor": "Munters Group (Sweden)",
    "product_name": "Munters Trio Climate Controller & FarmConnect Cloud",
    "category": "barn_environmental_station",
    "base_url": "https://api.farmconnect.munters.com/v1",
    "auth_type": "OAuth2 Bearer Token",
    "sampling_cadence": "1-minute sensor polling",
    "cost_per_head_usd_year": 5.5,
    "signals": [
        "indoor_temp_c", "relative_humidity_pct", "derived_thi",
        "heat_stress_stage", "fan_ventilation_stage", "misting_active"
    ],
}


def get_mock_munters_thi_response(
    barn_id: str = "main_barn_01",
    ts_utc: str = "2023-07-28T14:00:00Z"
) -> Dict[str, Any]:
    """
    Mock response representing Munters FarmConnect IoT telemetry:
    GET /barns/{barn_id}/climate/telemetry?ts={ts_utc}
    """
    return {
        "barn_id": barn_id,
        "timestamp_utc": ts_utc,
        "is_synthetic": True,
        "vendor": "Munters Group",
        "climate_metrics": {
            "indoor_temp_c": 26.8,
            "indoor_rh_pct": 66.0,
            "indoor_thi": 74.2,
            "thermal_category": "moderate_heat_strain",  # THI 72-79
            "static_pressure_pa": 101325.0,
            "air_speed_mps": 1.8,
        },
        "sensor_nodes": [
            {"sensor_id": f"S{i:02d}", "temp_c": round(26.5 + i * 0.1, 1), "rh_pct": 66.0}
            for i in range(1, 7)
        ],
        "actuators_state": {
            "ventilation_fans_stage": 4,  # Stage 1 to 6
            "cooling_misters_active": True,
            "curtain_opening_pct": 85.0,
        },
    }


# ==============================================================================
# 3. LOCAL & HYPERLOCAL WEATHER TELEMETRY: TOMORROW.IO & OPENWEATHER AG
# ==============================================================================

TOMORROW_IO_AG_METADATA = {
    "vendor": "Tomorrow.io (The Tomorrow Companies Inc.)",
    "product_name": "Tomorrow.io Agricultural Weather & Heat Stress API",
    "category": "hyperlocal_weather",
    "base_url": "https://api.tomorrow.io/v4/timelines",
    "auth_type": "API Key (apikey query param)",
    "sampling_cadence": "15-minute observations and 1-hour forecasts",
    "cost_per_head_usd_year": 2.0,
    "signals": [
        "outdoor_temp_c", "outdoor_rh_pct", "dew_point_c", "solar_radiation_wm2",
        "wind_speed_mps", "wind_gust_mps", "outdoor_thi_forecast_24h"
    ],
}


def get_mock_tomorrow_io_weather_response(
    latitude: float = 40.08,
    longitude: float = -88.24,
    ts_utc: str = "2023-07-28T14:00:00Z"
) -> Dict[str, Any]:
    """
    Mock response representing Tomorrow.io agricultural timeline endpoint:
    GET /timelines?location={lat},{lon}&fields=temperature,humidity,dewPoint,solarRadiation,windSpeed
    """
    return {
        "location": {"lat": latitude, "lon": longitude, "name": "Commercial Dairy Barn, Urbana IL"},
        "timestamp_utc": ts_utc,
        "is_synthetic": True,
        "vendor": "Tomorrow.io Inc.",
        "current_conditions": {
            "outdoor_temp_c": 28.5,
            "outdoor_dewpoint_c": 21.2,
            "outdoor_rh_pct": 65.0,
            "outdoor_wind_mps": 3.8,
            "outdoor_gust_mps": 6.2,
            "outdoor_pressure_hpa": 1012.4,
            "outdoor_precip_mm": 0.0,
            "outdoor_uv_index": 7.5,
            "outdoor_solar_wm2": 780.0,
            "calculated_outdoor_thi": 76.8,
        },
        "forecast_heat_stress_advisory": {
            "max_thi_next_24h": 79.5,
            "hours_above_thi_72": 14,
            "cooling_urgency": "high",
        },
    }


# ==============================================================================
# 4. HERD MANAGEMENT PLATFORM: VALLEY AGRICULTURAL SOFTWARE (VAS / PULSE)
# ==============================================================================

VAS_PULSE_METADATA = {
    "vendor": "Valley Agricultural Software (VAS, USA)",
    "product_name": "VAS PULSE Cloud (DairyComp 305 Integration)",
    "category": "herd_management_platform",
    "base_url": "https://api.vas.com/pulse/v2",
    "auth_type": "OAuth2 Client Credentials",
    "sampling_cadence": "Event-driven and daily milk cycles",
    "cost_per_head_usd_year": 18.0,
    "signals": [
        "cow_id", "dim_days_in_milk", "lactation_number", "daily_milk_weight_kg",
        "pen_number", "parity", "breed"
    ],
}


def get_mock_vas_pulse_response(
    cow_id: str = "C01",
    ts_utc: str = "2023-07-28T14:00:00Z"
) -> Dict[str, Any]:
    """
    Mock response representing VAS PULSE / DairyComp 305 cow record:
    GET /farms/{farm_id}/cows/{cow_id}
    """
    return {
        "farm_code": "US_IL_782",
        "cow_id": cow_id,
        "electronic_id": f"982000418920{cow_id[-2:]}",
        "timestamp_utc": ts_utc,
        "is_synthetic": True,
        "vendor": "Valley Agricultural Software (VAS)",
        "animal_profile": {
            "breed": "Holstein",
            "lactation_number": 2,
            "days_in_milk": 142,
            "current_pen": 4,
            "stall_assignment": "cubicle_row_b",
        },
        "production": {
            "daily_milk_weight_kg": 21.8 if cow_id == "C01" else 30.5,
            "3_day_average_milk_weight_kg": 26.5,
            "somatic_cell_count_k": 280 if cow_id == "C01" else 110,
            "milk_conductivity_relative": 1.18 if cow_id == "C01" else 1.0,
        },
    }


# ==============================================================================
# REGISTRY & MAPPING INTO CANONICAL REPO SCHEMA
# ==============================================================================

ALL_MOCK_APIS = [
    NEDAP_COWCONTROL_METADATA,
    ALLFLEX_SENSEHUB_METADATA,
    MUNTERS_FARMCONNECT_METADATA,
    TOMORROW_IO_AG_METADATA,
    VAS_PULSE_METADATA,
]


def map_vendor_telemetry_to_canonical_row(
    cow_id: str,
    ts_utc: str,
    nedap_data: Optional[Dict[str, Any]] = None,
    munters_data: Optional[Dict[str, Any]] = None,
    weather_data: Optional[Dict[str, Any]] = None,
    vas_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Transforms heterogeneous AgTech vendor responses into the canonical
    joined_1min schema mandated by backend-cleaning/CONTRACT.md.
    """
    row = {
        "cow_id": cow_id,
        "ts_utc": ts_utc,
        "cbt_c": None,
        "cbt_c_is_imputed": True,
        "neck_imu_magnitude_mean": None,
        "neck_imu_magnitude_mean_is_imputed": True,
        "milk_yield_kg": None,
        "milk_yield_kg_is_imputed": True,
        "dim": None,
        "indoor_temp_c": None,
        "indoor_rh_pct": None,
        "indoor_thi": None,
        "outdoor_temp_c": None,
        "outdoor_rh_pct": None,
        "outdoor_wind_mps": None,
        "outdoor_solar_wm2": None,
        "out_of_pen": False,
        "is_synthetic": True,
    }

    if nedap_data and "data" in nedap_data:
        m = nedap_data["data"].get("last_interval_metrics_1m", {})
        row["neck_imu_magnitude_mean"] = m.get("kinetic_activity_mean")
        row["neck_imu_magnitude_mean_is_imputed"] = False

    if munters_data and "climate_metrics" in munters_data:
        c = munters_data["climate_metrics"]
        row["indoor_temp_c"] = c.get("indoor_temp_c")
        row["indoor_rh_pct"] = c.get("indoor_rh_pct")
        row["indoor_thi"] = c.get("indoor_thi")

    if weather_data and "current_conditions" in weather_data:
        w = weather_data["current_conditions"]
        row["outdoor_temp_c"] = w.get("outdoor_temp_c")
        row["outdoor_rh_pct"] = w.get("outdoor_rh_pct")
        row["outdoor_wind_mps"] = w.get("outdoor_wind_mps")
        row["outdoor_solar_wm2"] = w.get("outdoor_solar_wm2")

    if vas_data and "production" in vas_data:
        p = vas_data["production"]
        row["milk_yield_kg"] = p.get("daily_milk_weight_kg")
        row["milk_yield_kg_is_imputed"] = False
        row["dim"] = vas_data.get("animal_profile", {}).get("days_in_milk")

    return row
