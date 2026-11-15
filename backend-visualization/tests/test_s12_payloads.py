"""
Unit tests for S12 outbreak backtrace, pen map, herd health, and impact payloads.
Includes strict non-clinical diagnosis guardrails and placeholder contract verification.
"""

import os
import sys
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in [REPO_ROOT, REPO_ROOT / "backend-visualization", REPO_ROOT / "backend-cleaning", REPO_ROOT / "apis"]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from visualization.payloads import (
    generate_pen_map,
    generate_herd_health,
    generate_attribution,
    generate_impact,
    generate_backtrace_run,
)
from visualization.data_loader import (
    load_bedding_data,
    load_milk_visits_data,
    get_pen_map_data,
    get_herd_health_data,
    get_attribution_data,
    get_impact_data,
)
from visualization.server import VisualizationAPIHandler


class TestS12Payloads(unittest.TestCase):

    def test_pen_map_schema_and_grid(self):
        payload = generate_pen_map()
        self.assertEqual(payload["barn_id"], "main_barn_01")
        self.assertEqual(payload["pen_id"], "pen_01")
        grid = payload["grid"]
        self.assertEqual(grid["width_m"], 30.0)
        self.assertEqual(grid["height_m"], 15.0)
        self.assertEqual(len(grid["heatmap"]), 15)
        self.assertEqual(len(grid["heatmap"][0]), 30)

        cows = payload["cows"]
        self.assertEqual(len(cows), 16)
        c01 = next(c for c in cows if c["cow_id"] == "C01")
        self.assertEqual(c01["flag_status"], "flagged")
        self.assertGreater(c01["exposure_score"], 0.8)
        self.assertTrue(c01["is_source_candidate"])

        elements = payload["implicated_elements"]
        self.assertIn("grid_cells", elements)
        self.assertIn("milking_units", elements)
        self.assertIn("resting_zones", elements)

        # Real-coordinate 1.5m resting circles & contact overlays
        self.assertIn("resting_areas", payload)
        self.assertIn("implicated_circles", payload)
        self.assertIn("contact_events", payload)
        self.assertGreaterEqual(len(payload["resting_areas"]), 1)
        circle = payload["resting_areas"][0]
        self.assertEqual(circle["radius_m"], 1.5)
        self.assertIn("center_x_m", circle)
        self.assertIn("center_y_m", circle)
        self.assertIn("until_bedding_change_utc", circle)
        self.assertIn("contact_cows", circle)

    def test_herd_health_table_vitality_and_risk(self):
        payload = generate_herd_health()
        cows = payload["cows"]
        self.assertEqual(len(cows), 16)

        # Herd group trends
        self.assertIn("group_trends", payload)
        trends = payload["group_trends"]
        self.assertEqual(trends["cohort_size"], 16)
        self.assertIn("mean_health_index", trends)
        self.assertIn("mean_mastitis_risk", trends)
        self.assertIn("watch_counts", trends)

        c01 = next(c for c in cows if c["cow_id"] == "C01")
        self.assertLess(c01["health_index"], 70.0)
        self.assertGreater(c01["mastitis_risk"], 70.0)
        breakdown = c01["health_breakdown"]
        self.assertIn("thermal_vitality", breakdown)
        self.assertIn("production_vitality", breakdown)

        components = c01["risk_components"]
        self.assertIn("rule_score", components)
        self.assertIn("anomaly_score", components)
        expected_risk = round(0.6 * components["rule_score"] + 0.4 * components["anomaly_score"], 1)
        self.assertEqual(c01["mastitis_risk"], expected_risk)

        flag = c01["active_flag"]
        self.assertIsNotNone(flag)
        self.assertEqual(flag["status"], "active")
        self.assertEqual(flag["type"], "suspected")
        self.assertIn("confidence", flag)

    def test_attribution_panel_and_likelihoods(self):
        payload = generate_attribution()
        canonical_routes = [
            "resting_area",
            "milking_equipment",
            "both",
            "no_common_route",
            "resting_cubicle_route",
            "milking_equipment_route",
        ]
        self.assertIn(payload["likely_route"], canonical_routes)
        probs = payload["route_probabilities"]
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=2)
        p_vals = payload["p_values"]
        self.assertIn("resting_permutation_p", p_vals)
        self.assertIn("milking_permutation_p", p_vals)
        self.assertIn("resting_areas", payload)
        self.assertIn("implicated_resting_areas", payload)
        self.assertIn("impact", payload)

        pathogens = payload["pathogen_group_likelihood"]
        self.assertIn("coliform_environmental_gram_negative", pathogens)
        self.assertIn("streptococci_environmental_gram_positive", pathogens)
        self.assertIn("statement", pathogens)
        self.assertTrue(payload["is_model_suggestion"])

    def test_backtrace_run_payload(self):
        canonical_routes = ["resting_area", "milking_equipment", "both", "no_common_route"]

        # Single cow run
        payload = generate_backtrace_run(flags=[{"cow_id": "C01"}], lookback_hours=72)
        self.assertIn(payload["likely_route"], canonical_routes)
        self.assertIn("p_values", payload)
        self.assertIn("resting_areas", payload)
        self.assertIn("implicated_resting_areas", payload)
        self.assertIn("impact", payload)
        self.assertIn("transmission_source", payload)
        self.assertEqual(payload["impact"]["flagged_early_count"], 1)

        circle = payload["resting_areas"][0]
        self.assertEqual(circle["radius_m"], 1.5)
        self.assertIn("center_x_m", circle)
        self.assertIn("center_y_m", circle)
        self.assertIn("until_bedding_change_utc", circle)

        # Multi-cow group run
        payload_multi = generate_backtrace_run(target_cows=["C01", "C02"], lookback_hours=72)
        self.assertIn(payload_multi["likely_route"], canonical_routes)
        self.assertEqual(payload_multi["impact"]["flagged_early_count"], 2)
        self.assertGreaterEqual(len(payload_multi["resting_areas"]), 1)

    def test_impact_panel(self):
        payload = generate_impact()
        self.assertEqual(payload["cohort_size"], 16)
        self.assertGreater(payload["flagged_early_count"], 0)
        self.assertGreater(payload["mean_lead_time_hours"], 10.0)
        self.assertGreater(payload["estimated_milk_saved_kg"], 50.0)

    def test_placeholder_datasets(self):
        bedding = load_bedding_data()
        self.assertGreaterEqual(len(bedding), 4)
        for b in bedding:
            self.assertIn("zone_id", b)
            self.assertIn("changed_at", b)
            self.assertTrue(b["is_synthetic"])

        milk = load_milk_visits_data()
        self.assertGreaterEqual(len(milk), 50)
        for m in milk[:10]:
            self.assertIn("unit_id", m)
            self.assertIn("stall_number", m)
            self.assertIn("cond_lf", m)
            self.assertIn("cond_max", m)
            self.assertTrue(m["is_synthetic"])

    def test_server_s12_endpoints(self):
        for route in ["/api/pen-map", "/api/herd-health", "/api/attribution", "/api/impact"]:
            code, data = VisualizationAPIHandler.route_request(route)
            self.assertEqual(code, 200, f"Route {route} failed with {code}")
            self.assertIsInstance(data, dict)
            self.assertIn("is_synthetic", data)

    def test_non_clinical_wording_guardrail(self):
        """Strictly enforces prompt mandate: Output must never contain unsupported clinical diagnoses."""
        forbidden_patterns = [
            r"\bdiagnos(?:is|ed|ing)\b",
            r"\bill(?:ness)?\b",
            r"\bdisease(?:d)?\b",
            r"\bsick(?:ness)?\b",
            r"\bcure(?:d)?\b",
        ]
        endpoints_to_test = [
            generate_pen_map(),
            generate_herd_health(),
            generate_attribution(),
            generate_impact(),
            generate_backtrace_run(),
        ]

        def check_text(val: str, path: str):
            for pat in forbidden_patterns:
                # Disallow clinical diagnosis assertions, but allow explanatory disclaimers like "not a clinical diagnosis"
                matches = re.finditer(pat, val, re.IGNORECASE)
                for m in matches:
                    snippet = val[max(0, m.start() - 25):min(len(val), m.end() + 25)].lower()
                    if "not a clinical diagnosis" in snippet or "not clinical diagnosis" in snippet or "never diagnosis" in snippet:
                        continue
                    self.fail(f"Forbidden clinical diagnosis term '{m.group(0)}' at {path}: ...{snippet}...")

        def recurse(node, path="root"):
            if isinstance(node, dict):
                for k, v in node.items():
                    recurse(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    recurse(v, f"{path}[{i}]")
            elif isinstance(node, str):
                check_text(node, path)

        for payload in endpoints_to_test:
            recurse(payload)

    def test_pen_map_timestamp_sensitivity(self):
        """Verifies pen map cow coordinates change dynamically across timestamps and stay in bounds."""
        p1 = generate_pen_map(ts_utc="2023-07-26T09:00:00Z")
        p2 = generate_pen_map(ts_utc="2023-07-28T14:00:00Z")
        p3 = generate_pen_map(ts_utc="2023-07-30T20:00:00Z")

        c1_c01 = next(c for c in p1["cows"] if c["cow_id"] == "C01")
        c2_c01 = next(c for c in p2["cows"] if c["cow_id"] == "C01")
        c3_c01 = next(c for c in p3["cows"] if c["cow_id"] == "C01")

        # Coordinates must not be byte-identical across 4-day time spread
        self.assertNotEqual((c1_c01["uwb_x_m"], c1_c01["uwb_y_m"]), (c2_c01["uwb_x_m"], c2_c01["uwb_y_m"]))
        self.assertNotEqual((c2_c01["uwb_x_m"], c2_c01["uwb_y_m"]), (c3_c01["uwb_x_m"], c3_c01["uwb_y_m"]))

        # Bounds check across all instrumented cows
        for payload in [p1, p2, p3]:
            for cow in payload["cows"]:
                if cow.get("uwb_x_m") is not None:
                    self.assertGreaterEqual(cow["uwb_x_m"], 0.0)
                    self.assertLessEqual(cow["uwb_x_m"], 30.0)
                    self.assertGreaterEqual(cow["uwb_y_m"], 0.0)
                    self.assertLessEqual(cow["uwb_y_m"], 15.0)

    def test_pen_map_with_cows_data_and_synthetic_gating(self):
        """Verifies is_synthetic is False when real cow positions are supplied."""
        custom_cows = [
            {
                "cow_id": "C01",
                "display_name": "Cow C01",
                "uwb_x_m": 14.2,
                "uwb_y_m": 6.8,
                "zone": "cubicle_row_a",
                "activity_state": "resting",
                "out_of_pen": False,
                "flag_status": "flagged",
                "exposure_score": 0.92,
                "exposure_tier": "priority_watch",
                "is_source_candidate": True,
            }
        ]
        p = generate_pen_map(cows_data=custom_cows, is_synthetic=False)
        self.assertFalse(p["is_synthetic"])
        self.assertEqual(p["cows"][0]["uwb_x_m"], 14.2)
        self.assertEqual(p["cows"][0]["uwb_y_m"], 6.8)

    def test_generate_impact_ts_utc_guarantee(self):
        """Verifies impact payload always carries ts_utc even if impact_data omitted it."""
        raw_impact = {
            "cohort_size": 16,
            "total_affected_cows": 3,
            "flagged_early_count": 2,
        }
        res = generate_impact(impact_data=raw_impact, ts_utc="2023-07-29T10:00:00Z")
        self.assertEqual(res["ts_utc"], "2023-07-29T10:00:00Z")
        self.assertEqual(res["cohort_size"], 16)

    def test_backtrace_run_no_unbound_local_error(self):
        """Verifies generate_backtrace_run handles service exceptions without UnboundLocalError."""
        from unittest.mock import patch
        with patch("apis.icar.service.IcarAdeService.run_backtrace", side_effect=RuntimeError("Simulated failure")):
            run = generate_backtrace_run(flags=[{"cow_id": "C01"}], lookback_hours=72)
            self.assertIn("likely_route", run)
            self.assertIn("resting_areas", run)
            self.assertIn("impact", run)
            self.assertEqual(len(run["resting_areas"]), 1)

    def test_pen_map_centered_coordinate_system(self):
        """Verifies pen map automatically detects centered MMCows coordinates and outputs origin='center'."""
        centered_cows = [
            {
                "cow_id": "C01",
                "uwb_x_m": -4.2,
                "uwb_y_m": 2.1,
                "zone": "cubicle_row_b",
                "activity_state": "resting",
                "out_of_pen": False,
            },
            {
                "cow_id": "C02",
                "uwb_x_m": 6.8,
                "uwb_y_m": -3.5,
                "zone": "cubicle_row_a",
                "activity_state": "resting",
                "out_of_pen": False,
            },
        ]
        p = generate_pen_map(cows_data=centered_cows)
        self.assertEqual(p["coordinate_system"], "centered")
        self.assertEqual(p["grid"]["origin"], "center")
        self.assertEqual(p["grid"]["x_min_m"], -12.45)
        self.assertEqual(p["grid"]["x_max_m"], 12.45)
        self.assertEqual(p["grid"]["y_min_m"], -9.31)
        self.assertEqual(p["grid"]["y_max_m"], 8.39)

    def test_pen_map_positive_coordinate_system(self):
        """Verifies pen map defaults to positive coordinates for synthetic fixtures."""
        p = generate_pen_map(ts_utc="2023-07-28T14:00:00Z")
        self.assertEqual(p["coordinate_system"], "positive")
        self.assertEqual(p["grid"]["origin"], "bottom_left")
        self.assertEqual(p["grid"]["x_min_m"], 0.0)
        self.assertEqual(p["grid"]["x_max_m"], 30.0)

    def test_heatmap_c11_c16_exclusion(self):
        """Verifies uninstrumented cows C11-C16 and rows with is_instrumented=False do not contribute heatmap cells."""
        # 1. Test generate_pen_map with bouts for C11-C16
        bouts_with_untracked = [
            {
                "cow_id": "C12",
                "x_m": -2.0,
                "y_m": 1.0,
                "duration_min": 45.0,
                "is_instrumented": False,
            },
            {
                "cow_id": "C15",
                "center_x_m": 0.0,
                "center_y_m": 0.0,
                "duration_min": 60.0,
            },
            {
                "cow_id": "C01",
                "x_m": 5.0,
                "y_m": 2.0,
                "duration_min": 35.0,
                "is_instrumented": True,
            },
        ]
        p = generate_pen_map(lying_bouts=bouts_with_untracked)
        heatmap = p["grid"]["heatmap"]
        # Only C01's bout should contribute; total non-zero cells in heatmap should be exactly 1
        non_zero_cells = [val for row in heatmap for val in row if val > 0]
        self.assertEqual(len(non_zero_cells), 1)

        # 2. Test generate_barn_overview with C11-C16 cows
        from visualization.payloads import generate_barn_overview
        cows_overview = [
            {
                "cow_id": "C01",
                "uwb_x_m": 15.0,
                "uwb_y_m": 7.5,
                "is_instrumented": True,
            },
            {
                "cow_id": "C12",
                "uwb_x_m": 0.0,
                "uwb_y_m": 0.0,
                "is_instrumented": False,
            },
            {
                "cow_id": "C13",
                "uwb_x_m": None,
                "uwb_y_m": None,
            },
        ]
        barn = generate_barn_overview(cows_data=cows_overview)
        matrix = barn["heatmap_grid"]["density_matrix"]
        # Only C01 should contribute, cell (0, 0) should remain 0.0
        self.assertEqual(matrix[0][0], 0.0)
        total_density = sum(sum(row) for row in matrix)
        self.assertAlmostEqual(total_density, 1.0)
        c12_rec = next(c for c in barn["cows"] if c["cow_id"] == "C12")
        self.assertIsNone(c12_rec["uwb_x_m"])
        self.assertFalse(c12_rec["is_instrumented"])

    def test_heatmap_negative_centered_coordinates_projection(self):
        """Verifies negative centered MMCows coordinates project to valid interior grid cells without (0, 0) clamping."""
        centered_bouts = [
            {
                "cow_id": "C01",
                "x_m": -4.2,
                "y_m": 2.1,
                "duration_min": 40.0,
                "is_instrumented": True,
            },
            {
                "cow_id": "C03",
                "x_m": float("nan"),
                "y_m": float("nan"),
                "duration_min": 50.0,
            },
        ]
        p = generate_pen_map(lying_bouts=centered_bouts)
        heatmap = p["grid"]["heatmap"]
        # Top-left cell (0, 0) must NOT be clamped to
        self.assertEqual(heatmap[0][0], 0.0)
        # Expected grid indices:
        # gx = int(((-4.2 - (-12.45)) / 24.9) * 30) = int((8.25 / 24.9) * 30) = int(9.939) = 9
        # gy = int(((2.1 - (-9.31)) / 17.7) * 15) = int((11.41 / 17.7) * 15) = int(9.669) = 9
        self.assertGreater(heatmap[9][9], 0.0)
        self.assertEqual(p["coordinate_system"], "centered")
        self.assertEqual(p["grid"]["origin"], "center")
        self.assertEqual(p["grid"]["x_min_m"], -12.45)
        self.assertEqual(p["grid"]["x_max_m"], 12.45)
        self.assertEqual(p["grid"]["y_min_m"], -9.31)
        self.assertEqual(p["grid"]["y_max_m"], 8.39)

    def test_heatmap_empty_when_no_qualifying_bouts(self):
        """Verifies explicitly passing empty or short bouts yields an empty heatmap rather than fallback fixture."""
        # 1. Empty list
        p_empty = generate_pen_map(lying_bouts=[])
        heatmap_empty = p_empty["grid"]["heatmap"]
        max_density = max(max(row) for row in heatmap_empty)
        self.assertEqual(max_density, 0.0)

        # 2. Only bouts < 20 min (below resting occupancy threshold)
        short_bouts = [
            {"cow_id": "C01", "x_m": 5.0, "y_m": 2.0, "duration_min": 12.0},
            {"cow_id": "C02", "x_m": -3.0, "y_m": 1.0, "duration_min": 8.5},
        ]
        p_short = generate_pen_map(lying_bouts=short_bouts)
        self.assertEqual(max(max(row) for row in p_short["grid"]["heatmap"]), 0.0)

        # 3. Only NaN coordinate bouts
        nan_bouts = [
            {"cow_id": "C01", "x_m": float("nan"), "y_m": float("nan"), "duration_min": 45.0},
        ]
        p_nan = generate_pen_map(lying_bouts=nan_bouts)
        self.assertEqual(max(max(row) for row in p_nan["grid"]["heatmap"]), 0.0)

    def test_heatmap_provenance_real_vs_fallback(self):
        """Verifies is_synthetic flag and fallback cubicle blocks when lying_bouts is None."""
        # When lying_bouts is None: synthetic fallback cubicle rows A & B
        p_fallback = generate_pen_map(lying_bouts=None, is_synthetic=True)
        self.assertTrue(p_fallback["is_synthetic"])
        # Check standard resting zone values
        self.assertGreater(p_fallback["grid"]["heatmap"][3][10], 0.0)
        self.assertGreater(p_fallback["grid"]["heatmap"][10][10], 0.0)

        # When real bouts are supplied with is_synthetic=False
        p_real = generate_pen_map(
            lying_bouts=[{"cow_id": "C01", "x_m": 12.0, "y_m": 6.0, "duration_min": 35.0}],
            is_synthetic=False,
        )
        self.assertFalse(p_real["is_synthetic"])


if __name__ == "__main__":
    unittest.main()
