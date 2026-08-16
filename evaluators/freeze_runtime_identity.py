#!/usr/bin/env python3
"""Freeze the exact runtime implementation immediately before estimator start."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.execution_contract import (  # noqa: E402
    EXPLICIT_EXECUTABLE_OVERRIDE,
    ExecutionContractError,
    build_runtime_identity,
    resolve_execution,
    write_runtime_identity,
)
from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.runtime_provenance import workspace_from_package_prefix  # noqa: E402


def capture(command: list[str], *, cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def package_prefix(package: str | None) -> str | None:
    if not package:
        return None
    return capture(["ros2", "pkg", "prefix", package])


def package_source(workspace: Path | None, package: str | None) -> Path | None:
    if workspace is None or package is None or not workspace.is_dir():
        return None
    text = capture(["colcon", "list"], cwd=workspace)
    if not text:
        return None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] != package:
            continue
        path = Path(parts[1]).expanduser()
        if not path.is_absolute():
            path = workspace / path
        return path.resolve()
    return None


def git_state(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None}
    root = capture(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
    if not root:
        return {"path": str(path)}
    git_root = Path(root).resolve()
    return {
        "path": str(path.resolve()),
        "git_root": str(git_root),
        "remote_origin": capture(["git", "-C", str(git_root), "remote", "get-url", "origin"]),
        "commit": capture(["git", "-C", str(git_root), "rev-parse", "HEAD"]),
        "branch": capture(["git", "-C", str(git_root), "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(capture(["git", "-C", str(git_root), "status", "--porcelain"])),
    }


def registry_runtime_binary(prefix: str | None, algorithm: dict[str, Any]) -> Path | None:
    implementation = algorithm.get("execution_implementation", {})
    implementation = implementation if isinstance(implementation, dict) else {}
    package = str(implementation.get("package", "")) or None
    executable = str(implementation.get("executable", "")) or None
    if not prefix or not package or not executable:
        return None
    candidate = Path(prefix) / "lib" / package / executable
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return resolved if resolved.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithm", required=True)
    parser.add_argument("--effective-command-json", required=True)
    parser.add_argument("--effective-config", type=Path)
    args = parser.parse_args()

    run = args.run.resolve()
    manifest = load_json(run / "manifest.json")
    algorithm = manifest.get("algorithms", {}).get(args.algorithm)
    if not isinstance(algorithm, dict):
        raise SystemExit(f"algorithm is not selected in run: {args.algorithm}")
    try:
        command = json.loads(args.effective_command_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid effective command JSON: {exc}") from exc
    if not isinstance(command, list) or not all(isinstance(value, str) for value in command):
        raise SystemExit("effective command JSON must be a string array")

    resolution = resolve_execution(manifest, args.algorithm)
    implementation = algorithm.get("execution_implementation", {})
    implementation = implementation if isinstance(implementation, dict) else {}
    registry_package = str(implementation.get("package", "")) or None

    runtime_package: str | None = None
    runtime_prefix: str | None = None
    source_candidate: Path | None = None
    if resolution.resolution_method == EXPLICIT_EXECUTABLE_OVERRIDE:
        source_candidate = resolution.resolved_executable.parent if resolution.resolved_executable else None
    else:
        runtime_package = registry_package
        runtime_prefix = package_prefix(runtime_package)
        runtime_binary = registry_runtime_binary(runtime_prefix, algorithm)
        if runtime_binary is not None:
            resolution = replace(resolution, resolved_executable=runtime_binary)
        workspace = workspace_from_package_prefix(runtime_prefix)
        source_candidate = package_source(workspace, runtime_package)
        if source_candidate is None and workspace is not None:
            source_candidate = workspace

    config = args.effective_config
    if config is not None and not config.is_file():
        raise SystemExit(f"effective config does not exist: {config}")

    try:
        payload = build_runtime_identity(
            manifest=manifest,
            algorithm_id=args.algorithm,
            resolution=resolution,
            effective_command=command,
            effective_config=config,
            ros_distro=os.environ.get("ROS_DISTRO") or None,
            source_state=git_state(source_candidate),
            runtime_package=runtime_package,
            runtime_package_prefix=runtime_prefix,
        )
        path = write_runtime_identity(run, args.algorithm, payload)
    except ExecutionContractError as exc:
        raise SystemExit(str(exc)) from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
