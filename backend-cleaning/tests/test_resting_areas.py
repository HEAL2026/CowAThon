import unittest

import pandas as pd

from cleaning.bouts import resting_areas


class TestRestingAreas(unittest.TestCase):
    def test_marks_all_cows_with_real_coordinates(self):
        bouts = pd.DataFrame(
            [
                {
                    "cow_id": "C01",
                    "start_utc": "2023-07-25T10:00:00Z",
                    "end_utc": "2023-07-25T10:30:00Z",
                    "duration_min": 30,
                    "x_m": 1.0,
                    "y_m": 2.0,
                },
                {
                    "cow_id": "C02",
                    "start_utc": "2023-07-25T11:00:00Z",
                    "end_utc": "2023-07-25T11:10:00Z",
                    "duration_min": 10,
                    "x_m": 1.1,
                    "y_m": 2.1,
                },
            ]
        )
        out = resting_areas(bouts)
        self.assertEqual(out["cow_id"].tolist(), ["C01"])
        self.assertEqual(out.loc[0, "center_x_m"], 1.0)
        self.assertEqual(out.loc[0, "radius_m"], 1.5)

    def test_rejects_non_positive_radius(self):
        with self.assertRaises(ValueError):
            resting_areas(
                pd.DataFrame(
                    {
                        "cow_id": ["C01"],
                        "start_utc": ["2023-01-01"],
                        "end_utc": ["2023-01-01"],
                        "duration_min": [20],
                        "x_m": [1.0],
                        "y_m": [2.0],
                    }
                ),
                radius_m=0,
            )


if __name__ == "__main__":
    unittest.main()
