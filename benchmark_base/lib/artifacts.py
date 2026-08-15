#!/usr/bin/env python3
"""Standardized benchmark artifact metadata and path helpers."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
from typing import Any


MAP_SOURCES = ("NATIVE", "UNIFIED_RECONSTRUCTION")
NATIVE_MAP_STATUSES = ("AVAILABLE", "NOT_PROVIDED", "FAILED")


@dataclass(frozen=True)
class MapArtifactPaths:
    root: Path
    native_dir: Path
    native_map: Path
    native_metadata: Path
    unified_dir: Path
    unified_map: Path
    unified_metadata: Path
    compat_unified_map: Path
    compat_unified_metadata: Path


def map_artifact_paths(run: str | Path, algorithm_id: str) -> MapArtifactPaths:
    root = Path(run) / "standardized" / "maps" / algorithm_id
    return MapArtifactPaths(
        root=root,
        native_dir=root / "native",
        native_map=root / "native" / "map.ply",
        native_metadata=root / "native" / "metadata.json",
        unified_dir=root / "unified",
        unified_map=root / "unified" / "map.ply",
        unified_metadata=root / "unified" / "metadata.json",
        compat_unified_map=root / "unified_map.ply",
        compat_unified_metadata=root / "map_metadata.json",
    )


def build_map_metadata(
    *,
    map_source: str,
    algorithm_id: str,
    dataset_id: str,
    trajectory_source: str,
    voxel_m: float,
    point_count: int,
    generation_command: str,
    generated_at: str,
    timestamp_matching: dict[str, Any] | None = None,
    native_source: str | None = None,
    trajectory_role: str = "ODOMETRY",
) -> dict[str, Any]:
    if map_source not in MAP_SOURCES:
        raise ValueError(f"invalid map_source: {map_source}")
    if voxel_m <= 0:
        raise ValueError("voxel_m must be > 0")
    if point_count < 0:
        raise ValueError("point_count must be >= 0")
    metadata: dict[str, Any] = {
        "schema": "lio_benchmark_map/v3",
        "map_source": map_source,
        "algorithm_id": algorithm_id,
        "dataset_id": dataset_id,
        "trajectory_source": trajectory_source,
        "trajectory_role": trajectory_role,
        "voxel_m": float(voxel_m),
        "point_count": int(point_count),
        "generation_command": generation_command,
        "generated_at": generated_at,
    }
    if timestamp_matching is not None:
        metadata["timestamp_matching"] = timestamp_matching
    if native_source is not None:
        metadata["native_source"] = native_source
    return metadata


def build_native_map_metadata(
    *,
    algorithm_id: str,
    dataset_id: str,
    status: str,
    source_output: str | None,
    source_role: str,
    generated_at: str,
    coordinate_frame: str | None = None,
    point_count: int | None = None,
    source_format: str | None = None,
) -> dict[str, Any]:
    if status not in NATIVE_MAP_STATUSES:
        raise ValueError(f"invalid native map status: {status}")
    if point_count is not None and point_count < 0:
        raise ValueError("point_count must be >= 0 when provided")
    if status == "AVAILABLE" and not source_output:
        raise ValueError("AVAILABLE native map requires source_output")
    return {
        "schema": "lio_benchmark_native_map/v1",
        "map_source": "NATIVE",
        "algorithm_id": algorithm_id,
        "dataset_id": dataset_id,
        "status": status,
        "source_output": source_output,
        "source_role": source_role,
        "coordinate_frame": coordinate_frame,
        "point_count": point_count,
        "source_format": source_format,
        "generated_at": generated_at,
    }


def ensure_relative_symlink(source: str | Path, link: str | Path) -> None:
    source = Path(source)
    link = Path(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    relative = os.path.relpath(source, start=link.parent)
    try:
        link.symlink_to(relative)
    except OSError:
        # Filesystems without symlink support remain usable at the cost of a copy.
        shutil.copy2(source, link)


def write_unified_map_metadata(paths: MapArtifactPaths, payload: dict[str, Any]) -> None:
    write_json(paths.unified_metadata, payload)
    write_json(paths.compat_unified_metadata, payload)


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_standardization_report(path: str | Path, algorithm_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = Path(path)
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"standardization report root must be object: {path}")
    else:
        loaded = {"schema": "lio_benchmark_standardization_report/v2", "algorithms": {}}
    algorithms = loaded.setdefault("algorithms", {})
    if not isinstance(algorithms, dict):
        raise ValueError("standardization report algorithms must be an object")
    algorithms[algorithm_id] = payload
    write_json(path, loaded)
    return loaded
