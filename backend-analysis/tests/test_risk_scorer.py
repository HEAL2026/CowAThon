"""Tests for multimodal watch-list risk scoring and graceful degradation."""

import unittest
import pandas as pd
from analysis.risk_scorer import MultimodalRiskScorer


class TestRiskScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = MultimodalRiskScorer()

    def test_healthy_baseline_cow(self):
        record = {
            "cow_id": "cow_01",
            "ts_utc": "2026-07-25T10:00:00Z",
            "cbt": 38.7,
            "thi": 64.0,
            "activity_index": 0.035,
            "rumination_proxy": 85.0,
            "milk_drop_pct": 0.5,
            "idling_fraction": 0.3,
        }
        res = self.scorer.score_record(record)
        self.assertLess(res["watch_risk_score"], 40.0)
        self.assertEqual(res["risk_category"], "baseline")
        self.assertAlmostEqual(res["confidence_score"], 1.0, delta=0.05)
        self.assertTrue(res["is_model_suggestion"])

    def test_distressed_priority_watch_cow(self):
        record = {
            "cow_id": "cow_02",
            "ts_utc": "2026-07-25T10:00:00Z",
            "cbt": 40.2, # Elevated fever / heat strain
            "thi": 76.0, # High environmental THI
            "activity_index": 0.010, # Lethargy
            "rumination_proxy": 15.0, # Depressed rumination
            "milk_drop_pct": 18.0, # Significant milk drop
            "idling_fraction": 0.8,
        }
        res = self.scorer.score_record(record)
        self.assertGreaterEqual(res["watch_risk_score"], 70.0)
        self.assertEqual(res["risk_category"], "priority_watch")
        self.assertTrue(any("CBT elevated" in f for f in res["contributing_factors"]))
        self.assertTrue(any("THI indicates heat stress" in f for f in res["contributing_factors"]))
        self.assertTrue(len(res["recommended_actions"]) > 0)

    def test_graceful_missing_modality_degradation(self):
        # Record with no CBT (e.g. bolus not yet swallowed or detached)
        record = {
            "cow_id": "cow_03",
            "ts_utc": "2026-07-25T10:00:00Z",
            "cbt": None,
            "thi": 75.0,
            "activity_index": 0.03,
            "rumination_proxy": 45.0,
            "milk_drop_pct": 2.0,
        }
        res = self.scorer.score_record(record)
        # Should gracefully compute score without crashing
        self.assertIn("cbt", res["missing_modalities"])
        self.assertNotIn("cbt", res["modalities_present"])
        # Confidence score should decrease
        self.assertLess(res["confidence_score"], 0.8)
        self.assertGreaterEqual(res["watch_risk_score"], 0.0)
        self.assertLessEqual(res["watch_risk_score"], 100.0)


if __name__ == "__main__":
    unittest.main()
