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
    generate_milking_stalls,
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

        # Single cow run (offline / no result: returns is_synthetic=True and empty resources per spec v2 §7)
        payload = generate_backtrace_run(flags=[{"cow_id": "C01"}], lookback_hours=72)
        self.assertIn(payload["likely_route"], canonical_routes)
        self.assertIn("p_values", payload)
        self.assertIn("resting_areas", payload)
        self.assertIn("implicated_resting_areas", payload)
        self.assertIn("resources", payload)
        self.assertIn("impact", payload)
        self.assertIn("transmission_source", payload)
        self.assertEqual(payload["impact"]["flagged_early_count"], 1)
        self.assertTrue(payload["is_synthetic"])
        self.assertIn("resting_spots", payload["resources"])
        self.assertIn("milking_units", payload["resources"])
        if payload["resources"]["resting_spots"]:
            self.assertEqual(len(payload["resources"]["resting_spots"]), 5)
            self.assertEqual(payload["resources"]["resting_spots"][0]["spot_id"], "spot_01")

        # Multi-cow group run
        payload_multi = generate_backtrace_run(target_cows=["C01", "C02"], lookback_hours=72)
        self.assertIn(payload_multi["likely_route"], canonical_routes)
        self.assertEqual(payload_multi["impact"]["flagged_early_count"], 2)
        self.assertTrue(payload_multi["is_synthetic"])
        if payload_multi["resources"]["resting_spots"]:
            self.assertEqual(len(payload_multi["resources"]["resting_spots"]), 5)

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
        """Verifies generate_backtrace_run handles service exceptions without UnboundLocalError and returns empty resources."""
        from unittest.mock import patch
        with patch("apis.icar.service.IcarAdeService.run_backtrace", side_effect=RuntimeError("Simulated failure")):
            run = generate_backtrace_run(flags=[{"cow_id": "C01"}], lookback_hours=72)
            self.assertIn("likely_route", run)
            self.assertIn("resting_areas", run)
            self.assertIn("impact", run)
            self.assertEqual(len(run["resting_areas"]), 0)
            self.assertEqual(run["resources"]["resting_spots"], [])
            self.assertTrue(run["is_synthetic"])

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
        self.assertEqual(len(p["resting_spots"]), 5)
        self.assertEqual(p["resting_spots"][0]["spot_id"], "spot_01")
        self.assertEqual(p["resting_spots"][0]["center_x_m"], 0.06)
        self.assertEqual(p["resting_spots"][0]["center_y_m"], 0.00)

    def test_pen_map_positive_coordinate_system(self):
        """Verifies pen map defaults to positive coordinates for synthetic fixtures."""
        p = generate_pen_map(ts_utc="2023-07-28T14:00:00Z")
        self.assertEqual(p["coordinate_system"], "positive")
        self.assertEqual(p["grid"]["origin"], "bottom_left")
        self.assertEqual(p["grid"]["x_min_m"], 0.0)
        self.assertEqual(p["grid"]["x_max_m"], 30.0)
        self.assertEqual(len(p["resting_spots"]), 5)
        self.assertEqual(p["resting_spots"][0]["spot_id"], "spot_01")
        self.assertEqual(p["resting_spots"][0]["center_x_m"], 12.51)
        self.assertEqual(p["resting_spots"][0]["center_y_m"], 9.31)

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

    def test_resting_areas_real_missing_centered_and_bottom_left_frames(self):
        """
        Verifies resting area coordinates handling across:
        1) Real source coordinates preserved verbatim (never hardcoded over);
        2) Missing coordinates in centered frame fallback to cubicle row B (-2.4, 1.5);
        3) Missing coordinates in bottom_left frame fallback to (12.4, 10.2);
        4) Explicit empty list preserved without fallback injection.
        """
        # 1. Real coordinates in centered frame: must preserve exact source coordinates
        real_resting = [
            {
                "area_id": "real_circle_c01",
                "center_x_m": -5.25,
                "center_y_m": 0.75,
                "radius_m": 1.5,
                "zone_id": "cubicle_row_b",
                "target_cow_id": "C01",
            }
        ]
        centered_cows = [{"cow_id": "C01", "uwb_x_m": -5.0, "uwb_y_m": 1.0}]
        p_real = generate_pen_map(cows_data=centered_cows, resting_areas=real_resting, is_synthetic=False)
        self.assertFalse(p_real["is_synthetic"])
        self.assertEqual(len(p_real["resting_areas"]), 1)
        self.assertEqual(p_real["resting_areas"][0]["center_x_m"], -5.25)
        self.assertEqual(p_real["resting_areas"][0]["center_y_m"], 0.75)
        self.assertEqual(p_real["coordinate_system"], "centered")
        self.assertEqual(p_real["grid"]["origin"], "center")

        # 2. Missing coordinates in centered frame: 5 canonical spots (spot_01 is (0.06, 0.00))
        p_missing_centered = generate_pen_map(cows_data=centered_cows, resting_areas=None, is_synthetic=False)
        self.assertEqual(len(p_missing_centered["resting_spots"]), 5)
        self.assertEqual(p_missing_centered["resting_spots"][0]["spot_id"], "spot_01")
        self.assertEqual(p_missing_centered["resting_spots"][0]["center_x_m"], 0.06)
        self.assertEqual(p_missing_centered["resting_spots"][0]["center_y_m"], 0.00)
        self.assertEqual(p_missing_centered["coordinate_system"], "centered")
        self.assertEqual(p_missing_centered["grid"]["origin"], "center")
        self.assertEqual(p_missing_centered["grid"]["x_min_m"], -12.45)
        self.assertEqual(p_missing_centered["grid"]["x_max_m"], 12.45)
        self.assertEqual(p_missing_centered["grid"]["y_min_m"], -9.31)
        self.assertEqual(p_missing_centered["grid"]["y_max_m"], 8.39)

        # 3. Missing coordinates in bottom_left (positive) frame: shifted to (12.51, 9.31)
        pos_cows = [{"cow_id": "C01", "uwb_x_m": 15.0, "uwb_y_m": 7.5}]
        p_missing_pos = generate_pen_map(cows_data=pos_cows, resting_areas=None, is_synthetic=True)
        self.assertEqual(len(p_missing_pos["resting_spots"]), 5)
        self.assertEqual(p_missing_pos["resting_spots"][0]["spot_id"], "spot_01")
        self.assertEqual(p_missing_pos["resting_spots"][0]["center_x_m"], 12.51)
        self.assertEqual(p_missing_pos["resting_spots"][0]["center_y_m"], 9.31)
        self.assertEqual(p_missing_pos["coordinate_system"], "positive")
        self.assertEqual(p_missing_pos["grid"]["origin"], "bottom_left")
        self.assertEqual(p_missing_pos["grid"]["x_min_m"], 0.0)
        self.assertEqual(p_missing_pos["grid"]["x_max_m"], 30.0)
        self.assertEqual(p_missing_pos["grid"]["y_min_m"], 0.0)
        self.assertEqual(p_missing_pos["grid"]["y_max_m"], 15.0)

        # 4. Explicit empty list: preserved without fallback injection
        p_empty = generate_pen_map(cows_data=centered_cows, resting_areas=[], is_synthetic=False)
        self.assertEqual(p_empty["resting_areas"], [])
        self.assertEqual(p_empty["implicated_circles"], [])

    def test_attribution_provenance_and_fallback_semantics(self):
        """
        Verifies attribution payload provenance and fallback semantics:
        1) is_synthetic is explicitly set and preserved on returned payload;
        2) Real analysis attribution preserves real resting areas and is_synthetic=False;
        3) Fallback fixture emits is_synthetic=True and deterministic resting areas;
        4) get_attribution_data() accurately returns (payload, is_synthetic).
        """
        # 1. Real attribution data from analysis output
        real_backtrace = {
            "likely_route": "resting_area",
            "p_values": {"resting_permutation_p": 0.012, "milking_permutation_p": 0.35},
            "implicated_resting_areas": [
                {"area_id": "real_area_01", "center_x_m": -3.2, "center_y_m": 1.1, "radius_m": 1.5}
            ],
            "is_synthetic": False,
        }
        p_real = generate_attribution(attribution_data=real_backtrace, is_synthetic=False)
        self.assertFalse(p_real["is_synthetic"])
        self.assertEqual(p_real["implicated_resting_areas"][0]["center_x_m"], -3.2)
        self.assertEqual(p_real["implicated_resting_areas"][0]["center_y_m"], 1.1)

        # 2. Fallback attribution fixture (empty resources per spec v2 §7, zero invented geometry)
        p_fallback = generate_attribution(attribution_data=None, is_synthetic=True)
        self.assertTrue(p_fallback["is_synthetic"])
        self.assertIn("implicated_resting_areas", p_fallback)
        self.assertEqual(p_fallback["implicated_resting_areas"], [])
        self.assertEqual(p_fallback["resources"]["resting_spots"], [])
        self.assertEqual(p_fallback["resources"]["milking_units"], [])

        # 3. data_loader get_attribution_data fallback
        p_loaded, is_synth = get_attribution_data()
        self.assertIsInstance(is_synth, bool)
        self.assertEqual(p_loaded["is_synthetic"], is_synth)

    def test_attribution_section_6_payload_surfaced_unchanged(self):
        """Verifies Section 6 payload is surfaced unchanged per docs/backtrace_spec.md §7."""
        sec6 = {
            "investigation_window": {
                "start_utc": "2023-07-25T14:00:00Z",
                "end_utc": "2023-07-28T14:00:00Z",
                "anchor": "onset",
            },
            "flagged_cows": [{"cow_id": "C06", "role": "index", "onset_utc": "2023-07-25T14:00:00Z"}],
            "resources": {
                "resting_spots": [
                    {
                        "spot_id": "spot_01",
                        "center_x_m": -2.4,
                        "center_y_m": 1.5,
                        "radius_m": 1.5,
                        "n_flagged": 1,
                        "flagged_cows": ["C06"],
                        "dwell_min_by_flagged": {"C06": 120.0},
                        "successors": [{"cow_id": "C07", "rank": 1, "lag_h": 2.5, "w": 0.85}],
                        "until_bedding_change_utc": "2023-07-28T06:00:00Z",
                        "provenance": "real",
                    }
                ],
                "milking_units": [
                    {
                        "unit_id": "unit_02",
                        "n_flagged": 1,
                        "flagged_cows": ["C06"],
                        "sessions": ["sess_01"],
                        "successors": [{"cow_id": "C07", "rank": 1, "session_id": "sess_01", "w": 0.65}],
                        "sanitized_between": False,
                        "provenance": "synthetic",
                    }
                ],
            },
            "exposed_cows": [
                {
                    "cow_id": "C07",
                    "e": 4.01,
                    "e_rest": 3.16,
                    "e_milk": 0.85,
                    "tier": "high",
                    "primary_route": "resting_spot",
                    "via": [{"resource": "spot_01", "predecessor": "C06", "w": 0.85}],
                }
            ],
            "route": {
                "likely_route": "resting_spot",
                "z_rest": 1.85,
                "z_milk": 0.22,
                "p_rest": 0.085,
                "p_milk": 0.42,
                "p_floor": 0.012,
                "n_permutations": 1000,
            },
            "provenance": {
                "lying_bouts": "real",
                "milking_log": "synthetic",
                "sanitation": "synthetic",
                "bedding": "synthetic",
            },
            "is_model_suggestion": True,
            "is_synthetic": False,
        }
        res = generate_attribution(attribution_data=sec6)
        self.assertEqual(res["investigation_window"]["anchor"], "onset")
        self.assertEqual(res["resources"]["resting_spots"][0]["spot_id"], "spot_01")
        self.assertEqual(res["resources"]["milking_units"][0]["unit_id"], "unit_02")
        self.assertEqual(res["exposed_cows"][0]["cow_id"], "C07")
        self.assertEqual(res["route"]["likely_route"], "resting_spot")
        self.assertFalse(res["is_synthetic"])
        self.assertEqual(res["resting_areas"][0]["spot_id"], "spot_01")

    def test_milking_stalls_succession_contract(self):
        """Verifies /api/milking-stalls is driven by milking_log successions and flags."""
        stalls_payload = generate_milking_stalls(num_stalls=8, ts_utc="2023-07-28T14:00:00Z")
        self.assertEqual(stalls_payload["parlor_id"], "parlor_alpha")
        self.assertEqual(len(stalls_payload["stalls"]), 8)
        self.assertTrue(stalls_payload["is_synthetic"])
        self.assertEqual(stalls_payload["provenance"]["milking_log"], "synthetic")

        for stall in stalls_payload["stalls"]:
            self.assertIn("stall_number", stall)
            self.assertIn("unit_id", stall)
            self.assertIn(stall["state"], ["active", "idle"])
            self.assertIn("last_completed_cycle", stall)
            self.assertIn("successors", stall)
            self.assertIn("predecessor", stall)
            self.assertIn("sanitized_between", stall)

    def test_pen_map_resting_spots_five_rows_and_successors(self):
        """
        Verifies pen map resting layer emits 5 spots (spot_01..spot_05) on y ~ 0
        carrying n_flagged, flagged_cows, and successors per docs/backtrace_spec.md §3.2 & §6.
        """
        payload = generate_pen_map()
        self.assertIn("resting_spots", payload)
        self.assertIn("resting_areas", payload)
        spots = payload["resting_spots"]
        self.assertEqual(len(spots), 5)
        spot_ids = [s["spot_id"] for s in spots]
        self.assertEqual(spot_ids, ["spot_01", "spot_02", "spot_03", "spot_04", "spot_05"])

        s1 = spots[0]
        self.assertEqual(s1["spot_id"], "spot_01")
        self.assertIn("n_flagged", s1)
        self.assertIn("flagged_cows", s1)
        self.assertIn("successors", s1)
        self.assertGreaterEqual(len(s1["successors"]), 1)
        self.assertIn("rank", s1["successors"][0])
        self.assertIn("lag_h", s1["successors"][0])
        self.assertIn("w", s1["successors"][0])
        self.assertEqual(s1["radius_m"], 1.5)

    def test_pen_map_herd_size_and_zero_default_flags_and_grid_bounds(self):
        """
        Verifies:
        1. When real cows are passed without flags, n_flagged is 0 across all resting spots;
        2. Grid emits non-null explicit x_min, x_max, y_min, y_max, width, height aliases;
        3. Flagging a specific cow (e.g. C01) increments n_flagged on its implicated spots;
        4. get_pen_map_data honours flagged_cows parameter without phantom cows.
        """
        # 1. 10 unflagged cows in centered frame
        ten_unflagged = [{"cow_id": f"C{i:02d}", "uwb_x_m": -2.5 + i * 0.5, "uwb_y_m": 0.5, "flag_status": "unflagged"} for i in range(1, 11)]
        p_unflagged = generate_pen_map(cows_data=ten_unflagged)
        self.assertEqual(len(p_unflagged["cows"]), 10)
        self.assertEqual(p_unflagged["grid"]["x_min"], -12.45)
        self.assertEqual(p_unflagged["grid"]["x_max"], 12.45)
        self.assertEqual(p_unflagged["grid"]["y_min"], -9.31)
        self.assertEqual(p_unflagged["grid"]["y_max"], 8.39)
        self.assertEqual(p_unflagged["grid"]["width"], 24.9)
        self.assertEqual(p_unflagged["grid"]["height"], 17.7)

        for spot in p_unflagged["resting_spots"]:
            self.assertEqual(spot["n_flagged"], 0)
            self.assertEqual(spot["flagged_cows"], [])
            self.assertEqual(spot["dwell_min_by_flagged"], {})

        # 2. Flagging C01
        ten_with_c01 = [{"cow_id": f"C{i:02d}", "uwb_x_m": -2.5 + i * 0.5, "uwb_y_m": 0.5, "flag_status": "flagged" if i == 1 else "unflagged"} for i in range(1, 11)]
        p_flagged = generate_pen_map(cows_data=ten_with_c01)
        s1 = next(s for s in p_flagged["resting_spots"] if s["spot_id"] == "spot_01")
        self.assertEqual(s1["n_flagged"], 1)
        self.assertEqual(s1["flagged_cows"], ["C01"])

        # 3. get_pen_map_data honours flagged_cows parameter
        p_data, is_syn = get_pen_map_data(flagged_cows=["C01"])
        c01 = next(c for c in p_data["cows"] if c["cow_id"] == "C01")
        self.assertEqual(c01["flag_status"], "flagged")
        c02 = next(c for c in p_data["cows"] if c["cow_id"] == "C02")
        self.assertEqual(c02["flag_status"], "unflagged")

    def test_pen_map_resting_spots_window_scoping(self):
        """
        Verifies:
        1. C06 alone flags only spot_01 (n_flagged=1), spot_02..spot_05 remain n_flagged=0;
        2. C06 + C05 still has spot_01 n_flagged=1 (C05 is on milking route, 0 resting dwell);
        3. C06 + C01 sets spot_01 n_flagged=2 (triggering strong highlight tier);
        4. Dynamic calculation from lying_bouts within [ts_utc - 48h, ts_utc] scopes dwell accurately.
        """
        # 1. C06 alone
        cows_c06 = [{"cow_id": f"C{i:02d}", "uwb_x_m": -2.0, "uwb_y_m": 0.5, "flag_status": "flagged" if i == 6 else "unflagged"} for i in range(1, 11)]
        p1 = generate_pen_map(cows_data=cows_c06)
        s1 = next(s for s in p1["resting_spots"] if s["spot_id"] == "spot_01")
        self.assertEqual(s1["n_flagged"], 1)
        self.assertEqual(s1["flagged_cows"], ["C06"])
        self.assertGreater(s1["dwell_min_by_flagged"]["C06"], 0)
        for sp in p1["resting_spots"]:
            if sp["spot_id"] != "spot_01":
                self.assertEqual(sp["n_flagged"], 0)
                self.assertEqual(sp["flagged_cows"], [])

        # 2. C06 + C05: C05 is on milking U2 route, zero resting dwell
        cows_c06_c05 = [{"cow_id": f"C{i:02d}", "uwb_x_m": -2.0, "uwb_y_m": 0.5, "flag_status": "flagged" if i in [5, 6] else "unflagged"} for i in range(1, 11)]
        p2 = generate_pen_map(cows_data=cows_c06_c05)
        s1_p2 = next(s for s in p2["resting_spots"] if s["spot_id"] == "spot_01")
        self.assertEqual(s1_p2["n_flagged"], 1)
        self.assertEqual(s1_p2["flagged_cows"], ["C06"])
        for sp in p2["resting_spots"]:
            if sp["spot_id"] != "spot_01":
                self.assertEqual(sp["n_flagged"], 0)

        # 3. C06 + C01: both in spot_01 -> n_flagged=2 (strong highlight)
        cows_c06_c01 = [{"cow_id": f"C{i:02d}", "uwb_x_m": -2.0, "uwb_y_m": 0.5, "flag_status": "flagged" if i in [1, 6] else "unflagged"} for i in range(1, 11)]
        p3 = generate_pen_map(cows_data=cows_c06_c01)
        s1_p3 = next(s for s in p3["resting_spots"] if s["spot_id"] == "spot_01")
        self.assertEqual(s1_p3["n_flagged"], 2)
        self.assertEqual(set(s1_p3["flagged_cows"]), {"C01", "C06"})

        # 4. Dynamic bout computation with time window
        bouts = [
            # In-window bout for C06 at spot_01 (0.06, 0.0)
            {
                "cow_id": "C06",
                "x_m": 0.10,
                "y_m": 0.05,
                "start_utc": "2023-07-28T10:00:00Z",
                "end_utc": "2023-07-28T12:30:00Z",
                "duration_min": 150.0,
            },
            # Out-of-window bout for C06 (5 days prior)
            {
                "cow_id": "C06",
                "x_m": -2.80,
                "y_m": 0.02,
                "start_utc": "2023-07-20T10:00:00Z",
                "end_utc": "2023-07-20T12:00:00Z",
                "duration_min": 120.0,
            },
        ]
        p_dyn = generate_pen_map(
            cows_data=cows_c06,
            lying_bouts=bouts,
            ts_utc="2023-07-28T14:00:00Z",
            lookback_hours=48,
        )
        s1_dyn = next(s for s in p_dyn["resting_spots"] if s["spot_id"] == "spot_01")
        self.assertEqual(s1_dyn["n_flagged"], 1)
        self.assertEqual(s1_dyn["dwell_min_by_flagged"]["C06"], 150.0)
        s2_dyn = next(s for s in p_dyn["resting_spots"] if s["spot_id"] == "spot_02")
        self.assertEqual(s2_dyn["n_flagged"], 0)


if __name__ == "__main__":
    unittest.main()
