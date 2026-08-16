#!/usr/bin/env python3
"""Runtime execution resolution and immutable run-time identity evidence."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from benchmark_base.lib.manifest import normalized_replay, sha256_file
from benchmark_base.lib.runtime_provenance import source_relationship as classify_source_relationship


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


def fingerprint_runtime_overlays(
    paths: Iterable[str | Path],
) -> list[dict[str, Any]]:
    """Fingerprint the exact frozen setup scripts in declared source order."""
    evidence: list[dict[str, Any]] = []
    for path in paths:
        candidate = Path(path).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
            if not resolved.is_file():
                raise OSError("not a regular file")
            stat = resolved.stat()
            digest = sha256_file(resolved)
        except (OSError, RuntimeError) as exc:
            raise ExecutionContractError(
                f"BLOCKED_EXECUTION: failed to fingerprint runtime overlay: {candidate}"
            ) from exc
        evidence.append(
            {
                "setup_path": str(resolved),
                "setup_sha256": digest,
                "setup_size_bytes": int(stat.st_size),
            }
        )
    return evidence


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


def _source_state(value: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(value or {})
    for key in ("path", "git_root", "remote_origin", "commit", "branch", "dirty"):
        source.setdefault(key, None)
    return source


def _implementation(manifest: dict[str, Any], algorithm_id: str) -> dict[str, Any]:
    algorithm = _selected_algorithm(manifest, algorithm_id)
    implementation = algorithm.get("execution_implementation", {})
    return implementation if isinstance(implementation, dict) else {}


def build_runtime_identity(
    *,
    manifest: dict[str, Any],
    algorithm_id: str,
    resolution: ExecutionResolution,
    effective_command: list[str],
    effective_config: Path | None,
    ros_distro: str | None,
    source_state: dict[str, Any] | None,
    runtime_package: str | None,
    runtime_package_prefix: str | None,
    runtime_overlays: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the immutable run-time identity payload before estimator startup."""
    implementation = _implementation(manifest, algorithm_id)
    registry_package = str(implementation.get("package", "")) or None
    expected_repository = str(implementation.get("repository", "")) or None
    executable_identity = None
    if resolution.resolved_executable is not None:
        executable_identity = fingerprint_executable(resolution.resolved_executable)
    source = _source_state(source_state)
    relationship = classify_source_relationship(
        expected_repository,
        str(source.get("remote_origin")) if source.get("remote_origin") else None,
    )
    return {
        "schema_version": 1,
        "algorithm_id": algorithm_id,
        "captured_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "identity_status": "FROZEN",
        "blocking_reason": None,
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
        "registry_package": registry_package,
        "runtime_package": runtime_package,
        "runtime_package_prefix": runtime_package_prefix,
        "runtime_overlays": list(runtime_overlays or []),
        "source": source,
        "registry_execution_implementation": implementation,
        "source_relationship": relationship,
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
        "replay": normalized_replay(manifest),
    }


def build_blocked_runtime_identity(
    *,
    manifest: dict[str, Any],
    algorithm_id: str,
    reason: str,
) -> dict[str, Any]:
    """Record a real run attempt that was blocked before estimator startup."""
    implementation = _implementation(manifest, algorithm_id)
    overrides = manifest.get("execution_overrides", {})
    override = overrides.get(algorithm_id) if isinstance(overrides, dict) else None
    requested = override.get("executable") if isinstance(override, dict) else None
    method = (
        EXPLICIT_EXECUTABLE_OVERRIDE
        if isinstance(requested, str) and requested.strip()
        else REGISTRY_DEFAULT_EXECUTION
    )
    return {
        "schema_version": 1,
        "algorithm_id": algorithm_id,
        "captured_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "identity_status": "BLOCKED_EXECUTION",
        "blocking_reason": str(reason),
        "resolution_method": method,
        "requested_executable": requested.strip() if isinstance(requested, str) else None,
        "resolved_executable": None,
        "executable_sha256": None,
        "executable_size_bytes": None,
        "executable_mtime_ns": None,
        "registry_package": implementation.get("package"),
        "runtime_package": None,
        "runtime_package_prefix": None,
        "runtime_overlays": [],
        "source": _source_state(None),
        "registry_execution_implementation": implementation,
        "source_relationship": "UNKNOWN_SOURCE",
        "launch_mode": None,
        "effective_command": [],
        "effective_config": {"path": None, "sha256": None},
        "environment": {
            "ros_distro": None,
            "workspace": str(Path(str(manifest.get("workspace", "."))).expanduser().resolve()),
        },
        "dataset": {
            "bag_dir": str(manifest.get("dataset", {}).get("bag_dir", ""))
            if isinstance(manifest.get("dataset"), dict)
            else None,
        },
        "replay": normalized_replay(manifest),
    }


def runtime_identity_path(run_dir: str | Path, algorithm_id: str) -> Path:
    return Path(run_dir) / "metadata" / "algorithms" / algorithm_id / "runtime_identity.json"


def write_runtime_identity(
    run_dir: str | Path,
    algorithm_id: str,
    payload: dict[str, Any],
) -> Path:
    """Write runtime identity once; never silently overwrite execution evidence."""
    target = runtime_identity_path(run_dir, algorithm_id)
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
