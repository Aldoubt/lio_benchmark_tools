#!/usr/bin/env python3
"""Helpers for running benchmark evaluators in the same ROS overlay as adapters."""
from __future__ import annotations

from pathlib import Path
import shlex


def build_sourced_python_command(
    *,
    python_executable: str,
    script: Path,
    arguments: list[str],
    workspace: Path,
    ros_distro: str,
) -> list[str]:
    if not ros_distro:
        raise ValueError("ros_distro is required")
    ros_setup = Path("/opt/ros") / ros_distro / "setup.bash"
    workspace_setup = workspace / "install" / "setup.bash"
    python_command = shlex.join([python_executable, str(script), *arguments])
    shell = (
        "set -e; "
        f"source {shlex.quote(str(ros_setup))}; "
        f"if [[ -f {shlex.quote(str(workspace_setup))} ]]; then "
        f"source {shlex.quote(str(workspace_setup))}; fi; "
        f"exec {python_command}"
    )
    return ["bash", "-lc", shell]
