#!/usr/bin/env python3
"""Helpers for constructing deterministic ROS runtime environments."""
from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any


_OVERLAY_PATH_KEYS = frozenset(
    {
        "AMENT_PREFIX_PATH",
        "CMAKE_PREFIX_PATH",
        "COLCON_PREFIX_PATH",
        "COLCON_CURRENT_PREFIX",
        "LD_LIBRARY_PATH",
        "PYTHONPATH",
        "ROS_PACKAGE_PATH",
    }
)


class RuntimeEnvironmentError(ValueError):
    """The frozen ROS runtime environment cannot be constructed safely."""


def formal_base_environment(
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Remove caller-owned overlay paths before formal source reconstruction."""
    source = os.environ if base_env is None else base_env
    return {
        str(key): str(value)
        for key, value in source.items()
        if str(key) not in _OVERLAY_PATH_KEYS
    }


def runtime_overlays_for_algorithm(
    manifest: dict[str, Any], algorithm_id: str
) -> tuple[Path, ...]:
    algorithms = manifest.get("algorithms", {})
    if not isinstance(algorithms, dict) or algorithm_id not in algorithms:
        raise RuntimeEnvironmentError(
            f"algorithm is not selected in frozen manifest: {algorithm_id}"
        )
    raw = manifest.get("runtime_overlays", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RuntimeEnvironmentError("frozen runtime_overlays must be an object")
    overlays = raw.get(algorithm_id, [])
    if overlays is None:
        overlays = []
    if not isinstance(overlays, list):
        raise RuntimeEnvironmentError(
            f"frozen runtime_overlays.{algorithm_id} must be a list"
        )
    result: list[Path] = []
    for index, value in enumerate(overlays):
        if not isinstance(value, str) or not value.strip():
            raise RuntimeEnvironmentError(
                f"frozen runtime_overlays.{algorithm_id}[{index}] is invalid"
            )
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            raise RuntimeEnvironmentError(
                f"frozen runtime_overlays.{algorithm_id}[{index}] is not absolute"
            )
        result.append(path)
    return tuple(result)


def _source_statement(path: Path, *, label: str, failure_code: int) -> str:
    quoted = shlex.quote(str(path))
    message = shlex.quote(f"failed to source {label}: {path}")
    return (
        f"source {quoted} || {{ printf '%s\\n' {message} >&2; "
        f"exit {failure_code}; }}"
    )


def _runtime_source_shell(
    *,
    workspace: Path,
    ros_distro: str,
    overlays: tuple[Path, ...],
    ros_setup: Path | None = None,
    final_command: str,
) -> str:
    if not ros_distro:
        raise RuntimeEnvironmentError("ros_distro is required")
    selected_ros_setup = (
        Path("/opt/ros") / ros_distro / "setup.bash"
        if ros_setup is None
        else Path(ros_setup)
    )
    if not selected_ros_setup.is_file():
        raise RuntimeEnvironmentError(
            f"ROS setup does not exist or is not a regular file: {selected_ros_setup}"
        )
    for overlay in overlays:
        if not overlay.is_file():
            raise RuntimeEnvironmentError(
                f"runtime overlay does not exist or is not a regular file: {overlay}"
            )

    workspace_setup = workspace / "install" / "setup.bash"
    statements = ["set -e"]
    statements.append(
        _source_statement(selected_ros_setup, label="ROS setup", failure_code=61)
    )
    if workspace_setup.is_file():
        statements.append(
            _source_statement(workspace_setup, label="workspace setup", failure_code=62)
        )
    for overlay in overlays:
        statements.append(
            _source_statement(overlay, label="runtime overlay", failure_code=65)
        )
    statements.append(final_command)
    return "; ".join(statements)


def capture_sourced_environment(
    *,
    workspace: Path,
    ros_distro: str,
    overlays: tuple[Path, ...] = (),
    ros_setup: Path | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the environment after sourcing the exact frozen ROS stack."""
    shell = _runtime_source_shell(
        workspace=Path(workspace).expanduser().resolve(),
        ros_distro=ros_distro,
        overlays=tuple(Path(path).expanduser() for path in overlays),
        ros_setup=ros_setup,
        final_command="env -0",
    )
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", shell],
        env=formal_base_environment(base_env),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = os.fsdecode(result.stderr).strip()
        if result.returncode == 65:
            detail = stderr or "runtime overlay source returned non-zero"
            raise RuntimeEnvironmentError(detail)
        detail = stderr or f"source shell returned {result.returncode}"
        raise RuntimeEnvironmentError(f"failed to construct formal ROS environment: {detail}")

    captured: dict[str, str] = {}
    for row in result.stdout.split(b"\0"):
        if not row or b"=" not in row:
            continue
        key, value = row.split(b"=", 1)
        captured[os.fsdecode(key)] = os.fsdecode(value)
    return captured


def build_sourced_python_command(
    *,
    python_executable: str,
    script: Path,
    arguments: list[str],
    workspace: Path,
    ros_distro: str,
    overlays: tuple[Path, ...] = (),
) -> list[str]:
    if not ros_distro:
        raise ValueError("ros_distro is required")
    ros_setup = Path("/opt/ros") / ros_distro / "setup.bash"
    workspace_setup = workspace / "install" / "setup.bash"
    python_command = shlex.join([python_executable, str(script), *arguments])
    statements = ["set -e", f"source {shlex.quote(str(ros_setup))}"]
    statements.append(
        f"if [[ -f {shlex.quote(str(workspace_setup))} ]]; then "
        f"source {shlex.quote(str(workspace_setup))}; fi"
    )
    for overlay in overlays:
        statements.append(f"source {shlex.quote(str(overlay))}")
    statements.append(f"exec {python_command}")
    return ["bash", "-lc", "; ".join(statements)]
