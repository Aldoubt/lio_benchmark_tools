from __future__ import annotations

import unittest

from benchmark_base.lib.trajectory_semantics import (
    FrameAuditStatus,
    audit_semantic_labels,
    classify_frame_audit,
)


class TrajectorySemanticsContractTest(unittest.TestCase):
    def test_gravity_aligned_fast_livo2_contract_matches_runtime_frames(self) -> None:
        contract = {
            "pose_semantics": "T_PARENT_TRACKED",
            "tracked_frame_physical": "IMU_BODY",
            "world_gauge": "GRAVITY_ALIGNED",
            "expected_parent_frames": ["camera_init"],
            "expected_child_frames": ["aft_mapped"],
        }
        audit = {
            "status": "AVAILABLE",
            "parent_frame_ids": ["camera_init"],
            "child_frame_ids": ["aft_mapped"],
        }
        result = classify_frame_audit(contract, audit)
        self.assertEqual(FrameAuditStatus.MATCH, result.status)

    def test_runtime_frame_label_mismatch_is_not_silently_accepted(self) -> None:
        contract = {
            "pose_semantics": "T_PARENT_TRACKED",
            "tracked_frame_physical": "IMU_BODY",
            "world_gauge": "INITIAL_BODY_ALIGNED",
            "expected_parent_frames": ["camera_init"],
            "expected_child_frames": ["body"],
        }
        audit = {
            "status": "AVAILABLE",
            "parent_frame_ids": ["odom"],
            "child_frame_ids": ["sensor"],
        }
        result = classify_frame_audit(contract, audit)
        self.assertEqual(FrameAuditStatus.FRAME_LABEL_MISMATCH, result.status)
        self.assertIn("parent", result.reasons[0])

    def test_dynamic_child_frame_policy_allows_kiss_input_lidar_frame(self) -> None:
        contract = {
            "pose_semantics": "T_PARENT_TRACKED",
            "tracked_frame_physical": "LIDAR",
            "world_gauge": "INITIAL_LIDAR_ALIGNED",
            "expected_parent_frames": ["odom_lidar"],
            "child_frame_policy": "INPUT_LIDAR_FRAME",
        }
        audit = {
            "status": "AVAILABLE",
            "parent_frame_ids": ["odom_lidar"],
            "child_frame_ids": ["livox_frame"],
        }
        result = classify_frame_audit(contract, audit)
        self.assertEqual(FrameAuditStatus.MATCH, result.status)

    def test_audit_labels_use_physical_tracked_frame_and_world_gauge(self) -> None:
        self.assertEqual(
            ("IMU_BODY", "GRAVITY_ALIGNED"),
            audit_semantic_labels(
                {
                    "tracked_frame_physical": "IMU_BODY",
                    "world_gauge": "GRAVITY_ALIGNED",
                }
            ),
        )

    def test_unavailable_audit_remains_unavailable(self) -> None:
        result = classify_frame_audit(
            {
                "pose_semantics": "T_PARENT_TRACKED",
                "tracked_frame_physical": "UNKNOWN",
                "world_gauge": "UNKNOWN",
            },
            {"status": "MISSING"},
        )
        self.assertEqual(FrameAuditStatus.AUDIT_UNAVAILABLE, result.status)


if __name__ == "__main__":
    unittest.main()
