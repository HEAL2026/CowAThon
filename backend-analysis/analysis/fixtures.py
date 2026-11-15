"""Deterministic synthetic MMCows-like multi-animal datasets for offline testing and demo fallback.

Uses canonical real MMCows fields and C-scheme animal IDs (C01–C10).
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from .env_thermal import calculate_thi


def generate_synthetic_mmcows_data(
    n_cows: int = 10,
    n_minutes: int = 120,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate deterministic synthetic multi-sensor dairy cow dataset."""
    rng = np.random.default_rng(seed)

    records = []
    base_time = pd.Timestamp("2023-07-25 08:00:00", tz="UTC")

    for i in range(1, n_cows + 1):
        cow_id = f"C{i:02d}"
        cow_base_cbt = 38.6 + 0.1 * (i % 4)

        for m in range(n_minutes):
            ts = base_time + pd.Timedelta(minutes=m)

            # Environmental conditions (warming up over time)
            hour_fraction = m / 60.0
            temp_c = 22.0 + 3.0 * hour_fraction + rng.normal(0, 0.2)
            rh_pct = 65.0 - 2.0 * hour_fraction + rng.normal(0, 0.5)
            thi = float(calculate_thi(temp_c, rh_pct))

            # Milking excursion (out_of_pen state around 15 minutes in for herd)
            is_milking_trip = 10 <= m < 20
            out_of_pen = is_milking_trip

            # A couple cows (e.g. C02, C07) exhibit thermal strain
            is_distressed_cow = i in (2, 7)
            if is_distressed_cow and m > 40:
                cbt = cow_base_cbt + 0.9 + 0.01 * (m - 40) + rng.normal(0, 0.05)
                imu_mag_std = 0.01 + rng.uniform(0.0, 0.01) # Lethargy
                imu_mag_mean = 9.81 + rng.normal(0, 0.02)
                milk_drop_pct = 12.0 + rng.uniform(0.0, 4.0)
                lying = 1
                uwb_x_m = np.nan if out_of_pen else 12.5
                uwb_y_m = np.nan if out_of_pen else 8.2
            else:
                cbt = cow_base_cbt + rng.normal(0, 0.08)
                imu_mag_std = 0.035 + rng.uniform(0.0, 0.03) # Normal rumination/movement
                imu_mag_mean = 9.85 + rng.normal(0, 0.05)
                milk_drop_pct = max(0.0, rng.normal(1.0, 1.5))
                lying = 1 if (m % 45 < 25) else 0
                uwb_x_m = np.nan if out_of_pen else float(10.0 + rng.uniform(-2, 2))
                uwb_y_m = np.nan if out_of_pen else float(8.0 + rng.uniform(-2, 2))

            records.append({
                "cow_id": cow_id,
                "ts_utc": ts,
                "cbt_c": round(cbt, 2),
                "indoor_temp_c": round(temp_c, 2),
                "indoor_rh_pct": round(rh_pct, 1),
                "indoor_thi": round(thi, 1),
                "neck_imu_magnitude_mean": round(imu_mag_mean, 3),
                "neck_imu_magnitude_std": round(imu_mag_std, 4),
                "milk_yield_kg": round(32.0 - (milk_drop_pct / 100.0) * 32.0, 1),
                "milk_drop_pct": round(milk_drop_pct, 1),
                "dim": 120 + i * 5,
                "lying": lying,
                "out_of_pen": out_of_pen,
                "uwb_x_m": uwb_x_m,
                "uwb_y_m": uwb_y_m,
                "uwb_z_m": 1.2 if not out_of_pen else np.nan,
                # Aliases for backward compatibility
                "cbt": round(cbt, 2),
                "thi": round(thi, 1),
                "temp_c": round(temp_c, 2),
                "rh_pct": round(rh_pct, 1),
                "acc_x_std": round(imu_mag_std / np.sqrt(3), 4),
                "acc_y_std": round(imu_mag_std / np.sqrt(3), 4),
                "acc_z_std": round(imu_mag_std / np.sqrt(3), 4),
                "milk_yield": round(32.0 - (milk_drop_pct / 100.0) * 32.0, 1),
            })

    return pd.DataFrame(records)
