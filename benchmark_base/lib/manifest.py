#!/usr/bin/env python3
"""Experiment manifest validation and V2 registry resolution."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .registry import Registry, RegistryError


V1_REQUIRED_DATASET_KEYS = (
    "bag_dir",
    "db3",
    "lidar_topic",
    "lidar_type",
    "imu_topic",
    "imu_type",
    "imu_acceleration_unit",
    "point_time_field",
    "point_time_unit",
)


def load_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON {path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("experiment manifest root must be an object")
    return value


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def schema_version(manifest: dict[str, Any]) -> int:
    value = manifest.get("schema_version")
    if value not in (1, 2):
        raise ValueError("schema_version must be 1 or 2")
    return int(value)


def normalized_replay(manifest: dict[str, Any]) -> dict[str, float | None]:
    raw = manifest.get("replay", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("replay must be an object")
    try:
        rate = float(raw.get("rate", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("replay.rate must be finite and > 0") from exc
    try:
        start = float(raw.get("start_offset_s", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("replay.start_offset_s must be finite and >= 0") from exc
    duration_raw = raw.get("duration_s")
    if duration_raw is None:
        duration = None
    else:
        try:
            duration = float(duration_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("replay.duration_s must be null or finite and > 0") from exc
    if not math.isfinite(rate) or rate <= 0.0:
        raise ValueError("replay.rate must be finite and > 0")
    if not math.isfinite(start) or start < 0.0:
        raise ValueError("replay.start_offset_s must be finite and >= 0")
    if duration is not None and (not math.isfinite(duration) or duration <= 0.0):
        raise ValueError("replay.duration_s must be null or finite and > 0")
    return {"rate": rate, "start_offset_s": start, "duration_s": duration}


def normalized_execution_overrides(
    manifest: dict[str, Any], selected_algorithms: list[str] | tuple[str, ...]
) -> dict[str, dict[str, str]]:
    raw = manifest.get("execution_overrides", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("execution_overrides must be an object")
    selected = set(selected_algorithms)
    normalized: dict[str, dict[str, str]] = {}
    for algorithm_id, override in raw.items():
        algorithm_id = str(algorithm_id)
        if algorithm_id not in selected:
            raise ValueError(
                f"execution_overrides.{algorithm_id} references an unselected algorithm"
            )
        if not isinstance(override, dict):
            raise ValueError(f"execution_overrides.{algorithm_id} must be an object")
        unknown = sorted(set(override) - {"executable"})
        if unknown:
            raise ValueError(
                f"execution_overrides.{algorithm_id} has unsupported fields: {', '.join(unknown)}"
            )
        executable = override.get("executable")
        if not isinstance(executable, str) or not executable.strip():
            raise ValueError(
                f"execution_overrides.{algorithm_id}.executable must be a non-empty string"
            )
        normalized[algorithm_id] = {"executable": executable.strip()}
    return normalized


def normalized_runtime_overlays(
    manifest: dict[str, Any], selected_algorithms: list[str] | tuple[str, ...]
) -> dict[str, list[str]]:
    raw = manifest.get("runtime_overlays", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("runtime_overlays must be an object")
    selected = set(selected_algorithms)
    normalized: dict[str, list[str]] = {}
    for algorithm_id, overlays in raw.items():
        algorithm_id = str(algorithm_id)
        if algorithm_id not in selected:
            raise ValueError(
                f"runtime_overlays.{algorithm_id} references an unselected algorithm"
            )
        if not isinstance(overlays, list) or not overlays:
            raise ValueError(f"runtime_overlays.{algorithm_id} must be a non-empty list")
        values: list[str] = []
        seen: set[str] = set()
        for index, overlay in enumerate(overlays):
            if not isinstance(overlay, str) or not overlay.strip():
                raise ValueError(
                    f"runtime_overlays.{algorithm_id}[{index}] must be a non-empty string"
                )
            value = overlay.strip()
            if not Path(value).expanduser().is_absolute():
                raise ValueError(f"runtime_overlays.{algorithm_id}[{index}] must be absolute")
            if value in seen:
                raise ValueError(
                    f"runtime_overlays.{algorithm_id} contains duplicate overlay path: {value}"
                )
            seen.add(value)
            values.append(value)
        normalized[algorithm_id] = values
    return normalized


def resolve_manifest(manifest: dict[str, Any], registry: Registry | None = None) -> dict[str, Any]:
    """Resolve schema-v2 references into a frozen v1-like runtime structure."""
    version = schema_version(manifest)
    if version == 1:
        return dict(manifest)
    active = registry or Registry()
    dataset_ref = manifest.get("dataset")
    algorithm_refs = manifest.get("algorithms")
    if not isinstance(dataset_ref, str) or not dataset_ref:
        raise ValueError("schema-v2 dataset must be a registry id string")
    if (
        not isinstance(algorithm_refs, list)
        or not algorithm_refs
        or not all(isinstance(item, str) and item for item in algorithm_refs)
    ):
        raise ValueError("schema-v2 algorithms must be a non-empty list of registry ids")
    try:
        dataset = active.load_dataset(dataset_ref)
        algorithms = {item: active.load_algorithm(item) for item in algorithm_refs}
    except RegistryError as exc:
        raise ValueError(str(exc)) from exc
    resolved = dict(manifest)
    resolved["source_schema_version"] = 2
    resolved["dataset_ref"] = dataset_ref
    resolved["algorithm_refs"] = list(algorithm_refs)
    resolved["dataset"] = dataset
    resolved["algorithms"] = algorithms
    resolved["execution_overrides"] = normalized_execution_overrides(manifest, algorithm_refs)
    resolved["runtime_overlays"] = normalized_runtime_overlays(manifest, algorithm_refs)
    resolved["replay"] = normalized_replay(manifest)
    return resolved


def validate_manifest(
    manifest: dict[str, Any],
    *,
    registry: Registry | None = None,
    verify_hash: bool = False,
    check_paths: bool = True,
    module_root: str | Path | None = None,
) -> list[str]:
    try:
        version = schema_version(manifest)
    except ValueError as exc:
        return [str(exc)]
    if version == 1:
        return _validate_v1(
            manifest,
            verify_hash=verify_hash,
            check_paths=check_paths,
            module_root=module_root,
        )
    return _validate_v2(
        manifest,
        registry=registry,
        verify_hash=verify_hash,
        check_paths=check_paths,
        module_root=module_root,
    )


def _validate_v1(
    manifest: dict[str, Any],
    *,
    verify_hash: bool,
    check_paths: bool,
    module_root: str | Path | None,
) -> list[str]:
    errors: list[str] = []
    for key in (
        "name",
        "workspace",
        "output_root",
        "dataset",
        "calibration",
        "evaluation",
        "algorithms",
    ):
        if key not in manifest:
            errors.append(f"missing top-level field: {key}")
    dataset = manifest.get("dataset", {})
    if not isinstance(dataset, dict):
        return errors + ["dataset must be an object"]
    for key in V1_REQUIRED_DATASET_KEYS:
        if dataset.get(key) in (None, ""):
            errors.append(f"dataset missing field: {key}")
    bag_dir = Path(str(dataset.get("bag_dir", "")))
    db3 = Path(str(dataset.get("db3", "")))
    if check_paths:
        if not bag_dir.is_dir():
            errors.append(f"bag_dir does not exist: {bag_dir}")
        elif not (bag_dir / "metadata.yaml").is_file():
            errors.append(f"bag_dir missing metadata.yaml: {bag_dir}")
        if not db3.is_file():
            errors.append(f"db3 does not exist: {db3}")
        workspace = Path(str(manifest.get("workspace", "")))
        if not workspace.is_dir():
            errors.append(f"workspace does not exist: {workspace}")
    algorithms = manifest.get("algorithms", {})
    if not isinstance(algorithms, dict):
        errors.append("algorithms must be an object")
    else:
        root = Path(module_root) if module_root else Path(__file__).resolve().parents[2]
        for name, config in algorithms.items():
            if not isinstance(config, dict):
                errors.append(f"algorithm {name} must be an object")
                continue
            runner = Path(str(config.get("runner", "")))
            if not runner.is_absolute():
                runner = root / runner
            if check_paths and not runner.is_file():
                errors.append(f"algorithm {name} runner does not exist: {runner}")
            if config.get("mode") not in ("odometry", "full_slam"):
                errors.append(f"algorithm {name} mode must be odometry or full_slam")
    calibration = manifest.get("calibration", {})
    if len(calibration.get("rotation_lidar_to_imu_row_major", [])) != 9:
        errors.append("calibration rotation must have 9 values")
    if len(calibration.get("translation_lidar_to_imu_m", [])) != 3:
        errors.append("calibration translation must have 3 values")
    if verify_hash and db3.is_file() and dataset.get("sha256"):
        actual = sha256_file(db3)
        if actual.lower() != str(dataset["sha256"]).lower():
            errors.append(f"db3 SHA-256 mismatch: actual={actual}")
    return errors


def _validate_v2(
    manifest: dict[str, Any],
    *,
    registry: Registry | None,
    verify_hash: bool,
    check_paths: bool,
    module_root: str | Path | None,
) -> list[str]:
    errors: list[str] = []
    for key in ("name", "workspace", "output_root", "dataset", "algorithms", "standardization"):
        if key not in manifest:
            errors.append(f"missing top-level field: {key}")
    if errors:
        return errors
    try:
        resolved = resolve_manifest(manifest, registry)
    except ValueError as exc:
        return [str(exc)]
    dataset = resolved["dataset"]
    algorithms = resolved["algorithms"]
    for algorithm_id, algorithm in algorithms.items():
        for modality in algorithm["required_modalities"]:
            if dataset.get("topics", {}).get(modality) in (None, ""):
                errors.append(
                    f"algorithm {algorithm_id} requires unavailable dataset modality: {modality}"
                )
    standardization = manifest.get("standardization", {})
    if not isinstance(standardization, dict):
        errors.append("standardization must be an object")
    else:
        for key in ("map_voxel_m", "near_range_m", "trajectory_time_tolerance_s"):
            try:
                value = float(standardization[key])
            except (KeyError, TypeError, ValueError):
                errors.append(f"standardization.{key} must be numeric")
                continue
            if value < 0 or (key == "map_voxel_m" and value <= 0):
                errors.append(f"standardization.{key} has invalid value: {value}")
    if check_paths:
        bag_dir = Path(str(dataset["bag_dir"])).expanduser()
        if not bag_dir.is_dir():
            errors.append(f"bag_dir does not exist: {bag_dir}")
        elif not (bag_dir / "metadata.yaml").is_file():
            errors.append(f"bag_dir missing metadata.yaml: {bag_dir}")
        workspace = Path(str(manifest["workspace"])).expanduser()
        if not workspace.is_dir():
            errors.append(f"workspace does not exist: {workspace}")
        root = Path(module_root) if module_root else Path(__file__).resolve().parents[2]
        for algorithm_id, algorithm in algorithms.items():
            runner = Path(algorithm["runner"]["adapter"])
            if not runner.is_absolute():
                runner = root / runner
            if not runner.is_file():
                errors.append(f"algorithm {algorithm_id} runner does not exist: {runner}")
    if verify_hash and dataset.get("sha256"):
        errors.append("schema-v2 hash verification requires an explicit sha256_target field")
    return errors
