#!/usr/bin/env python3
"""Runtime execution resolution and immutable run-time identity evidence."""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from benchmark_base.lib.manifest import normalized_replay, sha256_file


EXPLICIT_EXECUTABLE_OVERRIDE = "EXPLICIT_EXECUTABLE_OVERRIDE"
REGISTRY_DEFAULT_EXECUTION = "REGISTRY_DEFAULT_EXECUTION"


class ExecutionContractError(ValueError):
    """A fail-closed runtime execution contract violation."""


@dataclass(frozen=True)
class ExecutionResolution:
    algorithm_id: str
    resolution_method: str
    requested_executable: str | None
    resolved_executable: Path | None


def _selected_algorithm(manifest: dict[str, Any], algorithm_id: str) -> dict[str, Any]:
    algorithms = manifest.get("algorithms", {})
    if not isinstance(algorithms, dict) or algorithm_id not in algorithms:
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: algorithm is not selected in frozen manifest: {algorithm_id}"
        )
    algorithm = algorithms[algorithm_id]
    if not isinstance(algorithm, dict):
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: algorithm manifest entry is not an object: {algorithm_id}"
        )
    return algorithm


def resolve_execution(manifest: dict[str, Any], algorithm_id: str) -> ExecutionResolution:
    """Resolve exactly one of explicit override or registry-default execution."""
    _selected_algorithm(manifest, algorithm_id)
    overrides = manifest.get("execution_overrides", {})
    overrides = overrides if isinstance(overrides, dict) else {}
    override = overrides.get(algorithm_id)
    if override is None:
        return ExecutionResolution(
            algorithm_id=algorithm_id,
            resolution_method=REGISTRY_DEFAULT_EXECUTION,
            requested_executable=None,
            resolved_executable=None,
        )
    if not isinstance(override, dict):
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: execution override must be an object: {algorithm_id}"
        )
    requested = override.get("executable")
    if not isinstance(requested, str) or not requested.strip():
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: explicit executable is missing for {algorithm_id}"
        )
    raw_path = Path(requested.strip()).expanduser()
    try:
        resolved = raw_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: explicit executable cannot be resolved for {algorithm_id}: {raw_path}"
        ) from exc
    if not resolved.is_file():
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: explicit executable is not a regular file for {algorithm_id}: {resolved}"
        )
    if not os.access(resolved, os.X_OK):
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: explicit executable is not executable for {algorithm_id}: {resolved}"
        )
    return ExecutionResolution(
        algorithm_id=algorithm_id,
        resolution_method=EXPLICIT_EXECUTABLE_OVERRIDE,
        requested_executable=requested.strip(),
        resolved_executable=resolved,
    )


def fingerprint_executable(path: str | Path) -> dict[str, Any]:
    """Freeze a direct executable's content and filesystem identity."""
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
        stat = resolved.stat()
        digest = sha256_file(resolved)
    except (OSError, RuntimeError) as exc:
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: failed to fingerprint executable: {candidate}"
        ) from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: executable fingerprint target is not runnable: {resolved}"
        )
    return {
        "realpath": str(resolved),
        "sha256": digest,
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _config_identity(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "sha256": None}
    candidate = path.expanduser()
    try:
        resolved = candidate.resolve(strict=True)
        digest = sha256_file(resolved)
    except (OSError, RuntimeError) as exc:
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: failed to fingerprint effective config: {candidate}"
        ) from exc
    if not resolved.is_file():
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: effective config is not a regular file: {resolved}"
        )
    return {"path": str(resolved), "sha256": digest}


def build_runtime_identity(
    *,
    manifest: dict[str, Any],
    algorithm_id: str,
    resolution: ExecutionResolution,
    effective_command: list[str],
    effective_config: Path | None,
    ros_distro: str | None,
    source_state: dict[str, Any] | None,
    ros_package_prefix: str | None,
) -> dict[str, Any]:
    """Build the immutable run-time identity payload before estimator startup."""
    algorithm = _selected_algorithm(manifest, algorithm_id)
    implementation = algorithm.get("execution_implementation", {})
    implementation = implementation if isinstance(implementation, dict) else {}
    package = str(implementation.get("package", "")) or None
    executable_identity = None
    if resolution.resolved_executable is not None:
        executable_identity = fingerprint_executable(resolution.resolved_executable)
    replay = normalized_replay(manifest)
    source = dict(source_state or {})
    source.setdefault("path", None)
    source.setdefault("git_root", None)
    source.setdefault("remote_origin", None)
    source.setdefault("commit", None)
    source.setdefault("branch", None)
    source.setdefault("dirty", None)
    return {
        "schema_version": 1,
        "algorithm_id": algorithm_id,
        "captured_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "identity_status": "FROZEN",
        "resolution_method": resolution.resolution_method,
        "requested_executable": resolution.requested_executable,
        "resolved_executable": (
            executable_identity["realpath"] if executable_identity is not None else None
        ),
        "executable_sha256": (
            executable_identity["sha256"] if executable_identity is not None else None
        ),
        "executable_size_bytes": (
            executable_identity["size_bytes"] if executable_identity is not None else None
        ),
        "executable_mtime_ns": (
            executable_identity["mtime_ns"] if executable_identity is not None else None
        ),
        "ros_package": package,
        "ros_package_prefix": ros_package_prefix,
        "source": source,
        "registry_execution_implementation": implementation,
        "source_relationship": "UNKNOWN_SOURCE",
        "launch_mode": (
            "DIRECT_EXECUTABLE"
            if resolution.resolution_method == EXPLICIT_EXECUTABLE_OVERRIDE
            else "REGISTRY_DEFAULT"
        ),
        "effective_command": [str(value) for value in effective_command],
        "effective_config": _config_identity(effective_config),
        "environment": {
            "ros_distro": ros_distro or None,
            "workspace": str(Path(str(manifest.get("workspace", "."))).expanduser().resolve()),
        },
        "dataset": {
            "bag_dir": str(manifest.get("dataset", {}).get("bag_dir", ""))
            if isinstance(manifest.get("dataset"), dict)
            else None,
        },
        "replay": replay,
    }


def write_runtime_identity(
    run_dir: str | Path,
    algorithm_id: str,
    payload: dict[str, Any],
) -> Path:
    """Write runtime identity once; never silently overwrite frozen evidence."""
    run = Path(run_dir)
    target = run / "metadata" / "algorithms" / algorithm_id / "runtime_identity.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: runtime identity already exists; create a new run id: {target}"
        )
    temporary = target.with_name(target.name + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        temporary.write_text(data, encoding="utf-8")
        os.replace(temporary, target)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ExecutionContractError(
            f"BLOCKED_EXECUTION: failed to write runtime identity: {target}"
        ) from exc
    return target
