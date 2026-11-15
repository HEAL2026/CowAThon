"""Unit tests for analysis CLI runner (analysis.run)."""

import unittest
import json
import tempfile
from pathlib import Path
import pandas as pd

from analysis.fixtures import generate_synthetic_mmcows_data
from analysis.run import run_cli, find_default_parquet_path


class TestAnalysisRunCLI(unittest.TestCase):
    def test_run_cli_fallback_to_synthetic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "output"
            code = run_cli([
                "--parquet", "/nonexistent/path/to/joined_1min.parquet",
                "--out", str(out_dir),
                "--quiet",
            ])
            self.assertEqual(code, 0)

            summary_file = out_dir / "cow_risk_summary.json"
            benchmark_file = out_dir / "benchmark_results.json"
            timeseries_file = out_dir / "analyzed_timeseries.parquet"

            self.assertTrue(summary_file.exists())
            self.assertTrue(benchmark_file.exists())
            self.assertTrue(timeseries_file.exists())

            with open(summary_file, "r", encoding="utf-8") as f:
                summary = json.load(f)
            self.assertEqual(len(summary), 10)
            self.assertTrue(summary["C01"]["is_synthetic"])

            with open(benchmark_file, "r", encoding="utf-8") as f:
                benchmarks = json.load(f)
            self.assertTrue(benchmarks["is_synthetic"])

    def test_run_cli_no_fallback_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code = run_cli([
                "--parquet", "/nonexistent/path/to/joined_1min.parquet",
                "--out", str(tmpdir),
                "--no-fallback",
                "--quiet",
            ])
            self.assertEqual(code, 1)

    def test_run_cli_with_real_parquet_and_cow_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            parquet_path = tmp_path / "mock_joined_1min.parquet"
            out_dir = tmp_path / "output"

            # Create realistic mock parquet
            df = generate_synthetic_mmcows_data(n_cows=4, n_minutes=20, seed=123)
            df.to_parquet(parquet_path, index=False)

            code = run_cli([
                "--parquet", str(parquet_path),
                "--out", str(out_dir),
                "--cows", "C01,C03",
                "--n-splits", "2",
                "--quiet",
            ])
            self.assertEqual(code, 0)

            summary_file = out_dir / "cow_risk_summary.json"
            self.assertTrue(summary_file.exists())

            with open(summary_file, "r", encoding="utf-8") as f:
                summary = json.load(f)

            self.assertEqual(sorted(list(summary.keys())), ["C01", "C03"])
            self.assertFalse(summary["C01"]["is_synthetic"])

    def test_run_cli_export_vis_dir_includes_backtrace_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            out_dir = tmp_path / "output"
            vis_dir = tmp_path / "vis_export"

            code = run_cli([
                "--out", str(out_dir),
                "--export-vis-dir", str(vis_dir),
                "--quiet",
            ])
            self.assertEqual(code, 0)

            backtrace_file = vis_dir / "backtrace_result.json"
            self.assertTrue(backtrace_file.exists())
            with open(backtrace_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("likely_route", data)
            self.assertIn("implicated_resting_areas", data)
            self.assertTrue(data["is_model_suggestion"])


if __name__ == "__main__":
    unittest.main()
