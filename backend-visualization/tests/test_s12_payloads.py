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
for p in [REPO_ROOT / "backend-visualization", REPO_ROOT / "backend-cleaning", REPO_ROOT / "apis"]:
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

        # Bounds check across all 16 cows
        for payload in [p1, p2, p3]:
            for cow in payload["cows"]:
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


if __name__ == "__main__":
    unittest.main()
