"""Unit tests for S8–S11: Exposure tracing (resting, milking, combined) and permutation-test backtrace."""

import unittest
import pandas as pd
import numpy as np

from analysis.exposure_resting import calculate_resting_exposure, get_grid_cell_id
from analysis.exposure_milking import calculate_milking_exposure
from analysis.exposure_combined import calculate_combined_exposure
from analysis.backtrace import (
    run_permutation_attribution_test,
    generate_synthetic_backtrace_fixtures,
    backtrace,
)


class TestS8S11Backtrace(unittest.TestCase):
    def test_resting_exposure_toy_grid(self):
        # 4 cows on toy grid:
        # C02 (flagged) sheds in cell_X2_Y1 (x=5.1, y=3.1) from 10:00 to 12:00
        # C01 rests in cell_X2_Y1 at 14:00 (same bedding window) -> exposed
        # C03 rests in cell_X2_Y1 at 16:00, but bedding was changed at 15:00 -> not exposed
        # C04 rests in cell_X6_Y4 (x=12.0, y=8.0) -> not exposed
        bouts_df = pd.DataFrame([
            {"cow_id": "C02", "start_utc": "2023-07-25 10:00:00+00:00", "end_utc": "2023-07-25 12:00:00+00:00", "duration_min": 120, "x_m": 5.1, "y_m": 3.1},
            {"cow_id": "C01", "start_utc": "2023-07-25 14:00:00+00:00", "end_utc": "2023-07-25 15:00:00+00:00", "duration_min": 60, "x_m": 5.1, "y_m": 3.1},
            {"cow_id": "C03", "start_utc": "2023-07-25 16:00:00+00:00", "end_utc": "2023-07-25 17:00:00+00:00", "duration_min": 60, "x_m": 5.1, "y_m": 3.1},
            {"cow_id": "C04", "start_utc": "2023-07-25 11:00:00+00:00", "end_utc": "2023-07-25 13:00:00+00:00", "duration_min": 120, "x_m": 12.0, "y_m": 8.0},
        ])
        bedding_df = pd.DataFrame([
            {"zone_id": "main_pen", "changed_at": "2023-07-25 15:00:00+00:00"}
        ])

        res = calculate_resting_exposure(
            lying_bouts_df=bouts_df,
            bedding_df=bedding_df,
            flagged_cows={"C02"},
            lookback_hours=72,
            resting_min_duration_min=20,
        )

        self.assertGreater(res["cow_exposure"]["C01"], 0.0)
        self.assertEqual(res["cow_exposure"]["C03"], 0.0)
        self.assertEqual(res["cow_exposure"]["C04"], 0.0)
        self.assertEqual(len(res["implicated_cells"]), 1)
        self.assertEqual(res["implicated_cells"][0]["cell_id"], "cell_X2_Y1")

        # Real-coordinate 1.5m resting circle validation
        self.assertIn("implicated_resting_areas", res)
        self.assertEqual(len(res["implicated_resting_areas"]), 1)
        circle = res["implicated_resting_areas"][0]
        self.assertEqual(circle["center_x_m"], 5.1)
        self.assertEqual(circle["center_y_m"], 3.1)
        self.assertEqual(circle["radius_m"], 1.5)
        self.assertEqual(circle["target_cow_id"], "C02")
        self.assertEqual(circle["until_bedding_change_utc"], "2023-07-25T15:00:00Z")
        self.assertEqual(circle["contact_cows"], ["C01"])

    def test_milking_exposure_with_sanitization(self):
        # Milking visits:
        # C02 (flagged) milks on STALL-01 at 09:00
        # C01 milks on STALL-01 at 09:15 (un-sanitized) -> exposed
        # Sanitation event occurs on STALL-01 at 09:30
        # C03 milks on STALL-01 at 09:45 (after sanitation) -> not exposed
        # C04 milks on STALL-02 at 09:15 -> not exposed
        milking_df = pd.DataFrame([
            {"cow_id": "C02", "milking_time": "2023-07-25 09:00:00+00:00", "unit_id": "STALL-01"},
            {"cow_id": "C01", "milking_time": "2023-07-25 09:15:00+00:00", "unit_id": "STALL-01"},
            {"cow_id": "C03", "milking_time": "2023-07-25 09:45:00+00:00", "unit_id": "STALL-01"},
            {"cow_id": "C04", "milking_time": "2023-07-25 09:15:00+00:00", "unit_id": "STALL-02"},
        ])
        sanitation_df = pd.DataFrame([
            {"unit_id": "STALL-01", "sanitized_at": "2023-07-25 09:30:00+00:00"}
        ])

        res = calculate_milking_exposure(
            milking_log_df=milking_df,
            sanitation_df=sanitation_df,
            flagged_cows={"C02"},
            lookback_hours=72,
        )

        self.assertGreater(res["cow_exposure"]["C01"], 0.0)
        self.assertEqual(res["cow_exposure"]["C03"], 0.0)
        self.assertEqual(res["cow_exposure"]["C04"], 0.0)
        self.assertEqual(len(res["implicated_units"]), 1)
        self.assertEqual(res["implicated_units"][0]["unit_id"], "STALL-01")

    def test_combined_exposure(self):
        resting_exp = {"C01": 0.60, "C02": 1.0, "C03": 0.0}
        milking_exp = {"C01": 0.40, "C02": 1.0, "C03": 0.0}
        res_comb = calculate_combined_exposure(resting_exp, milking_exp, flagged_cows={"C02"})

        self.assertEqual(res_comb["combined_exposure"]["C02"], 1.0)
        # 1 - (1 - 0.6)*(1 - 0.4) = 0.76
        self.assertAlmostEqual(res_comb["combined_exposure"]["C01"], 0.76, places=2)
        self.assertEqual(res_comb["combined_exposure"]["C03"], 0.0)
        self.assertEqual(len(res_comb["exposed_cows"]), 1)
        self.assertEqual(res_comb["exposed_cows"][0]["cow_id"], "C01")

    def test_permutation_attribution_resting_scenario(self):
        bouts, milk, bed, san = generate_synthetic_backtrace_fixtures(scenario="resting")
        res = run_permutation_attribution_test(
            lying_bouts_df=bouts,
            milking_log_df=milk,
            flagged_cows=["C02", "C01"],
            bedding_df=bed,
            sanitation_df=san,
            n_permutations=100,
            seed=42,
        )
        self.assertEqual(res["likely_route"], "resting_area")
        self.assertEqual(res["likely_route_alias"], "resting_environment")
        self.assertLess(res["p_value_resting"], 0.05)
        self.assertGreater(res["pathogen_group_likelihood"]["environmental_bedding_associated"], 0.70)

    def test_permutation_attribution_milking_scenario(self):
        bouts, milk, bed, san = generate_synthetic_backtrace_fixtures(scenario="milking")
        res = run_permutation_attribution_test(
            lying_bouts_df=bouts,
            milking_log_df=milk,
            flagged_cows=["C02", "C01"],
            bedding_df=bed,
            sanitation_df=san,
            n_permutations=100,
            seed=42,
        )
        self.assertEqual(res["likely_route"], "milking_equipment")
        self.assertEqual(res["likely_route_alias"], "milking_equipment")
        self.assertLess(res["p_value_milking"], 0.05)
        self.assertGreater(res["pathogen_group_likelihood"]["contagious_milking_associated"], 0.70)

    def test_permutation_attribution_sporadic_scenario(self):
        bouts, milk, bed, san = generate_synthetic_backtrace_fixtures(scenario="sporadic")
        res = run_permutation_attribution_test(
            lying_bouts_df=bouts,
            milking_log_df=milk,
            flagged_cows=["C02", "C01"],
            bedding_df=bed,
            sanitation_df=san,
            n_permutations=50,
            seed=42,
        )
        self.assertEqual(res["likely_route"], "no_common_route")
        self.assertEqual(res["likely_route_alias"], "sporadic_inconclusive")
        self.assertGreaterEqual(res["p_value_resting"], 0.05)
        self.assertGreaterEqual(res["p_value_milking"], 0.05)

    def test_backtrace_contract_function(self):
        res = backtrace(flags=[{"cow_id": "C02"}], lookback_hours=72)

        self.assertIn("investigation_id", res)
        self.assertIn("generated_at_utc", res)
        self.assertIn("likely_route", res)
        self.assertIn("likely_route_alias", res)
        self.assertIn("route_p_values", res)
        self.assertIn("p_values", res)
        self.assertIn("pathogen_group_likelihood", res)
        self.assertIn("implicated_units_or_cells", res)
        self.assertIn("implicated_resting_areas", res)
        self.assertIn("implicated_circles", res)
        self.assertIn("implicated_resources", res)
        self.assertIn("resting_areas", res["implicated_resources"])
        self.assertIn("exposed_cows", res)
        self.assertIn("high_risk_contacts", res)
        self.assertIn("recommended_actions", res)
        self.assertTrue(res["is_model_suggestion"])

    def test_backtrace_resting_route_emits_15m_circle(self):
        bouts, milk, bed, san = generate_synthetic_backtrace_fixtures(scenario="resting")
        res = backtrace(
            flags=[{"cow_id": "C02"}, {"cow_id": "C01"}],
            lookback_hours=72,
            lying_bouts_df=bouts,
            milking_log_df=milk,
            bedding_df=bed,
            sanitation_df=san,
            n_permutations=100,
            seed=42,
        )
        self.assertEqual(res["likely_route"], "resting_area")
        self.assertGreaterEqual(len(res["implicated_resting_areas"]), 1)
        first_circle = res["implicated_resting_areas"][0]
        self.assertEqual(first_circle["radius_m"], 1.5)
        self.assertEqual(first_circle["target_cow_id"], "C02")
        self.assertEqual(first_circle["center_x_m"], 5.15)
        self.assertEqual(first_circle["center_y_m"], 3.05)
        self.assertIn("until_bedding_change_utc", first_circle)
        self.assertIn("C01", first_circle["contact_cows"])
        self.assertTrue(res["implicated_resources"]["primary_unit_or_cell"].startswith("Resting Circle"))
        self.assertIn("cell_X", " ".join(res["implicated_units_or_cells"]))


if __name__ == "__main__":
    unittest.main()
