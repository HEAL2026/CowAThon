"""
Reproducible fixture generator for MMCows-conforming synthetic datasets.
Enables offline development and testing of visualization payloads.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import random
import math


COW_IDS = [
    "Fern_221", "Poppy_164", "Daisy_108", "Buttercup_112",
    "Bessie_301", "Clover_415", "Bella_512", "Rosie_204",
    "Molly_332", "Luna_118", "Penny_219", "Ruby_407",
    "Hazel_105", "Willow_314", "Flora_202", "Ivy_110"
]

BARN_ZONES = [
    "cubicle_row_a", "cubicle_row_b", "feed_alley", "holding_pen", "milking_lane"
]


def generate_mock_cows_overview(
    base_time: Optional[datetime] = None,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """
    Generates synthetic barn location and state records for all 16 MMCows.
    """
    rnd = random.Random(seed)
    cows = []

    for idx, cid in enumerate(COW_IDS):
        zone = rnd.choice(BARN_ZONES)
        is_cubicle = "cubicle" in zone
        activity = "resting" if is_cubicle else ("feeding" if "feed" in zone else "walking")

        # Give Fern_221 elevated heat/health risk for demonstration
        if cid == "Fern_221":
            risk_status = "elevated"
            risk_score = 0.82
            factors = ["THI > 74", "CBT elevated +0.9C", "Milk yield drop 18%"]
            on_watch = True
            missing_mods = []
        elif cid == "Poppy_164":
            risk_status = "elevated"
            risk_score = 0.71
            factors = ["Co-resting exposure with Fern_221", "Activity drop 22%"]
            on_watch = True
            missing_mods = ["uwb"]
        else:
            risk_status = "within_baseline"
            risk_score = round(rnd.uniform(0.05, 0.25), 2)
            factors = []
            on_watch = False
            missing_mods = ["cbt"] if idx % 4 == 0 else []

        cows.append({
            "cow_id": cid,
            "x_coord": round(rnd.uniform(2.0, 28.0), 2),
            "y_coord": round(rnd.uniform(1.0, 14.0), 2),
            "zone": zone,
            "activity_state": activity,
            "risk_status": risk_status,
            "risk_score": risk_score,
            "factors": factors,
            "on_watch_list": on_watch,
            "vet_flagged": (cid == "Poppy_164"),
            "idling_minutes": round(rnd.uniform(15.0, 90.0), 1),
            "missing_modalities": missing_mods,
        })

    return cows


def generate_mock_timeseries(
    cow_id: str,
    days: int = 7,
    cadence_hours: int = 2,
    seed: int = 100,
) -> List[Dict[str, Any]]:
    """
    Generates synthetic multi-day timeseries points for a single animal.
    Explicitly tracks simulated imputation flags.
    """
    rnd = random.Random(seed + hash(cow_id) % 1000)
    end_time = datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc)
    start_time = end_time - timedelta(days=days)

    points = []
    curr = start_time
    base_yield = 32.0 if cow_id != "Fern_221" else 27.5

    while curr <= end_time:
        iso_ts = curr.isoformat()
        hour = curr.hour

        # Diurnal temperature cycle
        ambient_temp = 20.0 + 7.0 * math.sin((hour - 8) * math.pi / 12)
        ambient_thi = 66.0 + 8.0 * math.sin((hour - 8) * math.pi / 12)

        # Base CBT with slight lag behind ambient THI
        cbt_base = 38.6 + (0.8 if cow_id == "Fern_221" and curr > end_time - timedelta(days=2) else 0.0)
        cbt = cbt_base + 0.3 * math.sin((hour - 10) * math.pi / 12) + rnd.uniform(-0.1, 0.1)

        # Simulate 10% missing/imputed CBT values
        cbt_imputed = rnd.random() < 0.10
        if cbt_imputed:
            cbt = round(cbt, 2)  # forward-filled

        imu = 1.2 + rnd.uniform(-0.3, 0.4)
        imu_imputed = rnd.random() < 0.05

        # Milk yield is recorded daily (forward filled for 2h windows)
        yield_val = base_yield + rnd.uniform(-1.0, 1.0)
        yield_imputed = (hour != 6 and hour != 18)

        points.append({
            "ts_utc": iso_ts,
            "cbt_c": round(cbt, 2),
            "cbt_c_is_imputed": cbt_imputed,
            "neck_imu_magnitude_mean": round(imu, 3),
            "neck_imu_magnitude_mean_is_imputed": imu_imputed,
            "daily_milk_yield_l": round(yield_val, 2),
            "daily_milk_yield_l_is_imputed": yield_imputed,
            "indoor_thi": round(ambient_thi, 1),
            "indoor_thi_is_imputed": False,
        })

        curr += timedelta(hours=cadence_hours)

    return points
