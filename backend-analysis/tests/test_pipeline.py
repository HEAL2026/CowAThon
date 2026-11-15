"""Integration tests for end-to-end backend analysis pipeline."""

import unittest
import json
import tempfile
from pathlib import Path
import pandas as pd

from tests.fixtures import generate_synthetic_mmcows_data
from analysis.pipeline import run_analysis_pipeline


class TestPipelineIntegration(unittest.TestCase):
    def setUp(self):
        self.df = generate_synthetic_mmcows_data(n_cows=10, n_minutes=30, seed=42)

    def test_run_analysis_pipeline_and_export(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)
            result = run_analysis_pipeline(
                self.df,
                output_dir=out_path,
                n_cv_splits=5,
                seed=0,
            )

            # Check return structure
            self.assertIn("cow_summaries", result)
            self.assertIn("benchmarks", result)
            self.assertIn("analyzed_df", result)

            self.assertEqual(len(result["cow_summaries"]), 10)
            cow_01 = result["cow_summaries"]["C01"]
            self.assertIn("watch_risk_score", cow_01)
            self.assertIn("risk_category", cow_01)
            self.assertIn("confidence_score", cow_01)
            self.assertIn("metrics", cow_01)
            self.assertIn("contributing_factors", cow_01)
            self.assertIn("recommended_actions", cow_01)
            self.assertTrue(cow_01["is_model_suggestion"])

            # Verify exported files exist
            summary_file = out_path / "cow_risk_summary.json"
            benchmark_file = out_path / "benchmark_results.json"
            timeseries_file = out_path / "analyzed_timeseries.parquet"

            self.assertTrue(summary_file.exists())
            self.assertTrue(benchmark_file.exists())
            self.assertTrue(timeseries_file.exists())

            # Validate JSON loads cleanly
            with open(summary_file, "r", encoding="utf-8") as f:
                loaded_summary = json.load(f)
            self.assertEqual(len(loaded_summary), 10)

            with open(benchmark_file, "r", encoding="utf-8") as f:
                loaded_benchmarks = json.load(f)
            self.assertIn("baselines", loaded_benchmarks)
            self.assertIn("multimodal_model", loaded_benchmarks)

            # Validate Parquet file loads cleanly
            df_loaded = pd.read_parquet(timeseries_file)
            self.assertIn("watch_risk_score", df_loaded.columns)
            self.assertIn("indoor_thi", df_loaded.columns)
            self.assertIn("activity_index", df_loaded.columns)


if __name__ == "__main__":
    unittest.main()
