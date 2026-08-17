from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.manifest import resolve_manifest, sha256_file, validate_manifest
from benchmark_base.lib.registry import Registry


ROOT = Path(__file__).resolve().parents[2]


class ManifestDatasetFileContractTest(unittest.TestCase):
    @staticmethod
    def _dataset(root: Path, dataset_id: str = "external_mid360") -> Path:
        bag = root / "bag"
        bag.mkdir(exist_ok=True)
        (bag / "metadata.yaml").write_text("rosbag2_bagfile_information:\n", encoding="utf-8")
        dataset = {
            "schema_version": 2,
            "dataset_id": dataset_id,
            "bag_dir": str(bag.resolve()),
            "sha256": "a" * 64,
            "environment": "UNSPECIFIED",
            "acquisition": {
                "platform": "UNSPECIFIED",
                "route_type": "UNSPECIFIED",
                "camera_present": False,
            },
            "topics": {
                "lidar": "/lidar",
                "imu": "/imu",
                "camera": None,
            },
            "types": {
                "lidar": "livox_ros_driver2/msg/CustomMsg",
                "imu": "sensor_msgs/msg/Imu",
                "camera": None,
            },
            "timestamp": {
                "point_time_field": "offset_time",
                "point_time_unit": "ns_relative_to_timebase",
            },
            "calibration": {
                "canonical_convention": "LIDAR_TO_IMU",
                "rotation_lidar_to_imu_row_major": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                "translation_lidar_to_imu_m": [-0.011, -0.02329, 0.04412],
                "status": "MANUFACTURER_SPEC",
            },
        }
        path = root / "dataset.json"
        path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _manifest(dataset_file: str | None = None, dataset: str | None = None) -> dict:
        manifest = {
            "schema_version": 2,
            "name": "external_dataset_test",
            "workspace": "/tmp/workspace-does-not-need-to-exist",
            "output_root": "/tmp/lio-benchmark-output",
            "algorithms": ["fast_livo2", "fast_lio2", "kiss_icp"],
            "standardization": {
                "map_scan_step": 5,
                "map_point_step": 8,
                "map_voxel_m": 0.12,
                "near_range_m": 0.5,
                "trajectory_time_tolerance_s": 0.05,
            },
        }
        if dataset_file is not None:
            manifest["dataset_file"] = dataset_file
        if dataset is not None:
            manifest["dataset"] = dataset
        return manifest

    def test_absolute_external_dataset_is_validated_and_frozen_with_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset_path = self._dataset(root)
            manifest = self._manifest(dataset_file=str(dataset_path.resolve()))

            self.assertEqual(
                [],
                validate_manifest(manifest, check_paths=False, manifest_dir=root),
            )
            resolved = resolve_manifest(manifest, manifest_dir=root)
            self.assertEqual(str(dataset_path.resolve()), resolved["dataset_file_ref"])
            self.assertEqual(sha256_file(dataset_path), resolved["dataset_file_sha256"])
            self.assertEqual("external_mid360", resolved["dataset"]["dataset_id"])
            self.assertNotIn("dataset_ref", resolved)

    def test_relative_external_dataset_resolves_only_against_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            configs = root / "configs"
            datasets = root / "datasets"
            configs.mkdir(); datasets.mkdir()
            dataset_path = self._dataset(datasets)
            manifest = self._manifest(dataset_file="../datasets/dataset.json")

            resolved = resolve_manifest(manifest, manifest_dir=configs)
            self.assertEqual(str(dataset_path.resolve()), resolved["dataset_file_ref"])

            with self.assertRaisesRegex(ValueError, "manifest_dir"):
                resolve_manifest(manifest)
            errors = validate_manifest(manifest, check_paths=False)
            self.assertTrue(any("manifest_dir" in error for error in errors), errors)

    def test_registry_dataset_reference_remains_backward_compatible(self) -> None:
        manifest = self._manifest(dataset="green_house_mid360")
        resolved = resolve_manifest(manifest, Registry())
        self.assertEqual("green_house_mid360", resolved["dataset_ref"])
        self.assertEqual("green_house_mid360", resolved["dataset"]["dataset_id"])
        self.assertNotIn("dataset_file_ref", resolved)
        self.assertNotIn("dataset_file_sha256", resolved)

    def test_dataset_and_dataset_file_are_mutually_exclusive_and_one_is_required(self) -> None:
        both = self._manifest(dataset="green_house_mid360", dataset_file="/tmp/dataset.json")
        neither = self._manifest()
        both_errors = validate_manifest(both, check_paths=False, manifest_dir=Path("/tmp"))
        neither_errors = validate_manifest(neither, check_paths=False, manifest_dir=Path("/tmp"))
        self.assertTrue(any("exactly one" in error for error in both_errors), both_errors)
        self.assertTrue(any("exactly one" in error for error in neither_errors), neither_errors)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            resolve_manifest(both, manifest_dir=Path("/tmp"))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            resolve_manifest(neither, manifest_dir=Path("/tmp"))

    def test_missing_malformed_and_schema_invalid_external_dataset_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = self._manifest(dataset_file="missing.json")
            errors = validate_manifest(missing, check_paths=False, manifest_dir=root)
            self.assertTrue(any("dataset_file" in error and "not found" in error for error in errors), errors)

            malformed_path = root / "malformed.json"
            malformed_path.write_text("{", encoding="utf-8")
            malformed = self._manifest(dataset_file=str(malformed_path))
            errors = validate_manifest(malformed, check_paths=False, manifest_dir=root)
            self.assertTrue(any("invalid JSON" in error for error in errors), errors)

            invalid_path = root / "invalid.json"
            invalid_path.write_text(json.dumps({"schema_version": 2, "dataset_id": "broken"}), encoding="utf-8")
            invalid = self._manifest(dataset_file=str(invalid_path))
            errors = validate_manifest(invalid, check_paths=False, manifest_dir=root)
            self.assertTrue(any("dataset record" in error or "dataset record missing" in error for error in errors), errors)

    def test_resolved_dataset_is_a_snapshot_not_a_live_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset_path = self._dataset(root)
            manifest = self._manifest(dataset_file=str(dataset_path))
            resolved = resolve_manifest(manifest, manifest_dir=root)
            frozen_id = resolved["dataset"]["dataset_id"]
            frozen_sha = resolved["dataset_file_sha256"]

            payload = json.loads(dataset_path.read_text(encoding="utf-8"))
            payload["dataset_id"] = "mutated_after_resolution"
            dataset_path.write_text(json.dumps(payload), encoding="utf-8")

            self.assertEqual("external_mid360", frozen_id)
            self.assertNotEqual(frozen_sha, sha256_file(dataset_path))

    def test_core_resolve_config_passes_config_parent_as_manifest_dir(self) -> None:
        core = (ROOT / "benchmark_base/bin/lio-benchmark-core").read_text(encoding="utf-8")
        self.assertIn("manifest_dir=path.parent", core)


if __name__ == "__main__":
    unittest.main()
