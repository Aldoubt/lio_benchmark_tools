from __future__ import annotations

import unittest

from benchmark_base.lib.runtime_provenance import (
    ProvenanceStatus,
    classify_runtime_provenance,
    normalize_github_repository,
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


if __name__ == "__main__":
    unittest.main()
