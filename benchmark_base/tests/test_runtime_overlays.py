from __future__ import annotations

import os
import runpy
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.adapters import AdapterStatus, prepare_algorithm
from benchmark_base.lib.ros_workspace import (
    RuntimeEnvironmentError,
    capture_sourced_environment,
    formal_base_environment,
    runtime_overlays_for_algorithm,
)


class RuntimeOverlayEnvironmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        (self.workspace / "install").mkdir(parents=True)
        self.ros_setup = self.root / "ros_setup.bash"
        self.workspace_setup = self.workspace / "install/setup.bash"

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _write_setup(path: Path, body: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_runtime_overlays_for_algorithm_preserves_frozen_order(self) -> None:
        manifest = {
            "algorithms": {"kiss_icp": {}, "fast_livo2": {}},
            "runtime_overlays": {
                "kiss_icp": [
                    "/opt/vendor/first/setup.bash",
                    "/opt/vendor/second/setup.bash",
                ]
            },
        }
        self.assertEqual(
            (
                Path("/opt/vendor/first/setup.bash"),
                Path("/opt/vendor/second/setup.bash"),
            ),
            runtime_overlays_for_algorithm(manifest, "kiss_icp"),
        )
        self.assertEqual((), runtime_overlays_for_algorithm(manifest, "fast_livo2"))

    def test_formal_base_environment_removes_ambient_overlay_paths(self) -> None:
        source = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/tester",
            "AMENT_PREFIX_PATH": "/ambient/ament",
            "CMAKE_PREFIX_PATH": "/ambient/cmake",
            "COLCON_PREFIX_PATH": "/ambient/colcon",
            "LD_LIBRARY_PATH": "/ambient/lib",
            "PYTHONPATH": "/ambient/python",
            "ROS_PACKAGE_PATH": "/ambient/ros1",
            "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
        }
        result = formal_base_environment(source)
        for key in (
            "AMENT_PREFIX_PATH",
            "CMAKE_PREFIX_PATH",
            "COLCON_PREFIX_PATH",
            "LD_LIBRARY_PATH",
            "PYTHONPATH",
            "ROS_PACKAGE_PATH",
        ):
            self.assertNotIn(key, result)
        self.assertEqual("/usr/bin:/bin", result["PATH"])
        self.assertEqual("rmw_fastrtps_cpp", result["RMW_IMPLEMENTATION"])

    def test_capture_sourced_environment_applies_sources_in_exact_order(self) -> None:
        overlay_a = self.root / "overlay_a/setup.bash"
        overlay_b = self.root / "overlay_b/setup.bash"
        self._write_setup(self.ros_setup, 'export ORDER="ros"\n')
        self._write_setup(self.workspace_setup, 'export ORDER="${ORDER}:workspace"\n')
        self._write_setup(overlay_a, 'export ORDER="${ORDER}:overlay_a"\n')
        self._write_setup(overlay_b, 'export ORDER="${ORDER}:overlay_b"\n')

        env = capture_sourced_environment(
            workspace=self.workspace,
            ros_distro="humble",
            overlays=(overlay_a, overlay_b),
            ros_setup=self.ros_setup,
            base_env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
        self.assertEqual("ros:workspace:overlay_a:overlay_b", env["ORDER"])

    def test_missing_declared_overlay_fails_closed(self) -> None:
        missing = self.root / "missing/setup.bash"
        self._write_setup(self.ros_setup, "export ROS_DISTRO=humble\n")
        self._write_setup(self.workspace_setup, "true\n")
        with self.assertRaisesRegex(RuntimeEnvironmentError, "runtime overlay does not exist"):
            capture_sourced_environment(
                workspace=self.workspace,
                ros_distro="humble",
                overlays=(missing,),
                ros_setup=self.ros_setup,
                base_env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            )

    def test_overlay_source_failure_fails_closed(self) -> None:
        broken = self.root / "broken/setup.bash"
        self._write_setup(self.ros_setup, "export ROS_DISTRO=humble\n")
        self._write_setup(self.workspace_setup, "true\n")
        self._write_setup(broken, "return 7\n")
        with self.assertRaisesRegex(RuntimeEnvironmentError, "failed to source runtime overlay"):
            capture_sourced_environment(
                workspace=self.workspace,
                ros_distro="humble",
                overlays=(broken,),
                ros_setup=self.ros_setup,
                base_env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            )

    def test_prepare_algorithm_reuses_the_same_formal_runtime_environment(self) -> None:
        runner = self.root / "evaluators/run_algo.sh"
        runner.parent.mkdir(parents=True)
        runner.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        prefix = self.root / "formal/install/algo"
        marker = prefix / "share/ament_index/resource_index/packages/algo_pkg"
        marker.parent.mkdir(parents=True)
        marker.write_text("", encoding="utf-8")
        manifest = {
            "workspace": str(self.workspace),
            "dataset": {
                "topics": {"lidar": "/lidar", "imu": None, "camera": None},
                "capabilities": {},
                "calibration": {"status": "BLOCKED_CALIBRATION"},
            },
            "algorithms": {
                "algo": {
                    "required_modalities": ["lidar"],
                    "sensor_profile": {"lidar": True, "imu": False},
                    "execution_implementation": {
                        "package": "algo_pkg",
                        "executable": "algo_node",
                    },
                    "runner": {"adapter": "evaluators/run_algo.sh"},
                    "extrinsic_convention": "NONE",
                    "topics": {"outputs": {}},
                }
            },
            "execution_overrides": {},
            "runtime_overlays": {},
            "replay": {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 15.0},
        }
        formal_env = {
            "ROS_DISTRO": "humble",
            "AMENT_PREFIX_PATH": str(prefix),
        }
        prepared = prepare_algorithm(
            self.root / "run",
            manifest,
            "algo",
            benchmark_root=self.root,
            runtime_env=formal_env,
        )
        self.assertEqual("PASS", prepared.preflight.status)
        self.assertEqual(str(prefix.resolve()), prepared.preflight.checks["runtime_package_prefix"])

    def test_cli_runtime_preflight_passes_constructed_environment_to_adapter(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        namespace = runpy.run_path(str(repo_root / "benchmark_base/bin/lio-benchmark"))
        helper = namespace["runtime_preflight"]
        calls: dict[str, object] = {}
        formal_env = {
            "ROS_DISTRO": "humble",
            "AMENT_PREFIX_PATH": "/formal/install",
        }

        namespace["runtime_overlays_for_algorithm"] = lambda manifest, algorithm_id: (
            Path("/declared/kiss/setup.bash"),
        )
        namespace["resolve_ros_distro"] = lambda run: "humble"

        def fake_capture(**kwargs):
            calls["capture"] = kwargs
            return formal_env

        def fake_preflight(manifest, algorithm_id, **kwargs):
            calls["runtime_env"] = kwargs.get("runtime_env")
            return AdapterStatus(
                algorithm_id=algorithm_id,
                status="PASS",
                runnable=True,
                diagnostic_only=False,
                reasons=(),
                checks={"runtime_package_prefix": "/formal/install/kiss_icp"},
            )

        namespace["capture_sourced_environment"] = fake_capture
        namespace["preflight_algorithm"] = fake_preflight
        manifest = {
            "workspace": "/workspace",
            "algorithms": {"kiss_icp": {}},
            "runtime_overlays": {
                "kiss_icp": ["/declared/kiss/setup.bash"]
            },
        }
        result, captured_env = helper(
            Path("/run"),
            manifest,
            "kiss_icp",
            allow_diagnostic_calibration=False,
        )
        self.assertEqual("PASS", result.status)
        self.assertIs(formal_env, captured_env)
        self.assertIs(formal_env, calls["runtime_env"])
        self.assertEqual(
            ["/declared/kiss/setup.bash"],
            result.checks["runtime_overlays"],
        )


if __name__ == "__main__":
    unittest.main()
