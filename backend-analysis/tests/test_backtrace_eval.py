"""Unit tests for S11 outbreak backtrace evaluation benchmark."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
import pandas as pd

from analysis.backtrace import generate_synthetic_backtrace_fixtures
from analysis.backtrace_eval import (
    evaluate_synthetic_episode,
    evaluate_backtrace_against_synthetic,
    _check_source_hit,
    _parse_source,
)


class TestBacktraceEvaluation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_source_and_check_source_hit(self):
        raw_json = '{"unit_id": "STALL-01", "session_id": "2023-07-25_AM"}'
        parsed = _parse_source(raw_json)
        self.assertEqual(parsed["unit_id"], "STALL-01")

        # Source hit testing
        self.assertTrue(_check_source_hit("milking_equipment", parsed, ["STALL-01", "STALL-02"]))
        self.assertFalse(_check_source_hit("milking_equipment", parsed, ["STALL-02", "STALL-03"]))

        # Resting area cells
        cell_src = {"cells": [[2, 1], [2, 2]]}
        self.assertTrue(_check_source_hit("resting_area", cell_src, ["cubicle_row_a:cell_X2_Y1"]))
        self.assertTrue(_check_source_hit("no_common_route", {}, []))

    def test_evaluate_synthetic_episode_resting(self):
        bouts, milk, bed, san = generate_synthetic_backtrace_fixtures(scenario="resting")
        res = evaluate_synthetic_episode(
            scenario="resting_route",
            true_route="resting_area",
            true_source={"cells": [[2, 1]], "cell_id": "cubicle_row_a:cell_X2_Y1"},
            index_cow="C02",
            secondary_cows=["C01"],
            lying_bouts_df=bouts,
            milking_log_df=milk,
            bedding_df=bed,
            sanitation_df=san,
            n_permutations=50,
            seed=42,
        )
        self.assertTrue(res["route_match"])
        self.assertEqual(res["predicted_route"], "resting_area")
        self.assertTrue(res["source_hit"])
        self.assertEqual(res["precision_at_k"].get("1"), 1.0)
        self.assertEqual(res["recall_at_k"].get("1"), 1.0)

    def test_evaluate_synthetic_episode_milking(self):
        bouts, milk, bed, san = generate_synthetic_backtrace_fixtures(scenario="milking")
        res = evaluate_synthetic_episode(
            scenario="milking_route",
            true_route="milking_equipment",
            true_source={"unit_id": "STALL-01"},
            index_cow="C02",
            secondary_cows=["C01"],
            lying_bouts_df=bouts,
            milking_log_df=milk,
            bedding_df=bed,
            sanitation_df=san,
            n_permutations=50,
            seed=42,
        )
        self.assertTrue(res["route_match"])
        self.assertEqual(res["predicted_route"], "milking_equipment")
        self.assertTrue(res["source_hit"])
        self.assertEqual(res["precision_at_k"].get("1"), 1.0)
        self.assertEqual(res["recall_at_k"].get("1"), 1.0)

    def test_evaluate_synthetic_episode_sporadic(self):
        bouts, milk, bed, san = generate_synthetic_backtrace_fixtures(scenario="sporadic")
        res = evaluate_synthetic_episode(
            scenario="sporadic",
            true_route="no_common_route",
            true_source={},
            index_cow=None,
            secondary_cows=["C02", "C01"],
            lying_bouts_df=bouts,
            milking_log_df=milk,
            bedding_df=bed,
            sanitation_df=san,
            n_permutations=30,
            seed=42,
        )
        self.assertTrue(res["route_match"])
        self.assertEqual(res["predicted_route"], "no_common_route")
        self.assertTrue(res["source_hit"])

    def test_full_benchmark_suite_execution(self):
        summary = evaluate_backtrace_against_synthetic(
            output_dir=self.temp_dir,
            n_permutations=50,
            seed=42,
        )

        self.assertEqual(summary["total_episodes"], 3)
        self.assertEqual(summary["route_accuracy"], 1.0)
        self.assertEqual(summary["source_hit_rate"], 1.0)
        self.assertEqual(summary["overall_precision_at_1"], 1.0)
        self.assertEqual(summary["overall_recall_at_1"], 1.0)

        # Verify exported json
        exported = Path(self.temp_dir) / "backtrace_benchmark.json"
        self.assertTrue(exported.exists())
        with open(exported, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["route_accuracy"], 1.0)

    def test_benchmark_with_custom_labels_dataframe(self):
        custom_labels = pd.DataFrame([
            {
                "scenario": "milking_route",
                "cow_id": "C02",
                "role": "index",
                "true_route": "milking_equipment",
                "true_source": json.dumps({"unit_id": "STALL-01"}),
            },
            {
                "scenario": "milking_route",
                "cow_id": "C01",
                "role": "secondary",
                "true_route": "milking_equipment",
                "true_source": json.dumps({"unit_id": "STALL-01"}),
            },
        ])

        summary = evaluate_backtrace_against_synthetic(
            synthetic_labels=custom_labels,
            output_dir=self.temp_dir,
            n_permutations=40,
            seed=42,
        )

        self.assertEqual(summary["total_episodes"], 1)
        self.assertEqual(summary["route_accuracy"], 1.0)
        self.assertEqual(summary["source_hit_rate"], 1.0)

    def test_multi_day_historical_episode_with_reference_time(self):
        # 14-day dataset fixture: exposure occurred on day 2, dataset ends on day 14
        base_t = pd.Timestamp("2023-07-01 08:00:00", tz="UTC")
        day2_t = base_t + pd.Timedelta(days=1)
        day14_t = base_t + pd.Timedelta(days=13)

        milking_rows = [
            {"cow_id": "C02", "milking_time": day2_t + pd.Timedelta(hours=1), "unit_id": "STALL-01"},
            {"cow_id": "C01", "milking_time": day2_t + pd.Timedelta(hours=1, minutes=15), "unit_id": "STALL-01"},
        ]
        # Filler data up to day 14 for other cows
        for d in range(3, 14):
            milking_rows.append({
                "cow_id": f"C{(d % 6) + 4:02d}",
                "milking_time": base_t + pd.Timedelta(days=d),
                "unit_id": "STALL-03",
            })
        milking_df = pd.DataFrame(milking_rows)

        # Sanitation 2 hours after C01 on STALL-01
        san_df = pd.DataFrame([
            {"unit_id": "STALL-01", "sanitized_at": day2_t + pd.Timedelta(hours=3)},
        ])

        from analysis.backtrace import backtrace

        # Test A: Pass explicit reference_time matching day 2
        res_explicit = backtrace(
            flags=[{"cow_id": "C02"}, {"cow_id": "C01"}],
            lookback_hours=72,
            milking_log_df=milking_df,
            sanitation_df=san_df,
            reference_time=day2_t + pd.Timedelta(hours=2),
            n_permutations=50,
            seed=42,
        )
        self.assertEqual(res_explicit["likely_route"], "milking_equipment")
        self.assertLess(res_explicit["p_values"]["milking_equipment"], 0.05)

        # Test B: Pass flags with timestamps (inferred reference_time)
        flags_with_ts = [
            {"cow_id": "C02", "dx_utc": (day2_t + pd.Timedelta(hours=2)).isoformat()},
            {"cow_id": "C01", "dx_utc": (day2_t + pd.Timedelta(hours=4)).isoformat()},
        ]
        res_inferred = backtrace(
            flags=flags_with_ts,
            lookback_hours=72,
            milking_log_df=milking_df,
            sanitation_df=san_df,
            n_permutations=50,
            seed=42,
        )
        self.assertEqual(res_inferred["likely_route"], "milking_equipment")
        self.assertLess(res_inferred["p_values"]["milking_equipment"], 0.05)

    def test_scenario_without_explicit_index_role(self):
        # Scenario where 'role' column is absent, but 'onset_utc' specifies timeline
        labels_no_role = pd.DataFrame([
            {
                "scenario": "milking_route",
                "cow_id": "C02",
                "onset_utc": pd.Timestamp("2023-07-25 08:00:00", tz="UTC"),
                "dx_utc": pd.Timestamp("2023-07-25 12:00:00", tz="UTC"),
                "true_route": "milking_equipment",
                "true_source": json.dumps({"unit_id": "STALL-01"}),
            },
            {
                "scenario": "milking_route",
                "cow_id": "C01",
                "onset_utc": pd.Timestamp("2023-07-25 10:00:00", tz="UTC"),
                "dx_utc": pd.Timestamp("2023-07-25 14:00:00", tz="UTC"),
                "true_route": "milking_equipment",
                "true_source": json.dumps({"unit_id": "STALL-01"}),
            },
        ])

        summary = evaluate_backtrace_against_synthetic(
            synthetic_labels=labels_no_role,
            output_dir=self.temp_dir,
            n_permutations=40,
            seed=42,
        )

        ep = summary["episodes"][0]
        # Inferred index cow should be C02 (earliest onset_utc)
        self.assertEqual(ep["index_cow"], "C02")
        self.assertEqual(ep["secondary_cows"], ["C01"])
        self.assertTrue(ep["route_match"])
        self.assertTrue(ep["source_hit"])


if __name__ == "__main__":
    unittest.main()
