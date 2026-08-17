from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.frame_audit import RawPoseObservation
from benchmark_base.lib.trajectory import TrajectoryError
from benchmark_base.lib.trajectory_from_run import (
    TIMESTAMP_DUPLICATE_POLICY,
    TIMESTAMP_REGRESSION_POLICY,
    build_trajectory_standardization_metadata,
    canonicalize_pose_observations,
    ensure_standardized_trajectory_absent,
    trajectory_from_observations,
    trajectory_output_paths,
    trajectory_topic_from_algorithm,
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

    def test_strict_trajectory_contract_itself_still_rejects_duplicates(self) -> None:
        with self.assertRaisesRegex(TrajectoryError, "strictly increasing"):
            trajectory_from_observations(
                (
                    self._observation(timestamp_s=2.0),
                    self._observation(timestamp_s=2.0),
                ),
                source_topic="/Odometry",
            )

    def test_canonicalization_coalesces_exact_duplicate_timestamp_and_keeps_last_state(self) -> None:
        observations = (
            self._observation(timestamp_s=1.0, x=1.0),
            self._observation(timestamp_s=2.0, x=2.0),
            self._observation(timestamp_s=2.0, x=20.0),
            self._observation(timestamp_s=3.0, x=3.0),
        )
        canonical, summary = canonicalize_pose_observations(observations)

        self.assertEqual((1.0, 2.0, 3.0), tuple(row.timestamp_s for row in canonical))
        self.assertEqual(20.0, canonical[1].x_m)
        self.assertEqual(TIMESTAMP_DUPLICATE_POLICY, summary.policy)
        self.assertEqual(4, summary.raw_sample_count)
        self.assertEqual(3, summary.canonical_sample_count)
        self.assertEqual(1, summary.duplicate_group_count)
        self.assertEqual(1, summary.coalesced_sample_count)

    def test_canonicalization_counts_one_group_with_multiple_same_time_revisions(self) -> None:
        canonical, summary = canonicalize_pose_observations(
            (
                self._observation(timestamp_s=1.0),
                self._observation(timestamp_s=2.0, x=2.0),
                self._observation(timestamp_s=2.0, x=3.0),
                self._observation(timestamp_s=2.0, x=4.0),
                self._observation(timestamp_s=3.0),
            )
        )
        self.assertEqual(3, len(canonical))
        self.assertEqual(4.0, canonical[1].x_m)
        self.assertEqual(1, summary.duplicate_group_count)
        self.assertEqual(2, summary.coalesced_sample_count)

    def test_canonicalization_never_sorts_or_repairs_timestamp_regression(self) -> None:
        with self.assertRaisesRegex(TrajectoryError, "timestamp regression"):
            canonicalize_pose_observations(
                (
                    self._observation(timestamp_s=1.0),
                    self._observation(timestamp_s=3.0),
                    self._observation(timestamp_s=2.0),
                )
            )

    def test_metadata_records_run_local_rosbag_source_and_timestamp_canonicalization(self) -> None:
        _, summary = canonicalize_pose_observations(
            (
                self._observation(timestamp_s=1.0),
                self._observation(timestamp_s=2.0, x=2.0),
                self._observation(timestamp_s=2.0, x=3.0),
                self._observation(timestamp_s=3.0),
            )
        )
        metadata = build_trajectory_standardization_metadata(
            algorithm_id="fast_livo2",
            source_bag="/runs/smoke/raw/fast_livo2/fast_livo_trajectory",
            source_topic="/aft_mapped_to_init",
            source_message_type="nav_msgs/msg/Odometry",
            sample_count=3,
            start_timestamp_s=1.0,
            end_timestamp_s=3.0,
            output="standardized/trajectories/fast_livo2.csv",
            timestamp_canonicalization=summary,
        )
        self.assertEqual(1, metadata["schema_version"])
        self.assertEqual("fast_livo2", metadata["algorithm_id"])
        self.assertEqual("RUN_LOCAL_ROS2_BAG", metadata["source_kind"])
        self.assertEqual("HEADER_STAMP_ELSE_BAG_RECORD_TIME", metadata["timestamp_policy"])
        self.assertEqual(TIMESTAMP_DUPLICATE_POLICY, metadata["timestamp_duplicate_policy"])
        self.assertEqual(TIMESTAMP_REGRESSION_POLICY, metadata["timestamp_regression_policy"])
        self.assertEqual(4, metadata["raw_sample_count"])
        self.assertEqual(3, metadata["sample_count"])
        self.assertEqual(1, metadata["duplicate_timestamp_group_count"])
        self.assertEqual(1, metadata["coalesced_duplicate_sample_count"])
        self.assertEqual("standardized/trajectories/fast_livo2.csv", metadata["output"])

    def test_metadata_without_duplicates_still_records_zero_canonicalization_counts(self) -> None:
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
        self.assertEqual(139, metadata["raw_sample_count"])
        self.assertEqual(139, metadata["sample_count"])
        self.assertEqual(0, metadata["duplicate_timestamp_group_count"])
        self.assertEqual(0, metadata["coalesced_duplicate_sample_count"])

    def test_frame_audit_consumes_shared_rosbag_reader_instead_of_defining_its_own(self) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / "evaluators/audit_trajectory_frames.py").read_text(encoding="utf-8")
        self.assertIn("benchmark_base.lib.rosbag_trajectory", text)
        self.assertIn("read_pose_observations", text)
        self.assertNotIn("def open_reader(", text)
        self.assertNotIn("def find_bag_for_topic(", text)
        self.assertNotIn("def read_observations(", text)

    def test_frozen_algorithm_topic_resolution_fails_closed_when_missing(self) -> None:
        algorithm = {"topics": {"outputs": {"trajectory": "/Odometry"}}}
        self.assertEqual("/Odometry", trajectory_topic_from_algorithm(algorithm))
        with self.assertRaisesRegex(ValueError, "trajectory output topic"):
            trajectory_topic_from_algorithm({"topics": {"outputs": {}}})

    def test_output_paths_are_fixed_under_run_contract(self) -> None:
        run = Path("/runs/greenhouse_smoke")
        trajectory_path, metadata_path = trajectory_output_paths(run, "fast_lio2")
        self.assertEqual(run / "standardized/trajectories/fast_lio2.csv", trajectory_path)
        self.assertEqual(
            run / "metadata/algorithms/fast_lio2/trajectory_standardization.json",
            metadata_path,
        )

    def test_existing_standardized_trajectory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fast_lio2.csv"
            ensure_standardized_trajectory_absent(path)
            path.write_text("existing\n", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                ensure_standardized_trajectory_absent(path)

    def test_run_standardizer_evaluator_uses_shared_reader_canonicalizer_and_pure_converter(self) -> None:
        root = Path(__file__).resolve().parents[2]
        evaluator = root / "evaluators/standardize_trajectory_from_run.py"
        self.assertTrue(evaluator.is_file())
        text = evaluator.read_text(encoding="utf-8")
        self.assertIn("find_bag_for_topic", text)
        self.assertIn("read_pose_observations", text)
        self.assertIn("canonicalize_pose_observations", text)
        self.assertIn("trajectory_from_observations", text)
        self.assertNotIn("--overwrite", text)
        self.assertNotIn("sorted(observations", text)


if __name__ == "__main__":
    unittest.main()
