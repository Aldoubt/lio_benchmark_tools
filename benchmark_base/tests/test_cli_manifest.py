from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from benchmark_base.lib.manifest import resolve_manifest, validate_manifest
from benchmark_base.lib.registry import Registry


class ManifestTest(unittest.TestCase):
    def test_v2_manifest_resolves_registry_records(self) -> None:
        manifest = {
            "schema_version": 2,
            "name": "unit",
            "workspace": "/tmp/workspace",
            "output_root": "/tmp/runs",
            "dataset": "example_mid360",
            "algorithms": ["fast_livo2", "point_lio"],
            "standardization": {
                "map_voxel_m": 0.12,
                "near_range_m": 0.5,
                "trajectory_time_tolerance_s": 0.05,
            },
        }
        errors = validate_manifest(manifest, registry=Registry(), check_paths=False)
        self.assertEqual([], errors)
        resolved = resolve_manifest(manifest, Registry())
        self.assertEqual("example_mid360", resolved["dataset"]["dataset_id"])
        self.assertEqual(["fast_livo2", "point_lio"], resolved["algorithm_refs"])

    def test_v2_unknown_algorithm_fails_closed(self) -> None:
        manifest = {
            "schema_version": 2,
            "name": "unit",
            "workspace": "/tmp/workspace",
            "output_root": "/tmp/runs",
            "dataset": "example_mid360",
            "algorithms": ["missing_algorithm"],
            "standardization": {
                "map_voxel_m": 0.12,
                "near_range_m": 0.5,
                "trajectory_time_tolerance_s": 0.05,
            },
        }
        errors = validate_manifest(manifest, registry=Registry(), check_paths=False)
        self.assertTrue(any("not found" in error for error in errors))

    def test_v1_manifest_shape_remains_supported_without_path_checks(self) -> None:
        manifest = {
            "schema_version": 1,
            "name": "legacy",
            "workspace": "/tmp/ws",
            "output_root": "/tmp/runs",
            "dataset": {
                "bag_dir": "/tmp/bag",
                "db3": "/tmp/bag/data.db3",
                "lidar_topic": "/lidar",
                "lidar_type": "sensor_msgs/msg/PointCloud2",
                "imu_topic": "/imu",
                "imu_type": "sensor_msgs/msg/Imu",
                "imu_acceleration_unit": "g",
                "point_time_field": "timestamp",
                "point_time_unit": "ns_absolute",
            },
            "calibration": {
                "rotation_lidar_to_imu_row_major": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                "translation_lidar_to_imu_m": [0, 0, 0],
            },
            "evaluation": {},
            "algorithms": {
                "example": {
                    "mode": "odometry",
                    "runner": "evaluators/run_fast_livo_test.sh",
                }
            },
        }
        self.assertEqual([], validate_manifest(manifest, check_paths=False))
        self.assertEqual(manifest, resolve_manifest(manifest))

    def test_report_cli_exposes_warmup_option(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(root / "benchmark_base/bin/lio-benchmark"), "report", "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--warmup-s", result.stdout)


if __name__ == "__main__":
    unittest.main()
