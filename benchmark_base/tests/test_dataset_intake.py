from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.bag_probe import build_bag_identity, sha256_file
from benchmark_base.lib.dataset_intake import freeze_dataset
from benchmark_base.lib.registry import validate_dataset_record


class DatasetIntakeContractTest(unittest.TestCase):
    def _make_probe(
        self,
        root: Path,
        *,
        lidar_type: str = "livox_ros_driver2/msg/CustomMsg",
        imu_type: str = "sensor_msgs/msg/Imu",
        lidar_recorded_reversals: int = 0,
        lidar_header_reversals: int = 0,
    ) -> tuple[Path, Path]:
        bag = root / "bag"
        bag.mkdir()
        (bag / "metadata.yaml").write_text("rosbag2_bagfile_information:\n", encoding="utf-8")
        (bag / "bag_0.db3").write_bytes(b"frozen-bag-bytes")
        identity = build_bag_identity(bag)
        payload = {
            "schema": "lio_benchmark_dataset_probe/v1",
            "created_at": "2026-08-17T00:00:00+00:00",
            "source": {"bag_dir": str(bag.resolve()), "mode": "READ_ONLY_EVIDENCE"},
            "bag_identity": identity,
            "topics": [
                {
                    "name": "/lidar",
                    "type": lidar_type,
                    "message_count": 100,
                    "recorded_first_s": 1.0,
                    "recorded_last_s": 10.9,
                    "recorded_dt_median_s": 0.1,
                    "recorded_rate_hz": 10.0,
                    "recorded_time_reversal_count": lidar_recorded_reversals,
                    "header_first_s": 1.0,
                    "header_last_s": 10.9,
                    "header_dt_median_s": 0.1,
                    "header_rate_hz": 10.0,
                    "header_time_reversal_count": lidar_header_reversals,
                    "frame_ids": ["livox_frame"],
                    "point_fields": [
                        {"name": "timebase", "datatype": "uint64 absolute ns"},
                        {"name": "offset_time", "datatype": "uint32 relative ns"},
                    ],
                },
                {
                    "name": "/imu",
                    "type": imu_type,
                    "message_count": 1000,
                    "recorded_first_s": 1.0,
                    "recorded_last_s": 10.99,
                    "recorded_dt_median_s": 0.01,
                    "recorded_rate_hz": 100.0,
                    "recorded_time_reversal_count": 0,
                    "header_first_s": 1.0,
                    "header_last_s": 10.99,
                    "header_dt_median_s": 0.01,
                    "header_rate_hz": 100.0,
                    "header_time_reversal_count": 0,
                    "frame_ids": ["livox_frame"],
                    "point_fields": None,
                },
            ],
            "candidate_roles": {
                "lidar": {"candidates": ["/lidar"], "recommended": "/lidar", "status": "UNAMBIGUOUS"},
                "imu": {"candidates": ["/imu"], "recommended": "/imu", "status": "UNAMBIGUOUS"},
            },
            "timestamp_evidence": {},
            "imu_evidence": {},
            "sensor_layout_candidates": [
                {"topic": "/lidar", "layout": "LIVOX_CUSTOM_LAYOUT"}
            ],
            "limitations": [],
        }
        probe = root / "inspection-source.json"
        probe.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return bag, probe

    def _freeze_internal(self, root: Path, probe: Path, **overrides) -> Path:
        kwargs = dict(
            probe_path=probe,
            dataset_id="unit_mid360",
            lidar_topic="/lidar",
            imu_topic="/imu",
            profile="mid360-internal",
            imu_angular_velocity_unit="rad_s",
            imu_linear_acceleration_unit="g_like_raw",
            output_dir=root / "frozen",
        )
        kwargs.update(overrides)
        return freeze_dataset(**kwargs)

    def test_internal_profile_writes_registry_valid_immutable_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bag, probe = self._make_probe(root)
            source_bytes = probe.read_bytes()
            probe_sha = sha256_file(probe)
            bag_sha = build_bag_identity(bag)["bag_content_sha256"]

            output = self._freeze_internal(root, probe)

            self.assertEqual(root / "frozen", output)
            self.assertEqual(source_bytes, (output / "inspection.json").read_bytes())
            dataset = json.loads((output / "dataset.json").read_text(encoding="utf-8"))
            validate_dataset_record(dataset)
            self.assertEqual("unit_mid360", dataset["dataset_id"])
            self.assertEqual(str(bag.resolve()), dataset["bag_dir"])
            self.assertEqual(bag_sha, dataset["sha256"])
            self.assertEqual("UNSPECIFIED", dataset["environment"])
            self.assertEqual("/lidar", dataset["topics"]["lidar"])
            self.assertEqual("/imu", dataset["topics"]["imu"])
            self.assertEqual("livox_ros_driver2/msg/CustomMsg", dataset["types"]["lidar"])
            self.assertEqual("sensor_msgs/msg/Imu", dataset["types"]["imu"])
            self.assertEqual("offset_time", dataset["timestamp"]["point_time_field"])
            self.assertEqual("ns_relative_to_timebase", dataset["timestamp"]["point_time_unit"])
            self.assertEqual("header.stamp", dataset["timestamp"]["scan_time_field"])
            self.assertEqual("timebase", dataset["timestamp"]["timebase_field"])
            self.assertTrue(dataset["timestamp"]["verified_from_bag"])
            self.assertEqual("rad_s", dataset["imu"]["angular_velocity_unit"])
            self.assertEqual("g_like_raw", dataset["imu"]["linear_acceleration_unit"])
            self.assertEqual("EXPLICIT_USER_SELECTION", dataset["imu"]["unit_source"])

            calibration = dataset["calibration"]
            self.assertEqual("LIDAR_TO_IMU", calibration["canonical_convention"])
            self.assertEqual("p_I = R_IL * p_L + t_IL", calibration["canonical_equation"])
            self.assertEqual([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0], calibration["rotation_lidar_to_imu_row_major"])
            self.assertEqual([-0.011, -0.02329, 0.04412], calibration["translation_lidar_to_imu_m"])
            self.assertEqual([0.011, 0.02329, -0.04412], calibration["manufacturer_imu_origin_in_lidar_m"])
            self.assertEqual("MANUFACTURER_SPEC", calibration["status"])
            self.assertEqual("MANUFACTURER_SPEC", calibration["source_type"])
            self.assertEqual("Livox Mid-360", calibration["sensor_model"])
            self.assertEqual("EXPLICIT_PROFILE_SELECTION", calibration["sensor_model_source"])
            self.assertEqual("INTERNAL_IMU", calibration["imu_relation"])

            intake = dataset["intake"]
            self.assertEqual("lio_benchmark_dataset_intake/v1", intake["schema"])
            self.assertEqual("mid360-internal", intake["profile"])
            self.assertEqual(probe_sha, intake["inspection_sha256"])
            self.assertEqual(bag_sha, intake["bag_content_sha256"])
            self.assertEqual("EXPLICIT_USER_SELECTION", intake["selected_topics_source"])
            self.assertEqual({"inspection.json", "dataset.json"}, {p.name for p in output.iterdir()})

    def test_user_extrinsic_is_user_provided_and_rotation_is_plausible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, probe = self._make_probe(root)
            output = freeze_dataset(
                probe_path=probe,
                dataset_id="user_ext",
                lidar_topic="/lidar",
                imu_topic="/imu",
                profile="mid360-user-extrinsic",
                imu_angular_velocity_unit="rad_s",
                imu_linear_acceleration_unit="m_s2",
                output_dir=root / "frozen",
                rotation_lidar_to_imu=[1, 0, 0, 0, 1, 0, 0, 0, 1],
                translation_lidar_to_imu=[0.1, -0.2, 0.3],
                calibration_source="field-calib-2026-08-17",
            )
            dataset = json.loads((output / "dataset.json").read_text(encoding="utf-8"))
            calibration = dataset["calibration"]
            self.assertEqual("USER_PROVIDED", calibration["status"])
            self.assertEqual("USER_PROVIDED", calibration["source_type"])
            self.assertEqual([0.1, -0.2, 0.3], calibration["translation_lidar_to_imu_m"])
            self.assertEqual("field-calib-2026-08-17", calibration["source"])
            self.assertEqual("Livox Mid-360", calibration["sensor_model"])
            self.assertEqual("EXPLICIT_PROFILE_SELECTION", calibration["sensor_model_source"])

            with self.assertRaisesRegex(ValueError, "rotation"):
                freeze_dataset(
                    probe_path=probe,
                    dataset_id="bad_rotation",
                    lidar_topic="/lidar",
                    imu_topic="/imu",
                    profile="mid360-user-extrinsic",
                    imu_angular_velocity_unit="rad_s",
                    imu_linear_acceleration_unit="m_s2",
                    output_dir=root / "bad",
                    rotation_lidar_to_imu=[2, 0, 0, 0, 1, 0, 0, 0, 1],
                    translation_lidar_to_imu=[0, 0, 0],
                    calibration_source="bad",
                )

    def test_unknown_profile_is_explicitly_blocking_not_fake_identity_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, probe = self._make_probe(root)
            output = freeze_dataset(
                probe_path=probe,
                dataset_id="unknown_calib",
                lidar_topic="/lidar",
                imu_topic="/imu",
                profile="unknown-lidar-imu",
                imu_angular_velocity_unit="unknown",
                imu_linear_acceleration_unit="unknown",
                output_dir=root / "frozen",
            )
            dataset = json.loads((output / "dataset.json").read_text(encoding="utf-8"))
            calibration = dataset["calibration"]
            self.assertEqual("UNKNOWN", calibration["status"])
            self.assertEqual("UNKNOWN", calibration["sensor_model"])
            self.assertTrue(calibration["placeholder_transform"])
            self.assertFalse(calibration["usable_for_lidar_imu_benchmark"])
            self.assertEqual([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0], calibration["rotation_lidar_to_imu_row_major"])
            self.assertEqual([0.0, 0.0, 0.0], calibration["translation_lidar_to_imu_m"])

    def test_changed_bag_after_probe_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bag, probe = self._make_probe(root)
            (bag / "bag_0.db3").write_bytes(b"mutated-after-probe")
            with self.assertRaisesRegex(ValueError, "bag identity"):
                self._freeze_internal(root, probe)
            self.assertFalse((root / "frozen").exists())

    def test_topic_type_timestamp_and_pointcloud2_gates_fail_closed(self) -> None:
        cases = (
            ({"lidar_topic": "/missing"}, "selected LiDAR topic"),
            ({"imu_topic": "/lidar"}, "different"),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    _, probe = self._make_probe(root)
                    with self.assertRaisesRegex(ValueError, message):
                        self._freeze_internal(root, probe, **overrides)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, probe = self._make_probe(root, lidar_type="sensor_msgs/msg/PointCloud2")
            with self.assertRaisesRegex(ValueError, "PointCloud2"):
                self._freeze_internal(root, probe)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, probe = self._make_probe(root, imu_type="std_msgs/msg/String")
            with self.assertRaisesRegex(ValueError, "IMU type"):
                self._freeze_internal(root, probe)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, probe = self._make_probe(root, lidar_recorded_reversals=1)
            with self.assertRaisesRegex(ValueError, "recorded time"):
                self._freeze_internal(root, probe)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, probe = self._make_probe(root, lidar_header_reversals=1)
            with self.assertRaisesRegex(ValueError, "header time"):
                self._freeze_internal(root, probe)

    def test_invalid_id_units_and_existing_output_are_rejected_without_staging_residue(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, probe = self._make_probe(root)
            with self.assertRaisesRegex(ValueError, "dataset id"):
                self._freeze_internal(root, probe, dataset_id="bad/id")
            with self.assertRaisesRegex(ValueError, "angular velocity unit"):
                self._freeze_internal(root, probe, imu_angular_velocity_unit="deg_s")
            with self.assertRaisesRegex(ValueError, "linear acceleration unit"):
                self._freeze_internal(root, probe, imu_linear_acceleration_unit="auto")
            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(FileExistsError, "output"):
                self._freeze_internal(root, probe, output_dir=existing)
            self.assertFalse(any(".staging-" in p.name for p in root.iterdir()))


if __name__ == "__main__":
    unittest.main()
