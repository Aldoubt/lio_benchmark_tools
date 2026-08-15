from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.adapters import (
    collect_algorithm,
    preflight_algorithm,
    prepare_algorithm,
)


class AdapterLifecycleTest(unittest.TestCase):
    def test_missing_source_repository_is_blocked_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._manifest(root)
            result = preflight_algorithm(manifest, "lio", benchmark_root=root)
            self.assertEqual("BLOCKED_ENVIRONMENT", result.status)
            self.assertFalse(result.runnable)

    def test_missing_runner_is_implementation_failure_after_source_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "ws/src/lio"
            source.mkdir(parents=True)
            manifest = self._manifest(root)
            result = preflight_algorithm(manifest, "lio", benchmark_root=root)
            self.assertEqual("FAIL_IMPLEMENTATION", result.status)
            self.assertIn("runner", " ".join(result.reasons).lower())

    def test_missing_required_imu_topic_is_blocked_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._create_source_and_runner(root)
            manifest = self._manifest(root)
            manifest["dataset"]["topics"]["imu"] = None
            result = preflight_algorithm(manifest, "lio", benchmark_root=root)
            self.assertEqual("BLOCKED_INPUT", result.status)

    def test_unconfirmed_calibration_is_blocked_for_lidar_imu(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._create_source_and_runner(root)
            manifest = self._manifest(root)
            manifest["dataset"]["calibration"]["status"] = "BLOCKED_CALIBRATION"
            result = preflight_algorithm(manifest, "lio", benchmark_root=root)
            self.assertEqual("BLOCKED_CALIBRATION", result.status)
            self.assertTrue(result.diagnostic_only)

    def test_lidar_only_control_does_not_require_imu_or_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "ws/src/kiss"
            source.mkdir(parents=True)
            runner = root / "evaluators/run_kiss.sh"
            runner.parent.mkdir(parents=True)
            runner.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            manifest = self._manifest(root)
            manifest["dataset"]["topics"]["imu"] = None
            manifest["dataset"]["calibration"] = {"status": "BLOCKED_CALIBRATION"}
            manifest["algorithms"] = {
                "kiss": {
                    "algorithm_id": "kiss",
                    "required_modalities": ["lidar"],
                    "sensor_profile": {"lidar": True, "imu": False},
                    "source": {"local_path_hint": "src/kiss"},
                    "runner": {"adapter": "evaluators/run_kiss.sh"},
                    "extrinsic_convention": "NONE",
                    "topics": {"inputs": {"lidar": "/points"}, "outputs": {}},
                }
            }
            result = preflight_algorithm(manifest, "kiss", benchmark_root=root)
            self.assertEqual("PASS", result.status)
            self.assertTrue(result.runnable)
            self.assertFalse(result.diagnostic_only)

    def test_prepare_writes_run_local_calibration_without_touching_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._create_source_and_runner(root)
            manifest = self._manifest(root)
            run = root / "run"
            prepared = prepare_algorithm(run, manifest, "lio", benchmark_root=root)
            self.assertTrue(prepared.generated_config_dir.is_dir())
            calibration = prepared.generated_config_dir / "calibration.json"
            self.assertTrue(calibration.is_file())
            payload = json.loads(calibration.read_text(encoding="utf-8"))
            self.assertEqual("IMU_TO_LIDAR", payload["convention"])
            self.assertFalse((root / "ws/src/lio/calibration.json").exists())

    def test_collect_preserves_declared_missing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = root / "run"
            (run / "raw/lio").mkdir(parents=True)
            manifest = self._manifest(root)
            report = collect_algorithm(run, manifest, "lio")
            self.assertEqual("lio", report.algorithm_id)
            self.assertEqual("MISSING", report.outputs["trajectory"]["status"])

    @staticmethod
    def _create_source_and_runner(root: Path) -> None:
        (root / "ws/src/lio").mkdir(parents=True)
        runner = root / "evaluators/run_lio.sh"
        runner.parent.mkdir(parents=True)
        runner.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    @staticmethod
    def _manifest(root: Path) -> dict:
        return {
            "workspace": str(root / "ws"),
            "dataset": {
                "dataset_id": "d",
                "topics": {"lidar": "/lidar", "imu": "/imu", "camera": None},
                "calibration": {
                    "rotation_lidar_to_imu_row_major": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                    "translation_lidar_to_imu_m": [1, 2, 3],
                    "source": "unit",
                    "status": "CONFIRMED",
                },
            },
            "algorithms": {
                "lio": {
                    "algorithm_id": "lio",
                    "required_modalities": ["lidar", "imu"],
                    "sensor_profile": {"lidar": True, "imu": True},
                    "source": {"local_path_hint": "src/lio"},
                    "runner": {"adapter": "evaluators/run_lio.sh"},
                    "extrinsic_convention": "IMU_TO_LIDAR",
                    "topics": {
                        "inputs": {"lidar": "/lidar", "imu": "/imu"},
                        "outputs": {"trajectory": "trajectory.csv", "native_map": "map.pcd"},
                    },
                }
            },
        }


if __name__ == "__main__":
    unittest.main()
