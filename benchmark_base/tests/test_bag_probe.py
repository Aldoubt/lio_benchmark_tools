from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.bag_probe import (
    build_bag_identity,
    classify_candidate_roles,
    classify_sensor_layout,
    normalize_topic_evidence,
    validate_probe_payload,
)


class BagProbeContractTest(unittest.TestCase):
    def _make_bag(self, root: Path, name: str = "bag") -> Path:
        bag = root / name
        bag.mkdir()
        (bag / "metadata.yaml").write_text("rosbag2_bagfile_information:\n", encoding="utf-8")
        (bag / "segment_1.db3").write_bytes(b"first-segment")
        (bag / "segment_0.db3").write_bytes(b"zero-segment")
        (bag / "segment_2.mcap").write_bytes(b"mcap-segment")
        (bag / "unrelated.txt").write_text("ignored", encoding="utf-8")
        return bag

    @staticmethod
    def _raw_topics() -> dict:
        return {
            "/some/lidar": {
                "type": "livox_ros_driver2/msg/CustomMsg",
                "count": 100,
                "recorded_first_s": 10.0,
                "recorded_last_s": 19.9,
                "recorded_dt_s": {"median": 0.1},
                "recorded_time_reversals": 0,
                "header_first_s": 10.0,
                "header_last_s": 19.9,
                "header_dt_s": {"median": 0.1},
                "header_time_reversals": 0,
                "frame_ids": ["livox_frame"],
                "point_fields": [
                    {"name": "timebase", "datatype": "uint64 absolute ns"},
                    {"name": "offset_time", "datatype": "uint32 relative ns"},
                    {"name": "x", "datatype": "float32 m"},
                ],
            },
            "/some/imu": {
                "type": "sensor_msgs/msg/Imu",
                "count": 1000,
                "recorded_first_s": 10.0,
                "recorded_last_s": 19.99,
                "recorded_dt_s": {"median": 0.01},
                "recorded_time_reversals": 0,
                "header_first_s": 10.0,
                "header_last_s": 19.99,
                "header_dt_s": {"median": 0.01},
                "header_time_reversals": 0,
                "frame_ids": ["livox_frame"],
                "point_fields": None,
            },
        }

    def test_bag_identity_is_content_based_ordered_and_path_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bag = self._make_bag(root, "original")
            moved = root / "moved"
            shutil.copytree(bag, moved)

            original = build_bag_identity(bag)
            copied = build_bag_identity(moved)

            self.assertEqual(original["bag_content_sha256"], copied["bag_content_sha256"])
            self.assertEqual(
                ["segment_0.db3", "segment_1.db3", "segment_2.mcap"],
                [row["relative_path"] for row in original["storage_files"]],
            )
            self.assertEqual("metadata.yaml", original["metadata_yaml"]["relative_path"])
            self.assertNotIn("unrelated.txt", str(original))

    def test_modified_storage_file_changes_bag_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bag = self._make_bag(root)
            before = build_bag_identity(bag)["bag_content_sha256"]
            (bag / "segment_1.db3").write_bytes(b"changed")
            after = build_bag_identity(bag)["bag_content_sha256"]
            self.assertNotEqual(before, after)

    def test_single_lidar_and_imu_candidates_are_unambiguous_without_name_heuristics(self) -> None:
        topics = normalize_topic_evidence(self._raw_topics())
        roles = classify_candidate_roles(topics)
        self.assertEqual("UNAMBIGUOUS", roles["lidar"]["status"])
        self.assertEqual("/some/lidar", roles["lidar"]["recommended"])
        self.assertEqual("UNAMBIGUOUS", roles["imu"]["status"])
        self.assertEqual("/some/imu", roles["imu"]["recommended"])
        self.assertAlmostEqual(10.0, topics[0]["recorded_rate_hz"])

    def test_multiple_lidar_candidates_remain_ambiguous(self) -> None:
        raw = self._raw_topics()
        raw["/preferred-looking-name/livox"] = dict(raw["/some/lidar"])
        topics = normalize_topic_evidence(raw)
        roles = classify_candidate_roles(topics)
        self.assertEqual("AMBIGUOUS", roles["lidar"]["status"])
        self.assertIsNone(roles["lidar"]["recommended"])
        self.assertEqual(
            ["/preferred-looking-name/livox", "/some/lidar"],
            roles["lidar"]["candidates"],
        )

    def test_livox_layout_is_not_promoted_to_verified_sensor_model(self) -> None:
        layouts = classify_sensor_layout(normalize_topic_evidence(self._raw_topics()))
        self.assertEqual(1, len(layouts))
        self.assertEqual("/some/lidar", layouts[0]["topic"])
        self.assertEqual("LIVOX_CUSTOM_LAYOUT", layouts[0]["layout"])
        self.assertNotIn("MID360_VERIFIED", str(layouts))

    def test_probe_payload_validation_requires_v1_evidence_shape(self) -> None:
        payload = {
            "schema": "lio_benchmark_dataset_probe/v1",
            "created_at": "2026-08-17T00:00:00+00:00",
            "source": {"bag_dir": "/tmp/bag", "mode": "READ_ONLY_EVIDENCE"},
            "bag_identity": {
                "bag_dir": "/tmp/bag",
                "storage_files": [
                    {"relative_path": "data.db3", "size_bytes": 1, "sha256": "a" * 64}
                ],
                "metadata_yaml": None,
                "bag_content_sha256": "b" * 64,
            },
            "topics": [],
            "candidate_roles": {
                "lidar": {"candidates": [], "recommended": None, "status": "MISSING"},
                "imu": {"candidates": [], "recommended": None, "status": "MISSING"},
            },
            "timestamp_evidence": {},
            "imu_evidence": {},
            "sensor_layout_candidates": [],
            "limitations": [],
        }
        validate_probe_payload(payload)
        payload["schema"] = "wrong"
        with self.assertRaisesRegex(ValueError, "probe schema"):
            validate_probe_payload(payload)


if __name__ == "__main__":
    unittest.main()
