"""
Reproducible fixture generator for MMCows dataset conforming to raw schema.
Spans 2023-07-21 through 2023-08-04 for cows C01 through C16.
C01-C10 are instrumented (CBT, IMU, UWB, Ankle); C11-C16 are uninstrumented (Milk only).
"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import random
import math

COW_IDS = [f"C{i:02d}" for i in range(1, 17)]
INSTRUMENTED_COWS = set(COW_IDS[:10])  # C01..C10

COW_NAME_MAP = {
    "C01": "Fern",
    "C02": "Poppy",
    "C03": "Daisy",
    "C04": "Buttercup",
    "C05": "Bessie",
    "C06": "Clover",
    "C07": "Bella",
    "C08": "Rosie",
    "C09": "Molly",
    "C10": "Luna",
    "C11": "Penny",
    "C12": "Ruby",
    "C13": "Hazel",
    "C14": "Willow",
    "C15": "Flora",
    "C16": "Ivy",
}

BARN_ZONES = [
    "cubicle_row_a", "cubicle_row_b", "feed_alley", "holding_pen", "milking_lane"
]


def generate_mock_cows_overview(
    base_time: Optional[datetime] = None,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """
    Generates synthetic barn location and state records for all 16 MMCows.
    Reflects instrumented vs uninstrumented cows and out_of_pen milking states.
    """
    if base_time is None:
        base_time = datetime(2023, 7, 28, 14, 0, tzinfo=timezone.utc)

    rnd = random.Random(seed)
    cows = []
    hour = base_time.hour
    is_milking_hour = hour in [4, 5, 15, 16]

    for idx, cid in enumerate(COW_IDS):
        is_inst = cid in INSTRUMENTED_COWS
        friendly_name = COW_NAME_MAP.get(cid, cid)

        # Milking excursion simulation
        out_of_pen = is_milking_hour and (idx % 2 == 0)
        zone = "milking_lane" if out_of_pen else rnd.choice(BARN_ZONES[:-1])
        is_cubicle = "cubicle" in zone
        activity = "milking" if out_of_pen else ("resting" if is_cubicle else "feeding")

        if not is_inst:
            # Uninstrumented cows (C11-C16): only milk & herd THI available
            missing_mods = ["cbt", "uwb", "neck_imu", "ankle", "pressure"]
            risk_status = "within_baseline"
            risk_score = 0.15
            factors = ["Baseline milk yield; uninstrumented sensors"]
            on_watch = False
            vet_flagged = False
            x, y = 15.0, 7.5
        elif cid == "C01":
            # C01 (Fern): Primary heat distress & elevated CBT demonstration
            missing_mods = []
            risk_status = "priority_watch"
            risk_score = 0.84
            factors = [
                "THI in moderate heat strain zone (74.2)",
                "CBT elevated +0.85C (39.85C)",
                "Milk yield depressed 18% below 3-day baseline",
            ]
            on_watch = True
            vet_flagged = False
            x, y = (26.5, 4.0) if out_of_pen else (12.4, 8.2)
        elif cid == "C02":
            # C02 (Poppy): Co-resting contact exposure with C01
            missing_mods = ["uwb"]
            risk_status = "moderate_watch"
            risk_score = 0.68
            factors = [
                "Co-resting in cubicle_row_b alongside C01",
                "Neck IMU activity drop 22%",
            ]
            on_watch = True
            vet_flagged = True
            x, y = (25.0, 5.0) if out_of_pen else (13.1, 8.4)
        else:
            missing_mods = []
            risk_status = "baseline"
            risk_score = round(rnd.uniform(0.05, 0.30), 2)
            factors = []
            on_watch = False
            vet_flagged = False
            x = round(rnd.uniform(3.0, 27.0), 2)
            y = round(rnd.uniform(2.0, 13.0), 2)

        cows.append({
            "cow_id": cid,
            "display_name": f"{friendly_name} ({cid})",
            "x_coord": x,
            "y_coord": y,
            "zone": zone,
            "activity_state": activity,
            "out_of_pen": out_of_pen,
            "risk_status": risk_status,
            "risk_score": risk_score,
            "factors": factors,
            "on_watch_list": on_watch,
            "vet_flagged": vet_flagged,
            "idling_minutes": round(rnd.uniform(15.0, 95.0), 1),
            "missing_modalities": missing_mods,
            "is_instrumented": is_inst,
        })

    return cows


def generate_mock_timeseries(
    cow_id: str,
    days: int = 7,
    cadence_hours: int = 1,
    seed: int = 100,
) -> List[Dict[str, Any]]:
    """
    Generates synthetic multi-day timeseries points for MMCows spanning July 2023.
    Explicitly tracks simulated imputation flags and missing-modality behavior.
    """
    rnd = random.Random(seed + hash(cow_id) % 1000)
    end_time = datetime(2023, 7, 28, 14, 0, tzinfo=timezone.utc)
    start_time = end_time - timedelta(days=days)

    is_inst = cow_id in INSTRUMENTED_COWS
    base_yield_kg = 26.5 if cow_id == "C01" else (31.0 + rnd.uniform(-2.0, 2.0))

    points = []
    curr = start_time

    while curr <= end_time:
        iso_ts = curr.isoformat()
        hour = curr.hour

        # Diurnal temperature cycle in America/Chicago (summer)
        ambient_temp = 22.0 + 8.0 * math.sin((hour - 8) * math.pi / 12)
        ambient_thi = 68.0 + 9.0 * math.sin((hour - 8) * math.pi / 12)

        is_milking_cycle = hour in [4, 5, 15, 16]

        if is_inst:
            # Instrumented cow: CBT and IMU available
            cbt_base = 38.6 + (0.9 if cow_id == "C01" and curr > end_time - timedelta(days=2) else 0.0)
            cbt = cbt_base + 0.3 * math.sin((hour - 10) * math.pi / 12) + rnd.uniform(-0.08, 0.08)
            cbt_imputed = rnd.random() < 0.05
            cbt_val = round(cbt, 2)

            imu_val = round(1.25 + rnd.uniform(-0.25, 0.35), 3)
            imu_imputed = rnd.random() < 0.04
            lying_state = 0 if is_milking_cycle or hour in [7, 8, 12, 13] else 1
        else:
            # Uninstrumented cow: CBT and IMU are missing
            cbt_val = None
            cbt_imputed = False
            imu_val = None
            imu_imputed = False
            lying_state = None

        # Milk weight recorded daily (forward filled for 1h cadence)
        yield_kg = round(base_yield_kg + rnd.uniform(-0.8, 0.8), 2)
        yield_imputed = not (hour == 5 or hour == 16)

        points.append({
            "ts_utc": iso_ts,
            "cbt_c": cbt_val,
            "cbt_c_is_imputed": cbt_imputed,
            "neck_imu_magnitude_mean": imu_val,
            "neck_imu_magnitude_mean_is_imputed": imu_imputed,
            "daily_milk_yield_kg": yield_kg,
            "daily_milk_yield_kg_is_imputed": yield_imputed,
            "lying": lying_state,
            "indoor_thi": round(ambient_thi, 1),
            "indoor_thi_is_imputed": False,
            "out_of_pen": is_milking_cycle,
        })

        curr += timedelta(hours=cadence_hours)

    return points
