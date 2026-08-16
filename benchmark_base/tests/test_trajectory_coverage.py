from __future__ import annotations

import math
import unittest

from benchmark_base.lib.trajectory_coverage import coverage_against_input, summarize_timestamps


class TrajectoryCoverageTest(unittest.TestCase):
    def test_summary_reports_rate_periods_and_large_gaps(self) -> None:
        stats = summarize_timestamps([0.0, 0.1, 0.2, 0.3, 0.6])
        self.assertEqual(5, stats.count)
        self.assertAlmostEqual(0.0, stats.first_s)
        self.assertAlmostEqual(0.6, stats.last_s)
        self.assertAlmostEqual(0.6, stats.duration_s)
        self.assertAlmostEqual(4.0 / 0.6, stats.effective_hz)
        self.assertAlmostEqual(0.1, stats.median_period_s)
        self.assertAlmostEqual(0.27, stats.p95_period_s)
        self.assertAlmostEqual(0.3, stats.max_period_s)
        self.assertEqual(1, stats.gap_count_over_1p5x_median)

    def test_single_timestamp_has_no_rate_or_period_statistics(self) -> None:
        stats = summarize_timestamps([4.0])
        self.assertEqual(1, stats.count)
        self.assertEqual(0.0, stats.duration_s)
        self.assertIsNone(stats.effective_hz)
        self.assertIsNone(stats.median_period_s)
        self.assertIsNone(stats.p95_period_s)
        self.assertIsNone(stats.max_period_s)
        self.assertEqual(0, stats.gap_count_over_1p5x_median)

    def test_empty_timestamp_series_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one timestamp"):
            summarize_timestamps([])

    def test_nonfinite_and_nonincreasing_timestamps_fail_closed(self) -> None:
        for values in ([0.0, math.nan], [0.0, 0.0], [0.1, 0.0]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    summarize_timestamps(values)

    def test_coverage_describes_boundary_lag_and_count_ratio(self) -> None:
        coverage = coverage_against_input(
            [10.0, 10.1, 10.2, 10.3, 10.4],
            [10.1, 10.2, 10.3],
        )
        self.assertEqual(5, coverage["input_count"])
        self.assertEqual(3, coverage["output_count"])
        self.assertAlmostEqual(0.6, coverage["output_to_input_count_ratio"])
        self.assertAlmostEqual(0.1, coverage["first_output_lag_from_input_s"])
        self.assertAlmostEqual(-0.1, coverage["last_output_delta_to_input_end_s"])

    def test_coverage_rejects_output_outside_input_time_domain(self) -> None:
        with self.assertRaisesRegex(ValueError, "starts before input"):
            coverage_against_input([1.0, 2.0], [0.9, 1.5])
        with self.assertRaisesRegex(ValueError, "ends after input"):
            coverage_against_input([1.0, 2.0], [1.5, 2.1])


if __name__ == "__main__":
    unittest.main()
