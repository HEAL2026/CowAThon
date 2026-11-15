"""Tests verifying leak-free cross-validation and baseline benchmarking."""

import unittest
import numpy as np
import pandas as pd
from analysis.fixtures import generate_synthetic_mmcows_data
from analysis.evaluation import group_kfold, assert_no_group_leakage
from analysis.baselines import evaluate_baselines_vs_multimodal


class TestLeakFreeEvaluation(unittest.TestCase):
    def setUp(self):
        self.df = generate_synthetic_mmcows_data(n_cows=10, n_minutes=60, seed=42)

    def test_group_kfold_zero_animal_leakage(self):
        folds = group_kfold(self.df, by="cow_id", n_splits=5, seed=0)
        self.assertEqual(len(folds), 5)

        for fold_idx, (train_df, val_df) in enumerate(folds):
            # Assert no cow is in both splits
            assert_no_group_leakage(train_df, val_df, by="cow_id")

            # Check that validation cows are a proper subset
            train_cows = set(train_df["cow_id"])
            val_cows = set(val_df["cow_id"])
            self.assertEqual(len(train_cows & val_cows), 0)
            self.assertEqual(len(train_cows | val_cows), 10)
            # With 10 cows and 5 folds, each fold holds exactly 2 cows
            self.assertEqual(len(val_cows), 2)
            self.assertEqual(len(train_cows), 8)

    def test_baseline_vs_multimodal_benchmarks(self):
        results = evaluate_baselines_vs_multimodal(
            self.df,
            target_col="is_elevated_risk",
            group_col="cow_id",
            n_splits=5,
            seed=0,
        )

        self.assertEqual(results["dataset"], "MMCows Challenge 1")
        self.assertEqual(results["n_groups"], 10)
        self.assertEqual(results["n_splits"], 5)

        # Baselines exist and have mean/std
        thi_base = results["baselines"]["thi_threshold_baseline"]
        cbt_base = results["baselines"]["cbt_threshold_baseline"]
        multi = results["multimodal_model"]

        for model in [thi_base, cbt_base, multi]:
            self.assertIn("roc_auc_mean", model)
            self.assertIn("roc_auc_std", model)
            self.assertIn("balanced_accuracy_mean", model)
            self.assertIn("f1_mean", model)
            self.assertGreaterEqual(model["roc_auc_mean"], 0.0)
            self.assertLessEqual(model["roc_auc_mean"], 1.0)

        # Multimodal model should show positive lift over environmental baseline
        self.assertGreater(results["multimodal_lift_over_env_baseline_auc"], 0.0)


if __name__ == "__main__":
    unittest.main()
