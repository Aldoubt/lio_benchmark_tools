from __future__ import annotations

import unittest

import numpy as np

from benchmark_base.lib.display_alignment import (
    apply_display_transform_pose,
    apply_display_transform_xyz,
    compute_display_alignment,
)
from benchmark_base.lib.trajectory import PoseSample, quaternion_from_rpy, rpy_from_quaternion


class DisplayAlignmentContractTest(unittest.TestCase):
    def test_none_is_identity(self) -> None:
        pose = self._pose(3.0, 4.0, 5.0, 0.1, -0.2, 0.7)
        matrix = compute_display_alignment(pose, "NONE")
        np.testing.assert_allclose(matrix, np.eye(4), atol=1e-12)

    def test_start_xy_yaw_zeroes_only_start_xy_and_yaw(self) -> None:
        pose = self._pose(3.0, 4.0, 5.0, 0.1, -0.2, 0.7)
        matrix = compute_display_alignment(pose, "START_XY_YAW")
        position, quaternion = apply_display_transform_pose(
            (pose.x_m, pose.y_m, pose.z_m),
            (pose.qx, pose.qy, pose.qz, pose.qw),
            matrix,
        )
        roll, pitch, yaw = rpy_from_quaternion(*quaternion)
        self.assertAlmostEqual(0.0, position[0], places=10)
        self.assertAlmostEqual(0.0, position[1], places=10)
        self.assertAlmostEqual(5.0, position[2], places=10)
        self.assertAlmostEqual(0.1, roll, places=10)
        self.assertAlmostEqual(-0.2, pitch, places=10)
        self.assertAlmostEqual(0.0, yaw, places=10)

    def test_subsequent_relative_drift_is_not_fit_away(self) -> None:
        initial = self._pose(10.0, -4.0, 2.0, 0.0, 0.0, 0.5)
        matrix = compute_display_alignment(initial, "START_XY_YAW")
        points = np.array([[10.0, -4.0, 2.0], [12.0, -1.0, 4.0]], dtype=np.float64)
        transformed = apply_display_transform_xyz(points, matrix)
        self.assertAlmostEqual(2.0, transformed[0, 2])
        self.assertAlmostEqual(4.0, transformed[1, 2])
        self.assertGreater(np.linalg.norm(transformed[1, :2]), 0.0)

    def test_input_point_array_is_not_modified(self) -> None:
        pose = self._pose(1.0, 2.0, 3.0, 0.0, 0.0, 0.3)
        points = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float64)
        before = points.copy()
        apply_display_transform_xyz(points, compute_display_alignment(pose, "START_XY_YAW"))
        np.testing.assert_array_equal(before, points)

    def test_unknown_alignment_mode_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            compute_display_alignment(self._pose(0, 0, 0, 0, 0, 0), "ICP")

    @staticmethod
    def _pose(x: float, y: float, z: float, roll: float, pitch: float, yaw: float) -> PoseSample:
        qx, qy, qz, qw = quaternion_from_rpy(roll, pitch, yaw)
        return PoseSample(
            timestamp_s=0.0,
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
            source_topic="unit",
        )


if __name__ == "__main__":
    unittest.main()
