from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from benchmark_base.lib.manifest import resolve_manifest, validate_manifest
from benchmark_base.lib.registry import Registry


class ManifestTest(unittest.TestCase):
    @staticmethod
    def _v2_manifest() -> dict:
        return {
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

    def test_v2_manifest_resolves_registry_records(self) -> None:
        manifest = self._v2_manifest()
        errors = validate_manifest(manifest, registry=Registry(), check_paths=False)
        self.assertEqual([], errors)
        resolved = resolve_manifest(manifest, Registry())
        self.assertEqual("example_mid360", resolved["dataset"]["dataset_id"])
        self.assertEqual(["fast_livo2", "point_lio"], resolved["algorithm_refs"])

    def test_v2_replay_defaults_are_frozen(self) -> None:
        manifest = self._v2_manifest()
        resolved = resolve_manifest(manifest, Registry())
        self.assertEqual(
            {"rate": 1.0, "start_offset_s": 0.0, "duration_s": None},
            resolved["replay"],
        )
        self.assertEqual({}, resolved["execution_overrides"])

    def test_v2_accepts_selected_algorithm_executable_override(self) -> None:
        manifest = self._v2_manifest()
        manifest["execution_overrides"] = {
            "fast_livo2": {"executable": "/tmp/fastlivo_mapping"}
        }
        errors = validate_manifest(
            manifest,
            registry=Registry(),
            check_paths=False,
        )
        self.assertEqual([], errors)
        resolved = resolve_manifest(manifest, Registry())
        self.assertEqual(
            "/tmp/fastlivo_mapping",
            resolved["execution_overrides"]["fast_livo2"]["executable"],
        )

    def test_v2_rejects_override_for_unselected_algorithm(self) -> None:
        manifest = self._v2_manifest()
        manifest["execution_overrides"] = {
            "kiss_icp": {"executable": "/tmp/kiss_icp"}
        }
        errors = validate_manifest(manifest, registry=Registry(), check_paths=False)
        self.assertIn(
            "execution_overrides.kiss_icp references an unselected algorithm",
            errors,
        )

    def test_v2_rejects_malformed_execution_override(self) -> None:
        manifest = self._v2_manifest()
        manifest["execution_overrides"] = {"fast_livo2": {"executable": ""}}
        errors = validate_manifest(manifest, registry=Registry(), check_paths=False)
        self.assertIn(
            "execution_overrides.fast_livo2.executable must be a non-empty string",
            errors,
        )

    def test_v2_rejects_invalid_replay_values(self) -> None:
        cases = (
            ({"rate": 0.0}, "replay.rate must be finite and > 0"),
            ({"start_offset_s": -1.0}, "replay.start_offset_s must be finite and >= 0"),
            ({"duration_s": 0.0}, "replay.duration_s must be null or finite and > 0"),
        )
        for replay, expected in cases:
            with self.subTest(replay=replay):
                manifest = self._v2_manifest()
                manifest["replay"] = replay
                errors = validate_manifest(manifest, registry=Registry(), check_paths=False)
                self.assertIn(expected, errors)

    def test_v2_unknown_algorithm_fails_closed(self) -> None:
        manifest = self._v2_manifest()
        manifest["algorithms"] = ["missing_algorithm"]
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

    def test_scan_manifest_cli_exposes_smoke_window_options(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                sys.executable,
                str(root / "benchmark_base/bin/lio-benchmark"),
                "standardize",
                "scan-manifest",
                "--help",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--start-offset-s", result.stdout)
        self.assertIn("--duration-s", result.stdout)
        self.assertIn("--overwrite", result.stdout)

    def test_bundle_cli_exposes_diagnostic_archive_options(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(root / "benchmark_base/bin/lio-benchmark"), "bundle", "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--run", result.stdout)
        self.assertIn("--include-reports", result.stdout)
        self.assertIn("--output", result.stdout)


if __name__ == "__main__":
    unittest.main()
