#!/usr/bin/env python3
"""Standardized benchmark artifact metadata helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MAP_SOURCES = ("NATIVE", "UNIFIED_RECONSTRUCTION")


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
) -> dict[str, Any]:
    if map_source not in MAP_SOURCES:
        raise ValueError(f"invalid map_source: {map_source}")
    if voxel_m <= 0:
        raise ValueError("voxel_m must be > 0")
    if point_count < 0:
        raise ValueError("point_count must be >= 0")
    metadata: dict[str, Any] = {
        "schema": "lio_benchmark_map/v2",
        "map_source": map_source,
        "algorithm_id": algorithm_id,
        "dataset_id": dataset_id,
        "trajectory_source": trajectory_source,
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
