from __future__ import annotations

import unittest
from pathlib import Path

from benchmark_base.lib.ros_workspace import build_sourced_python_command


class RosWorkspaceCommandTest(unittest.TestCase):
    def test_python_command_sources_ros_and_workspace_overlay(self) -> None:
        command = build_sourced_python_command(
            python_executable="/usr/bin/python3",
            script=Path("/repo/evaluators/standardize_map.py"),
            arguments=["--run", "/runs/smoke", "--algorithm", "fast_livo2"],
            workspace=Path("/home/user/ws"),
            ros_distro="humble",
        )
        self.assertEqual(["bash", "-lc"], command[:2])
        shell = command[2]
        self.assertIn("source /opt/ros/humble/setup.bash", shell)
        self.assertIn("source /home/user/ws/install/setup.bash", shell)
        self.assertIn("exec /usr/bin/python3 /repo/evaluators/standardize_map.py", shell)
        self.assertIn("--run /runs/smoke", shell)


if __name__ == "__main__":
    unittest.main()
