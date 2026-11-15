"""
Unit and contract conformance tests for backend-visualization payloads.
Runs seamlessly with both standard library unittest and pytest.
"""

import os
import json
import tempfile
import re
import unittest

from visualization.payloads import (
    generate_barn_overview,
    generate_cow_timeseries,
    generate_milking_stalls,
    generate_watch_list,
    generate_integrations_feasibility,
)
from visualization.fixtures import (
    generate_mock_cows_overview,
    generate_mock_timeseries,
)
from visualization.exporter import export_all_payloads


class TestVisualizationPayloads(unittest.TestCase):

    def test_barn_overview_contract(self):
        cows = generate_mock_cows_overview(seed=42)
        payload = generate_barn_overview(
            cows_data=cows,
            indoor_thi=73.2,
            indoor_temp_c=25.4,
            indoor_humidity_pct=62.0,
            ts_utc="2026-07-25T14:00:00Z",
            is_synthetic=True,
        )

        self.assertEqual(payload["barn_id"], "main_barn_01")
        self.assertEqual(payload["indoor_thi"], 73.2)
        self.assertTrue(payload["is_synthetic"])
        self.assertEqual(len(payload["cows"]), 16)

        first_cow = payload["cows"][0]
        required_cow_fields = [
            "cow_id", "x_coord", "y_coord", "zone", "activity_state",
            "risk_status", "risk_score", "factors", "on_watch_list",
            "vet_flagged", "missing_modalities"
        ]
        for field in required_cow_fields:
            self.assertIn(field, first_cow, f"Missing field {field} in cow record")

        self.assertIsInstance(first_cow["missing_modalities"], list)

        # Validate heatmap grid
        grid_meta = payload["heatmap_grid"]
        self.assertEqual(grid_meta["width"], 20)
        self.assertEqual(grid_meta["height"], 10)
        matrix = grid_meta["density_matrix"]
        self.assertEqual(len(matrix), 10)
        self.assertEqual(len(matrix[0]), 20)
        for row in matrix:
            for val in row:
                self.assertTrue(0.0 <= val <= 1.0)

    def test_cow_timeseries_contract_and_imputation(self):
        points = generate_mock_timeseries("Fern_221", days=3, cadence_hours=2, seed=12)
        payload = generate_cow_timeseries(
            cow_id="Fern_221",
            timeseries_points=points,
            baseline_yield_l=28.0,
        )

        self.assertEqual(payload["cow_id"], "Fern_221")
        self.assertIn("start_utc", payload["data_range"])
        self.assertIn("end_utc", payload["data_range"])

        summary = payload["summary"]
        self.assertIn("mean_cbt_c", summary)
        self.assertIn("cbt_anomaly_detected", summary)
        self.assertIn(summary["status"], ["within_baseline", "elevated_risk"])

        # Test imputation transparency
        ts_list = payload["timeseries"]
        self.assertGreater(len(ts_list), 0)
        for pt in ts_list:
            self.assertIn("cbt_c_is_imputed", pt)
            self.assertIn("neck_imu_magnitude_mean_is_imputed", pt)
            self.assertIn("daily_milk_yield_l_is_imputed", pt)
            self.assertIn("indoor_thi_is_imputed", pt)
            self.assertIsInstance(pt["cbt_c_is_imputed"], bool)
            self.assertIsInstance(pt["daily_milk_yield_l_is_imputed"], bool)

    def test_milking_stalls_contract(self):
        payload = generate_milking_stalls(num_stalls=8, ts_utc="2026-07-25T14:00:00Z")
        self.assertEqual(payload["parlor_id"], "parlor_alpha")
        self.assertEqual(len(payload["stalls"]), 8)

        stall = payload["stalls"][0]
        self.assertIn("stall_number", stall)
        self.assertIn(stall["state"], ["active", "idle", "cleaning"])
        self.assertIn("last_completed_cycle", stall)

    def test_watch_list_uncertainty_and_missing_modalities(self):
        flagged = [
            {
                "cow_id": "Fern_221",
                "flag_type": "model_suggestion",
                "watch_reason": "Sustained high CBT under elevated THI accompanied by 18% yield decrease",
                "confidence": 0.84,
                "modalities_present": ["cbt", "neck_imu", "indoor_env", "milk_yield"],
                "modalities_missing": ["uwb"],
                "missing_modality_impact": "Location confidence lower; utilizing last-seen stall beacon",
                "recommended_action": "Check for heat abatement and udder inflammation prior to next cycle",
            }
        ]
        payload = generate_watch_list(flagged, ts_utc="2026-07-25T14:00:00Z")
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["confidence"], 0.84)
        self.assertIn("uwb", item["modalities_missing"])
        self.assertEqual(len(item["modalities_present"]), 4)
        self.assertGreater(len(item["missing_modality_impact"]), 0)

    def test_integrations_feasibility_contract(self):
        payload = generate_integrations_feasibility()
        systems = payload["systems"]
        self.assertGreaterEqual(len(systems), 4)
        for sys in systems:
            self.assertIn("adapter_id", sys)
            self.assertIn("attached", sys)
            self.assertIn("annual_cost_per_head_usd", sys)
            self.assertIn("feasibility_tier", sys)
            self.assertTrue(sys["is_synthetic"])

    def test_clinical_diagnosis_wording_guardrail(self):
        """
        Enforces track prompt mandate: No unsupported clinical diagnoses in output.
        Recursively scans strings for disallowed clinical terminology.
        """
        forbidden_terms = [
            r"\bdiagnos(?:is|ed|ing)\b",
            r"\billness\b",
            r"\bdisease\b",
            r"\bsick\b",
            r"\bcured\b",
            r"\bconfirmed_mastitis\b",
        ]
        pattern = re.compile("|".join(forbidden_terms), re.IGNORECASE)

        cows = generate_mock_cows_overview()
        barn = generate_barn_overview(cows_data=cows)
        cow_ts = generate_cow_timeseries("Fern_221", generate_mock_timeseries("Fern_221"))
        stalls = generate_milking_stalls()
        watch = generate_watch_list([
            {
                "cow_id": "Fern_221",
                "flag_type": "model_suggestion",
                "watch_reason": "Sustained high CBT under elevated THI",
                "confidence": 0.85,
                "recommended_action": "Visual check",
            }
        ])

        all_payloads = [barn, cow_ts, stalls, watch]

        def scan_obj(obj, path=""):
            if isinstance(obj, str):
                match = pattern.search(obj)
                self.assertIsNone(match, f"Forbidden diagnostic term '{match.group(0) if match else ''}' in {path}: {obj}")
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    scan_obj(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    scan_obj(item, f"{path}[{idx}]")

        for p in all_payloads:
            scan_obj(p)

    def test_exporter_runs_successfully(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exported = export_all_payloads(tmpdir)
            self.assertTrue(os.path.exists(exported["barn_overview"]))
            self.assertTrue(os.path.exists(exported["milking_stalls"]))
            self.assertTrue(os.path.exists(exported["watch_list"]))
            self.assertTrue(os.path.exists(exported["integrations_feasibility"]))
            self.assertTrue(os.path.isdir(exported["cows_dir"]))

            with open(exported["barn_overview"], "r", encoding="utf-8") as f:
                data = json.load(f)
                self.assertEqual(data["barn_id"], "main_barn_01")


if __name__ == "__main__":
    unittest.main()
