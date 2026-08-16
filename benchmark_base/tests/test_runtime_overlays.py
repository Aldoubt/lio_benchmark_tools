from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
