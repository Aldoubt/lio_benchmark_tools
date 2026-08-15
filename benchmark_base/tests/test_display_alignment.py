from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from benchmark_base.lib.display_alignment import (
    apply_display_transform_pose,
    apply_display_transform_xyz,
    compute_display_alignment,
    normalize_display_alignment_mode,
    write_display_alignment_metadata,
)
from benchmark_base.lib.trajectory import PoseSample, quaternion_from_rpy, rpy_from_quaternion


class DisplayAlignmentContractTest(unittest.TestCase):
    def test_none_is_identity(self) -> None:
        pose = self._pose(3.0, 4.0, 5.0, 0.1, -0.2, 0.7)
        matrix = compute_display_alignment(pose, "NONE")
        np.testing.assert_allclose(matrix, np.eye(4), atol=1e-12)

    def test_legacy_aliases_normalize_to_canonical_names(self) -> None:
        self.assertEqual("NONE", normalize_display_alignment_mode("raw"))
        self.assertEqual("START_XY_YAW", normalize_display_alignment_mode("start_yaw"))

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

    def test_metadata_generation_does_not_rewrite_standardized_trajectory(self) -> None:
        qx, qy, qz, qw = quaternion_from_rpy(0.1, -0.2, 0.7)
        header = "timestamp_s,x_m,y_m,z_m,qx,qy,qz,qw,roll_rad,pitch_rad,yaw_rad,source_topic\n"
        rows = [
            f"0,3,4,5,{qx},{qy},{qz},{qw},0.1,-0.2,0.7,/odom\n",
            f"1,4,5,6,{qx},{qy},{qz},{qw},0.1,-0.2,0.7,/odom\n",
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trajectory = root / "standardized/trajectories/test.csv"
            trajectory.parent.mkdir(parents=True)
            trajectory.write_text(header + "".join(rows), encoding="utf-8")
            before = hashlib.sha256(trajectory.read_bytes()).hexdigest()
            output = write_display_alignment_metadata(
                run=root,
                algorithm_id="test",
                trajectory_role="ODOMETRY",
                trajectory_path=trajectory,
                mode="START_XY_YAW",
            )
            after = hashlib.sha256(trajectory.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertTrue(output.is_file())
            self.assertIn('"scientific_artifacts_modified": false', output.read_text(encoding="utf-8"))

    def test_run_manifest_corrects_incompatible_hardcoded_odometry_role(self) -> None:
        qx, qy, qz, qw = quaternion_from_rpy(0.0, 0.0, 0.2)
        header = "timestamp_s,x_m,y_m,z_m,qx,qy,qz,qw,roll_rad,pitch_rad,yaw_rad,source_topic\n"
        rows = [
            f"0,1,2,3,{qx},{qy},{qz},{qw},0,0,0.2,/glim_ros/odom_corrected\n",
            f"1,2,3,3,{qx},{qy},{qz},{qw},0,0,0.2,/glim_ros/odom_corrected\n",
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trajectory = root / "standardized/trajectories/glim_full_slam.csv"
            trajectory.parent.mkdir(parents=True)
            trajectory.write_text(header + "".join(rows), encoding="utf-8")
            (root / "manifest.json").write_text(
                json.dumps({
                    "algorithms": {
                        "glim_full_slam": {"evaluation_roles": ["SYSTEM_MAPPING"]}
                    }
                }),
                encoding="utf-8",
            )
            output = write_display_alignment_metadata(
                run=root,
                algorithm_id="glim_full_slam",
                trajectory_role="ODOMETRY",
                trajectory_path=trajectory,
                mode="START_XY_YAW",
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("SYSTEM_MAPPING", payload["trajectory_role"])
            self.assertTrue(output.name.endswith("__system_mapping.json"))

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
