from __future__ import annotations

import math
import unittest

from benchmark_base.lib.frame_audit import (
    RawPoseObservation,
    build_frame_audit,
    quaternion_angle_difference,
)
from benchmark_base.lib.trajectory import PoseSample, quaternion_from_rpy


class TrajectoryFrameAuditTest(unittest.TestCase):
    def test_build_audit_preserves_raw_frame_semantics_and_compares_standardized_first_pose(self) -> None:
        raw_q = quaternion_from_rpy(0.1, 0.65, -0.2)
        std_q = quaternion_from_rpy(0.1, 0.65, -0.2)
        observations = (
            RawPoseObservation(
                timestamp_s=10.0,
                parent_frame_id="camera_init",
                child_frame_id="body",
                x_m=1.0,
                y_m=2.0,
                z_m=3.0,
                qx=raw_q[0],
                qy=raw_q[1],
                qz=raw_q[2],
                qw=raw_q[3],
            ),
            RawPoseObservation(
                timestamp_s=11.0,
                parent_frame_id="camera_init",
                child_frame_id="body",
                x_m=2.0,
                y_m=2.0,
                z_m=3.0,
                qx=raw_q[0],
                qy=raw_q[1],
                qz=raw_q[2],
                qw=raw_q[3],
            ),
        )
        standardized = PoseSample(
            timestamp_s=10.0,
            x_m=1.0,
            y_m=2.0,
            z_m=3.0,
            qx=std_q[0],
            qy=std_q[1],
            qz=std_q[2],
            qw=std_q[3],
            roll_rad=0.1,
            pitch_rad=0.65,
            yaw_rad=-0.2,
            source_topic="/aft_mapped_to_init",
        )

        audit = build_frame_audit(
            algorithm_id="fast_livo2",
            source_topic="/aft_mapped_to_init",
            message_type="nav_msgs/msg/Odometry",
            raw_bag="/tmp/raw/fast_livo_trajectory",
            observations=observations,
            standardized_first=standardized,
            declared_pose_represents="UNKNOWN",
            declared_world_frame_semantics="UNKNOWN",
        )

        self.assertEqual("AVAILABLE", audit.status)
        self.assertEqual(("camera_init",), audit.parent_frame_ids)
        self.assertEqual(("body",), audit.child_frame_ids)
        self.assertEqual(0, audit.parent_frame_change_count)
        self.assertEqual(0, audit.child_frame_change_count)
        self.assertAlmostEqual(0.65, audit.raw_first_pitch_rad)
        self.assertAlmostEqual(0.0, audit.raw_to_standardized_first_position_delta_m)
        self.assertAlmostEqual(0.0, audit.raw_to_standardized_first_orientation_delta_rad)
        self.assertEqual("T_parent_child", audit.pose_semantics)
        self.assertEqual("UNKNOWN", audit.declared_pose_represents)
        self.assertEqual("UNKNOWN", audit.declared_world_frame_semantics)

    def test_frame_changes_are_counted_without_guessing_frame_identity(self) -> None:
        q = quaternion_from_rpy(0.0, 0.0, 0.0)
        observations = (
            RawPoseObservation(0.0, "odom", "lidar", 0.0, 0.0, 0.0, *q),
            RawPoseObservation(1.0, "odom", "lidar", 1.0, 0.0, 0.0, *q),
            RawPoseObservation(2.0, "map", "base_link", 2.0, 0.0, 0.0, *q),
        )
        audit = build_frame_audit(
            algorithm_id="example",
            source_topic="/odom",
            message_type="nav_msgs/msg/Odometry",
            raw_bag="/tmp/example",
            observations=observations,
            standardized_first=None,
        )
        self.assertEqual(("map", "odom"), audit.parent_frame_ids)
        self.assertEqual(("base_link", "lidar"), audit.child_frame_ids)
        self.assertEqual(1, audit.parent_frame_change_count)
        self.assertEqual(1, audit.child_frame_change_count)
        self.assertEqual("UNKNOWN", audit.declared_pose_represents)

    def test_quaternion_angle_difference_is_sign_invariant(self) -> None:
        q = quaternion_from_rpy(0.0, 0.0, math.pi / 2.0)
        self.assertAlmostEqual(0.0, quaternion_angle_difference(q, tuple(-v for v in q)), places=12)
        identity = quaternion_from_rpy(0.0, 0.0, 0.0)
        self.assertAlmostEqual(math.pi / 2.0, quaternion_angle_difference(identity, q), places=12)

    def test_empty_observations_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            build_frame_audit(
                algorithm_id="missing",
                source_topic="/odom",
                message_type="nav_msgs/msg/Odometry",
                raw_bag="/tmp/missing",
                observations=(),
                standardized_first=None,
            )


if __name__ == "__main__":
    unittest.main()
