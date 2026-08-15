from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.trajectory import PoseSample, Trajectory, quaternion_from_rpy
from reporting.diagnostics import (
    collect_run_diagnostics,
    pairwise_disagreement,
    trajectory_diagnostics,
    write_run_diagnostics,
)


class EstimatorDivergenceDiagnosticsTest(unittest.TestCase):
    def test_trajectory_diagnostics_are_descriptive(self) -> None:
        trajectory = self._trajectory(
            [
                (0.0, 0.0, 0.0, 1.0, 0.10, -0.20, 3.00),
                (1.0, 1.0, 0.0, 2.0, 0.15, -0.10, -3.10),
                (2.0, 1.0, 2.0, 4.0, 0.20, 0.00, -2.90),
            ]
        )
        result = trajectory_diagnostics(trajectory)
        self.assertEqual(3, result.samples)
        self.assertAlmostEqual(2.0, result.duration_s)
        self.assertAlmostEqual(1.0, result.delta_x_m)
        self.assertAlmostEqual(2.0, result.delta_y_m)
        self.assertAlmostEqual(3.0, result.delta_z_m)
        self.assertAlmostEqual(3.0, result.z_range_m)
        self.assertAlmostEqual(0.10, result.roll_range_rad)
        self.assertAlmostEqual(0.20, result.pitch_range_rad)
        # 3.00 -> -2.90 crosses the +/-pi boundary; unwrap must report the small forward turn.
        self.assertAlmostEqual((2.0 * math.pi - 2.90) - 3.00, result.yaw_change_rad, places=9)
        self.assertGreater(result.path_length_m, 0.0)

    def test_warmup_uses_interpolated_boundary_without_deleting_raw_data(self) -> None:
        trajectory = self._trajectory(
            [
                (10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                (11.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                (12.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ]
        )
        result = trajectory_diagnostics(trajectory, warmup_s=0.5)
        self.assertEqual(3, result.samples)  # interpolated boundary + two original samples
        self.assertAlmostEqual(1.5, result.duration_s)
        self.assertAlmostEqual(3.0, result.delta_x_m)
        self.assertEqual(3, len(trajectory.samples))  # source remains unchanged

    def test_warmup_that_removes_usable_interval_fails_closed(self) -> None:
        trajectory = self._trajectory(
            [
                (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                (1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ]
        )
        with self.assertRaises(ValueError):
            trajectory_diagnostics(trajectory, warmup_s=1.0)

    def test_pairwise_disagreement_uses_timestamp_interpolation_not_index_matching(self) -> None:
        left = self._trajectory(
            [
                (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                (1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                (2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ]
        )
        right = self._trajectory(
            [
                (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                (0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0),
                (1.5, 1.5, 0.0, 0.0, 0.0, 0.0, 0.0),
                (2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ]
        )
        result = pairwise_disagreement(left, right, sample_period_s=0.25, alignment_mode="NONE")
        self.assertGreaterEqual(result.sample_count, 8)
        self.assertAlmostEqual(0.0, result.xy_rmse_m, places=10)
        self.assertAlmostEqual(0.0, result.z_rmse_m, places=10)
        self.assertAlmostEqual(0.0, result.xyz_rmse_m, places=10)

    def test_start_xy_yaw_removes_only_arbitrary_planar_origin_and_heading(self) -> None:
        left = self._trajectory(
            [
                (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
                (1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0),
                (2.0, 2.0, 0.0, 1.0, 0.0, 0.0, 0.0),
            ]
        )
        right = self._trajectory(
            [
                (0.0, 10.0, 20.0, 3.0, 0.0, 0.0, math.pi / 2.0),
                (1.0, 10.0, 21.0, 3.0, 0.0, 0.0, math.pi / 2.0),
                (2.0, 10.0, 22.0, 3.0, 0.0, 0.0, math.pi / 2.0),
            ]
        )
        result = pairwise_disagreement(left, right, sample_period_s=0.5, alignment_mode="START_XY_YAW")
        self.assertAlmostEqual(0.0, result.xy_rmse_m, places=9)
        self.assertAlmostEqual(2.0, result.z_rmse_m, places=9)  # Z is deliberately preserved
        self.assertEqual("START_XY_YAW", result.alignment_mode)

    def test_pairwise_unknown_alignment_fails_closed(self) -> None:
        trajectory = self._trajectory(
            [
                (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                (1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ]
        )
        with self.assertRaises(ValueError):
            pairwise_disagreement(trajectory, trajectory, alignment_mode="ICP")

    def test_run_collection_preserves_missing_algorithms_and_writes_pairwise_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            (run / "standardized/trajectories").mkdir(parents=True)
            a = self._trajectory([
                (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                (1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                (2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            ])
            b = self._trajectory([
                (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
                (1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0),
                (2.0, 2.0, 0.0, 1.0, 0.0, 0.0, 0.0),
            ])
            a.write_csv(run / "standardized/trajectories/a.csv")
            b.write_csv(run / "standardized/trajectories/b.csv")
            (run / "manifest.json").write_text(json.dumps({
                "dataset": {"calibration": {"status": "BLOCKED_CALIBRATION"}},
                "algorithms": {"a": {}, "b": {}, "missing": {}},
            }), encoding="utf-8")

            algorithms, pairs, details = collect_run_diagnostics(
                run,
                ["a", "b", "missing"],
                warmup_s=0.0,
                alignment_mode="START_XY_YAW",
                sample_period_s=0.5,
            )
            self.assertEqual(3, len(algorithms))
            missing = next(row for row in algorithms if row.algorithm_id == "missing")
            self.assertEqual("MISSING", missing.trajectory_status)
            self.assertIsNone(missing.duration_s)
            self.assertEqual("BLOCKED_CALIBRATION", missing.calibration_status)
            self.assertEqual(1, len(pairs))
            self.assertEqual(("a", "b"), (pairs[0].left_algorithm_id, pairs[0].right_algorithm_id))
            self.assertAlmostEqual(1.0, pairs[0].z_rmse_m)
            self.assertIn(("a", "b"), details)

            write_run_diagnostics(run, algorithms, pairs)
            smoke_path = run / "metrics/smoke_diagnostics.csv"
            pair_path = run / "metrics/pairwise_disagreement.csv"
            self.assertTrue(smoke_path.is_file())
            self.assertTrue(pair_path.is_file())
            with smoke_path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            missing_csv = next(row for row in rows if row["algorithm_id"] == "missing")
            self.assertEqual("", missing_csv["duration_s"])
            self.assertEqual("MISSING", missing_csv["trajectory_status"])

    @staticmethod
    def _trajectory(rows: list[tuple[float, float, float, float, float, float, float]]) -> Trajectory:
        samples = []
        for timestamp, x, y, z, roll, pitch, yaw in rows:
            qx, qy, qz, qw = quaternion_from_rpy(roll, pitch, yaw)
            samples.append(
                PoseSample(
                    timestamp_s=timestamp,
                    x_m=x,
                    y_m=y,
                    z_m=z,
                    qx=qx,
                    qy=qy,
                    qz=qz,
                    qw=qw,
                    roll_rad=roll,
                    pitch_rad=pitch,
                    yaw_rad=yaw,
                    source_topic="/test",
                )
            )
        return Trajectory(samples)


if __name__ == "__main__":
    unittest.main()
