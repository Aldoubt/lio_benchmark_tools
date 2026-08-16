from __future__ import annotations

import math
from pathlib import Path
import unittest

from benchmark_base.lib.frame_audit import RawPoseObservation
from benchmark_base.lib.trajectory import TrajectoryError
from benchmark_base.lib.trajectory_from_run import (
    build_trajectory_standardization_metadata,
    trajectory_from_observations,
)


class TrajectoryFromRunContractTest(unittest.TestCase):
    def _observation(
        self,
        *,
        timestamp_s: float,
        x: float = 1.0,
        y: float = 2.0,
        z: float = 3.0,
        qx: float = 0.0,
        qy: float = 0.0,
        qz: float = 0.0,
        qw: float = 2.0,
    ) -> RawPoseObservation:
        return RawPoseObservation(
            timestamp_s=timestamp_s,
            parent_frame_id="odom",
            child_frame_id="sensor",
            x_m=x,
            y_m=y,
            z_m=z,
            qx=qx,
            qy=qy,
            qz=qz,
            qw=qw,
        )

    def test_conversion_preserves_pose_values_and_source_topic(self) -> None:
        trajectory = trajectory_from_observations(
            (
                self._observation(timestamp_s=10.0, x=1.25, y=-2.5, z=0.75),
                self._observation(timestamp_s=10.1, x=1.5, y=-2.0, z=1.0),
            ),
            source_topic="/Odometry",
        )
        first = trajectory.samples[0]
        self.assertEqual(10.0, first.timestamp_s)
        self.assertEqual((1.25, -2.5, 0.75), (first.x_m, first.y_m, first.z_m))
        self.assertEqual((0.0, 0.0, 0.0, 1.0), (first.qx, first.qy, first.qz, first.qw))
        self.assertEqual((0.0, 0.0, 0.0), (first.roll_rad, first.pitch_rad, first.yaw_rad))
        self.assertEqual("/Odometry", first.source_topic)

    def test_conversion_derives_rpy_from_normalized_quaternion_without_frame_transform(self) -> None:
        half = math.sqrt(0.5)
        trajectory = trajectory_from_observations(
            (
                self._observation(timestamp_s=1.0, x=4.0, y=5.0, z=6.0, qz=half * 2.0, qw=half * 2.0),
                self._observation(timestamp_s=2.0, x=7.0, y=8.0, z=9.0, qz=half * 2.0, qw=half * 2.0),
            ),
            source_topic="/kiss/odometry",
        )
        first = trajectory.samples[0]
        self.assertEqual((4.0, 5.0, 6.0), (first.x_m, first.y_m, first.z_m))
        self.assertAlmostEqual(0.0, first.roll_rad, places=12)
        self.assertAlmostEqual(0.0, first.pitch_rad, places=12)
        self.assertAlmostEqual(math.pi / 2.0, first.yaw_rad, places=12)

    def test_non_monotonic_timestamps_fail_through_existing_trajectory_contract(self) -> None:
        with self.assertRaisesRegex(TrajectoryError, "strictly increasing"):
            trajectory_from_observations(
                (
                    self._observation(timestamp_s=2.0),
                    self._observation(timestamp_s=2.0),
                ),
                source_topic="/Odometry",
            )

    def test_metadata_records_run_local_rosbag_source_and_output_contract(self) -> None:
        metadata = build_trajectory_standardization_metadata(
            algorithm_id="fast_lio2",
            source_bag="/runs/smoke/raw/fast_lio2/fast_lio2_outputs",
            source_topic="/Odometry",
            source_message_type="nav_msgs/msg/Odometry",
            sample_count=139,
            start_timestamp_s=100.0,
            end_timestamp_s=113.8,
            output="standardized/trajectories/fast_lio2.csv",
        )
        self.assertEqual(1, metadata["schema_version"])
        self.assertEqual("fast_lio2", metadata["algorithm_id"])
        self.assertEqual("RUN_LOCAL_ROS2_BAG", metadata["source_kind"])
        self.assertEqual("HEADER_STAMP_ELSE_BAG_RECORD_TIME", metadata["timestamp_policy"])
        self.assertEqual(139, metadata["sample_count"])
        self.assertEqual("standardized/trajectories/fast_lio2.csv", metadata["output"])

    def test_frame_audit_consumes_shared_rosbag_reader_instead_of_defining_its_own(self) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / "evaluators/audit_trajectory_frames.py").read_text(encoding="utf-8")
        self.assertIn("benchmark_base.lib.rosbag_trajectory", text)
        self.assertIn("read_pose_observations", text)
        self.assertNotIn("def open_reader(", text)
        self.assertNotIn("def find_bag_for_topic(", text)
        self.assertNotIn("def read_observations(", text)


if __name__ == "__main__":
    unittest.main()
