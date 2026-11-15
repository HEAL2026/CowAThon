"""Test fixtures generating deterministic synthetic MMCows-like multi-animal datasets."""

from __future__ import annotations
import numpy as np
import pandas as pd


def generate_synthetic_mmcows_data(
    n_cows: int = 10,
    n_minutes: int = 120,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate deterministic synthetic multi-sensor dairy cow dataset."""
    rng = np.random.default_rng(seed)

    records = []
    base_time = pd.Timestamp("2026-07-25 08:00:00", tz="UTC")

    for i in range(1, n_cows + 1):
        cow_id = f"cow_{i:02d}"
        # Cow-specific physiological baseline
        cow_base_cbt = 38.6 + 0.1 * (i % 4)

        for m in range(n_minutes):
            ts = base_time + pd.Timedelta(minutes=m)

            # Environmental conditions (warming up over time)
            hour_fraction = m / 60.0
            temp_c = 22.0 + 3.0 * hour_fraction + rng.normal(0, 0.2)
            rh_pct = 65.0 - 2.0 * hour_fraction + rng.normal(0, 0.5)

            # Physiological CBT response
            # A couple cows (e.g. cow_02, cow_07) exhibit thermal strain
            is_distressed_cow = i in (2, 7)
            if is_distressed_cow and m > 40:
                cbt = cow_base_cbt + 0.9 + 0.01 * (m - 40) + rng.normal(0, 0.05)
                acc_x_std = 0.01 + rng.uniform(0.0, 0.01) # Lethargy
                acc_y_std = 0.01 + rng.uniform(0.0, 0.01)
                acc_z_std = 0.01 + rng.uniform(0.0, 0.01)
                milk_drop_pct = 12.0 + rng.uniform(0.0, 4.0)
                idling_fraction = 0.75 + rng.uniform(0.0, 0.1)
            else:
                cbt = cow_base_cbt + rng.normal(0, 0.08)
                acc_x_std = 0.03 + rng.uniform(0.0, 0.03) # Normal rumination/movement
                acc_y_std = 0.03 + rng.uniform(0.0, 0.03)
                acc_z_std = 0.03 + rng.uniform(0.0, 0.03)
                milk_drop_pct = max(0.0, rng.normal(1.0, 1.5))
                idling_fraction = 0.35 + rng.uniform(0.0, 0.1)

            records.append({
                "cow_id": cow_id,
                "ts_utc": ts,
                "temp_c": round(temp_c, 2),
                "rh_pct": round(rh_pct, 1),
                "cbt": round(cbt, 2),
                "acc_x_std": round(acc_x_std, 4),
                "acc_y_std": round(acc_y_std, 4),
                "acc_z_std": round(acc_z_std, 4),
                "milk_yield": round(32.0 - (milk_drop_pct / 100.0) * 32.0, 1),
                "milk_drop_pct": round(milk_drop_pct, 1),
                "idling_fraction": round(idling_fraction, 2),
            })

    return pd.DataFrame(records)
