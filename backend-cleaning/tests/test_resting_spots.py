import unittest

import pandas as pd

from cleaning.bouts import assign_spots, resting_spots


def _bouts():
    rows = []
    # cubicle A around (0, 0): three cows, long bouts
    for i, cow in enumerate(["C01", "C02", "C03"]):
        rows.append({"cow_id": cow, "duration_min": 60 + i, "x_m": 0.0 + 0.3 * i, "y_m": 0.1 * i, "in_pen_frac": 1.0})
    # cubicle B around (5, 0): one cow
    rows.append({"cow_id": "C04", "duration_min": 40, "x_m": 5.0, "y_m": 0.0, "in_pen_frac": 1.0})
    # too short, no coords, mostly out of pen: all excluded
    rows.append({"cow_id": "C05", "duration_min": 10, "x_m": 0.1, "y_m": 0.0, "in_pen_frac": 1.0})
    rows.append({"cow_id": "C06", "duration_min": 50, "x_m": None, "y_m": None, "in_pen_frac": 1.0})
    rows.append({"cow_id": "C07", "duration_min": 50, "x_m": 5.1, "y_m": 0.1, "in_pen_frac": 0.2})
    return pd.DataFrame(rows)


class TestRestingSpots(unittest.TestCase):
    def test_clusters_by_linkage_and_orders_by_dwell(self):
        out = resting_spots(_bouts())
        self.assertEqual(out["spot_id"].tolist(), ["spot_01", "spot_02"])
        self.assertEqual(out.loc[0, "n_cows"], 3)
        self.assertEqual(out.loc[0, "n_bouts"], 3)
        self.assertAlmostEqual(out.loc[0, "dwell_min"], 183.0)
        self.assertEqual(out.loc[1, "n_cows"], 1)
        self.assertFalse(out["is_synthetic"].any())
        self.assertTrue(abs(out.loc[0, "center_x_m"]) < 0.6 and abs(out.loc[1, "center_x_m"] - 5.0) < 1e-6)

    def test_assign_nearest_within_radius_else_na(self):
        b = _bouts()
        spots = resting_spots(b)
        ids = assign_spots(b, spots)
        self.assertEqual(ids.iloc[0], "spot_01")
        self.assertEqual(ids.iloc[3], "spot_02")
        self.assertTrue(pd.isna(ids.iloc[5]), "no coordinates -> NA")
        far = pd.DataFrame([{"cow_id": "C09", "duration_min": 30, "x_m": 20.0, "y_m": 20.0}])
        self.assertTrue(pd.isna(assign_spots(far, spots).iloc[0]), "outside every radius -> NA")

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            resting_spots(_bouts(), link_m=0)
        with self.assertRaises(KeyError):
            resting_spots(pd.DataFrame({"cow_id": ["C01"]}))


if __name__ == "__main__":
    unittest.main()
