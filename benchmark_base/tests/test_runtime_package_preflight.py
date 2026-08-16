from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.adapters import preflight_algorithm


class RuntimePackagePreflightTest(unittest.TestCase):
    @staticmethod
    def _manifest(root: Path, *, package: str) -> dict:
        runner = root / "evaluators/run_algo.sh"
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        return {
            "workspace": str(root / "ws"),
            "dataset": {
                "dataset_id": "d",
                "topics": {"lidar": "/lidar", "imu": None, "camera": None},
                "capabilities": {},
                "calibration": {"status": "BLOCKED_CALIBRATION"},
            },
            "algorithms": {
                "algo": {
                    "algorithm_id": "algo",
                    "required_modalities": ["lidar"],
                    "sensor_profile": {"lidar": True, "imu": False},
                    "source": {"local_path_hint": "missing/source/tree"},
                    "execution_implementation": {
                        "package": package,
                        "executable": "algo_node",
                    },
                    "runner": {"adapter": "evaluators/run_algo.sh"},
                    "extrinsic_convention": "NONE",
                    "topics": {"inputs": {"lidar": "/lidar"}, "outputs": {}},
                }
            },
            "execution_overrides": {},
            "replay": {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 15.0},
        }

    def test_available_runtime_package_allows_missing_source_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._manifest(root, package="fast_livo")
            result = preflight_algorithm(
                manifest,
                "algo",
                benchmark_root=root,
                runtime_package_prefixes={"fast_livo": "/ws/install/fast_livo"},
            )
            self.assertEqual("PASS", result.status)
            self.assertTrue(result.runnable)
            self.assertFalse(result.checks["source_exists"])
            self.assertEqual("fast_livo", result.checks["runtime_package"])
            self.assertTrue(result.checks["runtime_package_available"])

    def test_missing_runtime_package_blocks_registry_default_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._manifest(root, package="kiss_icp")
            result = preflight_algorithm(
                manifest,
                "algo",
                benchmark_root=root,
                runtime_package_prefixes={"kiss_icp": None},
            )
            self.assertEqual("BLOCKED_ENVIRONMENT", result.status)
            self.assertFalse(result.runnable)
            self.assertEqual("kiss_icp", result.checks["runtime_package"])
            self.assertFalse(result.checks["runtime_package_available"])
            self.assertIn("runtime ROS package is unavailable", " ".join(result.reasons))


if __name__ == "__main__":
    unittest.main()
