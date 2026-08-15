from __future__ import annotations

import math
import unittest

from benchmark_base.lib.trajectory import (
    PoseSample,
    Trajectory,
    TrajectoryMatchError,
    quaternion_from_rpy,
    rpy_from_quaternion,
)


def sample(t: float, x: float, yaw: float, *, sign: float = 1.0) -> PoseSample:
    q = quaternion_from_rpy(0.0, 0.0, yaw)
    q = tuple(sign * value for value in q)
    return PoseSample(t, x, 0.0, 0.0, q[0], q[1], q[2], q[3], 0.0, 0.0, yaw, "/odom")


class TrajectoryTest(unittest.TestCase):
    def test_exact_timestamp_returns_original_pose(self) -> None:
        trajectory = Trajectory((sample(1.0, 0.0, 0.0), sample(2.0, 1.0, 0.2)))
        match = trajectory.interpolate_pose(1.0, tolerance_s=0.1)
        self.assertTrue(match.exact)
        self.assertEqual(0.0, match.pose.x_m)

    def test_midpoint_interpolates_position_and_orientation(self) -> None:
        trajectory = Trajectory((sample(0.0, 0.0, 0.0), sample(1.0, 2.0, math.pi / 2)))
        match = trajectory.interpolate_pose(0.5, tolerance_s=0.5)
        self.assertFalse(match.exact)
        self.assertAlmostEqual(1.0, match.pose.x_m)
        _, _, yaw = rpy_from_quaternion(match.pose.qx, match.pose.qy, match.pose.qz, match.pose.qw)
        self.assertAlmostEqual(math.pi / 4, yaw, places=6)
        self.assertAlmostEqual(1.0, match.interpolation_gap_s)

    def test_sign_flipped_equivalent_quaternion_uses_shortest_arc(self) -> None:
        trajectory = Trajectory((sample(0.0, 0.0, 0.2), sample(1.0, 1.0, 0.2, sign=-1.0)))
        match = trajectory.interpolate_pose(0.5, tolerance_s=0.5)
        _, _, yaw = rpy_from_quaternion(match.pose.qx, match.pose.qy, match.pose.qz, match.pose.qw)
        self.assertAlmostEqual(0.2, yaw, places=6)

    def test_out_of_range_timestamp_is_rejected(self) -> None:
        trajectory = Trajectory((sample(1.0, 0.0, 0.0), sample(2.0, 1.0, 0.0)))
        with self.assertRaises(TrajectoryMatchError):
            trajectory.interpolate_pose(0.9, tolerance_s=1.0)

    def test_nearest_sample_tolerance_is_enforced(self) -> None:
        trajectory = Trajectory((sample(0.0, 0.0, 0.0), sample(1.0, 1.0, 0.0)))
        with self.assertRaisesRegex(TrajectoryMatchError, "exceeds tolerance"):
            trajectory.interpolate_pose(0.5, tolerance_s=0.1)

    def test_duplicate_timestamps_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            Trajectory((sample(1.0, 0.0, 0.0), sample(1.0, 1.0, 0.0)))


if __name__ == "__main__":
    unittest.main()
