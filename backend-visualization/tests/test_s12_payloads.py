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

    def test_herd_health_table_vitality_and_risk(self):
        payload = generate_herd_health()
        cows = payload["cows"]
        self.assertEqual(len(cows), 16)

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
        self.assertEqual(payload["likely_route"], "resting_cubicle_route")
        probs = payload["route_probabilities"]
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=2)
        p_vals = payload["p_values"]
        self.assertIn("resting_permutation_p", p_vals)
        self.assertIn("milking_permutation_p", p_vals)

        pathogens = payload["pathogen_group_likelihood"]
        self.assertIn("coliform_environmental_gram_negative", pathogens)
        self.assertIn("streptococci_environmental_gram_positive", pathogens)
        self.assertIn("statement", pathogens)
        self.assertTrue(payload["is_model_suggestion"])

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
        ]

        def check_text(val: str, path: str):
            for pat in forbidden_patterns:
                # Disallow clinical diagnosis assertions, but allow explanatory disclaimers like "not a clinical diagnosis"
                matches = re.finditer(pat, val, re.IGNORECASE)
                for m in matches:
                    snippet = val[max(0, m.start() - 25):min(len(val), m.end() + 25)].lower()
                    if "not a clinical diagnosis" in snippet or "never diagnosis" in snippet:
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


if __name__ == "__main__":
    unittest.main()
