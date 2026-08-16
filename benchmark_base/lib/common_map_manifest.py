#!/usr/bin/env python3
"""Build and validate the strict common LiDAR scan set for Unified Map comparison."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from benchmark_base.lib.manifest import load_json
from benchmark_base.lib.map_sampling import SelectedScan, read_scan_manifest, write_scan_manifest
from benchmark_base.lib.trajectory import Trajectory, TrajectoryMatchError


SCHEMA_VERSION = 1
POLICY = "STRICT_ALL_ALGORITHM_TRAJECTORY_INTERSECTION"
COMMON_NAME = "common_matched_scans.csv"
METADATA_NAME = "common_matched_metadata.json"


def sha256_file(path: Path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _paths(run: Path) -> tuple[Path, Path, Path]:
    sampling = run / "standardized" / "map_sampling"
    return (
        sampling / "selected_scans.csv",
        sampling / COMMON_NAME,
        sampling / METADATA_NAME,
    )


def _selected_algorithms(manifest: dict[str, Any]) -> list[str]:
    algorithms = manifest.get("algorithms")
    if not isinstance(algorithms, dict) or not algorithms:
        raise ValueError("frozen run algorithms must be a non-empty object")
    values = list(algorithms)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("frozen run contains an invalid algorithm id")
    return values


def _tolerance(manifest: dict[str, Any]) -> float:
    standardization = manifest.get("standardization", manifest.get("evaluation", {}))
    if not isinstance(standardization, dict) or "trajectory_time_tolerance_s" not in standardization:
        raise ValueError("frozen run requires trajectory_time_tolerance_s")
    try:
        tolerance = float(standardization["trajectory_time_tolerance_s"])
    except (TypeError, ValueError) as exc:
        raise ValueError("trajectory_time_tolerance_s must be finite and >= 0") from exc
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("trajectory_time_tolerance_s must be finite and >= 0")
    return tolerance


def _trajectory_records(
    run: Path,
    algorithm_ids: list[str],
) -> tuple[dict[str, Trajectory], dict[str, dict[str, Any]]]:
    trajectories: dict[str, Trajectory] = {}
    records: dict[str, dict[str, Any]] = {}
    for algorithm_id in algorithm_ids:
        path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
        if not path.is_file():
            raise ValueError(f"missing standardized trajectory for {algorithm_id}: {path}")
        try:
            trajectory = Trajectory.from_csv(path)
        except ValueError as exc:
            raise ValueError(f"invalid standardized trajectory for {algorithm_id}: {exc}") from exc
        trajectories[algorithm_id] = trajectory
        records[algorithm_id] = {
            "trajectory_path": str(path),
            "trajectory_sha256": sha256_file(path),
            "trajectory_sample_count": len(trajectory.samples),
        }
    return trajectories, records


def _current_input_fingerprints(
    run: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    source_path, _, _ = _paths(run)
    if not source_path.is_file():
        raise ValueError(f"missing selected scan manifest: {source_path}")
    selected_rows = read_scan_manifest(source_path)
    if not selected_rows:
        raise ValueError("selected scan manifest is empty")
    algorithm_ids = _selected_algorithms(manifest)
    _, trajectory_records = _trajectory_records(run, algorithm_ids)
    return {
        "policy": POLICY,
        "trajectory_time_tolerance_s": _tolerance(manifest),
        "selected_algorithms": algorithm_ids,
        "source_selected_manifest": str(source_path),
        "source_selected_manifest_sha256": sha256_file(source_path),
        "original_selected_scan_count": len(selected_rows),
        "trajectories": {
            algorithm_id: {
                "trajectory_path": trajectory_records[algorithm_id]["trajectory_path"],
                "trajectory_sha256": trajectory_records[algorithm_id]["trajectory_sha256"],
                "trajectory_sample_count": trajectory_records[algorithm_id]["trajectory_sample_count"],
            }
            for algorithm_id in algorithm_ids
        },
    }


def _raise_stale(reason: str) -> None:
    raise ValueError(f"strict common map evidence is stale or incomplete ({reason}); create a new run")


def validate_common_map_manifest(run: Path) -> dict[str, Any]:
    run = Path(run).resolve()
    source_path, common_path, metadata_path = _paths(run)
    if common_path.exists() != metadata_path.exists():
        _raise_stale("partial common artifacts")
    if not common_path.is_file() or not metadata_path.is_file():
        raise ValueError(
            "strict common map manifest is required; run: "
            f"lio-benchmark standardize common-map-manifest --run {run}"
        )

    manifest = load_json(run / "manifest.json")
    try:
        metadata = load_json(metadata_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _raise_stale(f"invalid metadata: {exc}")
    if not isinstance(metadata, dict):
        _raise_stale("metadata is not an object")
    if metadata.get("schema_version") != SCHEMA_VERSION:
        _raise_stale("schema version changed")

    current = _current_input_fingerprints(run, manifest)
    if metadata.get("policy") != current["policy"]:
        _raise_stale("policy changed")
    if metadata.get("trajectory_time_tolerance_s") != current["trajectory_time_tolerance_s"]:
        _raise_stale("trajectory tolerance changed")
    if metadata.get("selected_algorithms") != current["selected_algorithms"]:
        _raise_stale("selected algorithms changed")
    if metadata.get("source_selected_manifest") != current["source_selected_manifest"]:
        _raise_stale("selected manifest path changed")
    if metadata.get("source_selected_manifest_sha256") != current["source_selected_manifest_sha256"]:
        _raise_stale("selected manifest fingerprint changed")
    if metadata.get("original_selected_scan_count") != current["original_selected_scan_count"]:
        _raise_stale("selected scan count changed")

    algorithms_metadata = metadata.get("algorithms")
    if not isinstance(algorithms_metadata, dict):
        _raise_stale("algorithm metadata missing")
    for algorithm_id in current["selected_algorithms"]:
        recorded = algorithms_metadata.get(algorithm_id)
        expected = current["trajectories"][algorithm_id]
        if not isinstance(recorded, dict):
            _raise_stale(f"algorithm metadata missing for {algorithm_id}")
        for key in ("trajectory_path", "trajectory_sha256", "trajectory_sample_count"):
            if recorded.get(key) != expected[key]:
                _raise_stale(f"{algorithm_id} {key} changed")
        rejected = recorded.get("rejected_scan_indices")
        if not isinstance(rejected, list) or rejected != sorted(rejected):
            _raise_stale(f"{algorithm_id} rejected_scan_indices invalid")

    expected_common_sha = metadata.get("common_manifest_sha256")
    if not isinstance(expected_common_sha, str) or sha256_file(common_path) != expected_common_sha:
        _raise_stale("common manifest fingerprint changed")
    rows = read_scan_manifest(common_path)
    if metadata.get("common_matched_scan_count") != len(rows):
        _raise_stale("common scan count changed")
    source_rows = read_scan_manifest(source_path)
    source_indices = {row.scan_index for row in source_rows}
    common_indices = [row.scan_index for row in rows]
    if any(index not in source_indices for index in common_indices):
        _raise_stale("common manifest contains unknown scan index")
    return metadata


def build_common_map_manifest(run: Path) -> Path:
    run = Path(run).resolve()
    source_path, common_path, metadata_path = _paths(run)
    if common_path.exists() or metadata_path.exists():
        if not (common_path.exists() and metadata_path.exists()):
            _raise_stale("partial common artifacts")
        validate_common_map_manifest(run)
        return common_path

    manifest = load_json(run / "manifest.json")
    if not source_path.is_file():
        raise ValueError(f"missing selected scan manifest: {source_path}")
    selected_rows = read_scan_manifest(source_path)
    if not selected_rows:
        raise ValueError("selected scan manifest is empty")

    algorithm_ids = _selected_algorithms(manifest)
    tolerance = _tolerance(manifest)
    trajectories, trajectory_records = _trajectory_records(run, algorithm_ids)

    input_before = _current_input_fingerprints(run, manifest)
    matched_by_algorithm: dict[str, int] = {algorithm_id: 0 for algorithm_id in algorithm_ids}
    rejected_by_algorithm: dict[str, list[int]] = {algorithm_id: [] for algorithm_id in algorithm_ids}
    common_rows: list[SelectedScan] = []

    for row in selected_rows:
        common = True
        for algorithm_id in algorithm_ids:
            try:
                trajectories[algorithm_id].interpolate_pose(row.timestamp_s, tolerance)
            except TrajectoryMatchError:
                rejected_by_algorithm[algorithm_id].append(row.scan_index)
                common = False
            else:
                matched_by_algorithm[algorithm_id] += 1
        if common:
            common_rows.append(row)

    if not common_rows:
        raise ValueError("strict common map intersection is empty")

    input_after = _current_input_fingerprints(run, manifest)
    if input_before != input_after:
        _raise_stale("inputs changed while building common manifest")

    pending_common = common_path.with_name(common_path.name + ".pending")
    pending_metadata = metadata_path.with_name(metadata_path.name + ".pending")
    if pending_common.exists() or pending_metadata.exists():
        _raise_stale("pending artifact already exists")

    write_scan_manifest(pending_common, common_rows)
    common_sha = sha256_file(pending_common)
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "policy": POLICY,
        "selected_algorithms": algorithm_ids,
        "source_selected_manifest": str(source_path),
        "source_selected_manifest_sha256": input_before["source_selected_manifest_sha256"],
        "original_selected_scan_count": len(selected_rows),
        "common_matched_scan_count": len(common_rows),
        "trajectory_time_tolerance_s": tolerance,
        "common_manifest": str(common_path),
        "common_manifest_sha256": common_sha,
        "algorithms": {},
    }
    for algorithm_id in algorithm_ids:
        metadata["algorithms"][algorithm_id] = {
            **trajectory_records[algorithm_id],
            "individually_matched_scan_count": matched_by_algorithm[algorithm_id],
            "individually_rejected_scan_count": len(rejected_by_algorithm[algorithm_id]),
            "rejected_scan_indices": rejected_by_algorithm[algorithm_id],
        }

    if input_before != _current_input_fingerprints(run, manifest):
        pending_common.unlink(missing_ok=True)
        _raise_stale("inputs changed before common metadata write")

    pending_metadata.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(pending_common, common_path)
    os.replace(pending_metadata, metadata_path)
    validate_common_map_manifest(run)
    return common_path
