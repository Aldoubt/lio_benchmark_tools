from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RosbagInspectionContractTest(unittest.TestCase):
    def test_analyze_and_probe_share_one_rosbag_reader(self) -> None:
        shared = ROOT / "benchmark_base/lib/rosbag_inspection.py"
        analyze = ROOT / "evaluators/analyze_bag.py"
        probe = ROOT / "evaluators/probe_dataset.py"

        self.assertTrue(shared.is_file())
        self.assertTrue(probe.is_file())

        shared_text = shared.read_text(encoding="utf-8")
        analyze_text = analyze.read_text(encoding="utf-8")
        probe_text = probe.read_text(encoding="utf-8")

        self.assertIn("def inspect_ros2_bag", shared_text)
        self.assertIn("rosbag2_py.SequentialReader", shared_text)
        self.assertIn("inspect_ros2_bag", analyze_text)
        self.assertIn("inspect_ros2_bag", probe_text)
        self.assertNotIn("rosbag2_py.SequentialReader", analyze_text)
        self.assertNotIn("rosbag2_py.SequentialReader", probe_text)

    def test_custom_messages_keep_full_header_audit_even_when_layout_sampling_is_bounded(self) -> None:
        shared = ROOT / "benchmark_base/lib/rosbag_inspection.py"
        text = shared.read_text(encoding="utf-8")
        self.assertNotIn(
            "if is_custom and custom_samples.get(topic, 0) >= 3:\n            continue",
            text,
        )
        self.assertIn("sample_custom_layout", text)
        self.assertIn("header_times[topic].append", text)

    def test_probe_builds_v1_evidence_from_pure_contract_helpers(self) -> None:
        probe = ROOT / "evaluators/probe_dataset.py"
        self.assertTrue(probe.is_file())
        text = probe.read_text(encoding="utf-8")
        for symbol in (
            "build_bag_identity",
            "normalize_topic_evidence",
            "classify_candidate_roles",
            "classify_sensor_layout",
            "validate_probe_payload",
        ):
            self.assertIn(symbol, text)
        self.assertIn("lio_benchmark_dataset_probe/v1", text)
        self.assertIn("READ_ONLY_EVIDENCE", text)

    def test_probe_cli_surface_is_only_bag_and_optional_output(self) -> None:
        probe = ROOT / "evaluators/probe_dataset.py"
        self.assertTrue(probe.is_file())
        text = probe.read_text(encoding="utf-8")
        self.assertIn('add_argument("--bag"', text)
        self.assertIn('add_argument("--output"', text)
        for forbidden in (
            "--lidar-topic",
            "--imu-topic",
            "--profile",
            "--extrinsic",
            "--overwrite",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
