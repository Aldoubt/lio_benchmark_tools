from __future__ import annotations

import unittest
from pathlib import Path

from benchmark_base.lib.runtime_provenance import (
    ProvenanceStatus,
    build_runtime_provenance_record,
    classify_runtime_provenance,
    normalize_github_repository,
    workspace_from_package_prefix,
)


class RuntimeProvenanceTest(unittest.TestCase):
    def test_normalize_common_github_remote_forms(self) -> None:
        self.assertEqual("Franklif1/Fast_LIO2_ROS2", normalize_github_repository("https://github.com/Franklif1/Fast_LIO2_ROS2.git"))
        self.assertEqual("Franklif1/Fast_LIO2_ROS2", normalize_github_repository("git@github.com:Franklif1/Fast_LIO2_ROS2.git"))

    def test_matching_source_and_frames_pass(self) -> None:
        result = classify_runtime_provenance(
            expected_repository="PRBonn/kiss-icp",
            actual_repository="https://github.com/PRBonn/kiss-icp.git",
            frame_status="MATCH",
            ros_package_prefix="/workspace/install/kiss_icp",
        )
        self.assertEqual(ProvenanceStatus.MATCH, result.status)
        self.assertEqual((), result.reasons)

    def test_source_repository_mismatch_is_blocking(self) -> None:
        result = classify_runtime_provenance(
            expected_repository="Franklif1/Fast_LIO2_ROS2",
            actual_repository="https://github.com/example/another_fast_lio.git",
            frame_status="MATCH",
            ros_package_prefix="/workspace/install/fast_lio",
        )
        self.assertEqual(ProvenanceStatus.SOURCE_MISMATCH, result.status)

    def test_frame_label_mismatch_is_preserved_even_when_repo_matches(self) -> None:
        result = classify_runtime_provenance(
            expected_repository="Franklif1/Fast_LIO2_ROS2",
            actual_repository="https://github.com/Franklif1/Fast_LIO2_ROS2.git",
            frame_status="FRAME_LABEL_MISMATCH",
            ros_package_prefix="/workspace/install/fast_lio",
        )
        self.assertEqual(ProvenanceStatus.FRAME_CONTRACT_MISMATCH, result.status)

    def test_missing_runtime_source_is_unresolved_not_pass(self) -> None:
        result = classify_runtime_provenance(
            expected_repository="hku-mars/FAST-LIVO2",
            actual_repository=None,
            frame_status="MATCH",
            ros_package_prefix=None,
        )
        self.assertEqual(ProvenanceStatus.UNRESOLVED, result.status)

    def test_missing_declared_execution_repository_is_unresolved(self) -> None:
        result = classify_runtime_provenance(
            expected_repository=None,
            actual_repository="https://github.com/local/fast-livo2-ros2.git",
            frame_status="MATCH",
            ros_package_prefix="/workspace/install/fast_livo",
        )
        self.assertEqual(ProvenanceStatus.UNRESOLVED, result.status)
        self.assertIn("declared execution repository", result.reasons[0])

    def test_package_prefix_recovers_colcon_workspace(self) -> None:
        self.assertEqual(
            Path("/home/user/fastlio_ws"),
            workspace_from_package_prefix("/home/user/fastlio_ws/install/fast_lio"),
        )
        self.assertEqual(
            Path("/home/user/merged_ws"),
            workspace_from_package_prefix("/home/user/merged_ws/install"),
        )
        self.assertIsNone(workspace_from_package_prefix("/opt/ros/humble"))

    def test_record_uses_execution_implementation_not_algorithm_paper_source(self) -> None:
        algorithm = {
            "algorithm_id": "fast_lio2",
            "source": {"repository": "hku-mars/FAST_LIO"},
            "execution_implementation": {
                "repository": "Franklif1/Fast_LIO2_ROS2",
                "package": "fast_lio",
                "executable": "fastlio_mapping",
            },
            "trajectory_contract": {
                "pose_semantics": "T_PARENT_TRACKED",
                "tracked_frame_physical": "IMU_BODY",
                "world_gauge": "INITIAL_BODY_ALIGNED",
                "expected_parent_frames": ["camera_init"],
                "expected_child_frames": ["body"],
            },
        }
        frame_audit = {
            "status": "AVAILABLE",
            "parent_frame_ids": ["odom"],
            "child_frame_ids": ["sensor"],
        }
        source_state = {
            "remote_origin": "https://github.com/Franklif1/Fast_LIO2_ROS2.git",
            "commit": "abc123",
            "branch": "ros2",
            "dirty": False,
            "path": "/workspace/src/Fast_LIO2_ROS2",
        }
        record = build_runtime_provenance_record(
            algorithm=algorithm,
            frame_audit=frame_audit,
            ros_package_prefix="/workspace/install/fast_lio",
            source_state=source_state,
        )
        self.assertEqual("Franklif1/Fast_LIO2_ROS2", record["expected_execution_repository"])
        self.assertEqual("Franklif1/Fast_LIO2_ROS2", record["actual_execution_repository"])
        self.assertEqual("FRAME_LABEL_MISMATCH", record["frame_contract_status"])
        self.assertEqual("FRAME_CONTRACT_MISMATCH", record["status"])
        self.assertEqual("abc123", record["source_commit"])


if __name__ == "__main__":
    unittest.main()
