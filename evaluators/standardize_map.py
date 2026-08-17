#!/usr/bin/env python3
"""Reconstruct one strict-comparison Unified Map from frozen common LiDAR scans.

Every formal Unified Map consumes the same run-level strict common matched-scan
manifest. That manifest contains only original LiDAR scan indices that can be
matched by every selected algorithm trajectory under the frozen tolerance.
Map reconstruction re-validates the common evidence and every trajectory match;
it never silently falls back to independently matched scan populations.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.artifacts import (  # noqa: E402
    build_map_metadata,
    ensure_relative_symlink,
    map_artifact_paths,
    merge_standardization_report,
    write_unified_map_metadata,
)
from benchmark_base.lib.cloud_contract import cloud_rows, scan_timestamp  # noqa: E402
from benchmark_base.lib.common_map_manifest import (  # noqa: E402
    sha256_file,
    validate_common_map_manifest,
)
from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.map_frame_contract import lidar_points_in_tracked_frame  # noqa: E402
from benchmark_base.lib.map_sampling import read_scan_manifest  # noqa: E402
from benchmark_base.lib.registry import Registry  # noqa: E402
from benchmark_base.lib.trajectory import Trajectory, TrajectoryMatchError  # noqa: E402


def quaternion_matrix(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if n <= 1e-15:
        raise ValueError("zero quaternion")
    x, y, z, w = qx / n, qy / n, qz / n, qw / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def voxel_downsample(cloud: np.ndarray, voxel_m: float) -> np.ndarray:
    if cloud.size == 0:
        return cloud
    keys = np.floor(cloud[:, :3].astype(np.float64) / voxel_m).astype(np.int64)
    _, retained = np.unique(keys, axis=0, return_index=True)
    return cloud[np.sort(retained)]


def write_binary_ply(path: Path, cloud: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(cloud)}\n"
        "property float x\nproperty float y\nproperty float z\nproperty float intensity\nend_header\n"
    )
    records = np.empty(
        len(cloud),
        dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4")],
    )
    records["x"], records["y"], records["z"], records["intensity"] = cloud.T
    with path.open("wb") as stream:
        stream.write(header.encode("ascii"))
        records.tofile(stream)


def trajectory_contract(manifest: dict[str, Any], algorithm_id: str) -> tuple[dict[str, Any], str]:
    algorithm = manifest.get("algorithms", {}).get(algorithm_id, {})
    if isinstance(algorithm, dict):
        contract = algorithm.get("trajectory_contract")
        if isinstance(contract, dict) and contract.get("tracked_frame_physical"):
            return contract, "FROZEN_MANIFEST"
    current = Registry().load_algorithm(algorithm_id)
    contract = current.get("trajectory_contract")
    if not isinstance(contract, dict) or not contract.get("tracked_frame_physical"):
        raise ValueError(
            f"algorithm has no tracked-frame trajectory contract: {algorithm_id}; "
            "Unified Map reconstruction refuses to guess"
        )
    return contract, "CURRENT_REGISTRY_FALLBACK"


def reconstruct(run: Path, algorithm_id: str) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_json(run / "manifest.json")
    algorithms = manifest.get("algorithms", {})
    if not isinstance(algorithms, dict) or algorithm_id not in algorithms:
        raise ValueError(f"algorithm is not selected in frozen run: {algorithm_id}")

    dataset = manifest["dataset"]
    standardization = manifest.get("standardization", manifest.get("evaluation", {}))
    point_step = int(standardization.get("map_point_step", 8))
    voxel_m = float(standardization.get("map_voxel_m", 0.12))
    near_range_m = float(standardization.get("near_range_m", 0.5))
    if point_step < 1 or voxel_m <= 0:
        raise ValueError("invalid standardization point sampling/voxel settings")

    common_metadata = validate_common_map_manifest(run)
    common_path = run / "standardized" / "map_sampling" / "common_matched_scans.csv"
    tolerance_s = float(common_metadata["trajectory_time_tolerance_s"])
    if not math.isfinite(tolerance_s) or tolerance_s < 0:
        raise ValueError("strict common map metadata contains invalid trajectory tolerance")
    common_sha = sha256_file(common_path)
    if common_sha != common_metadata.get("common_manifest_sha256"):
        raise ValueError("strict common map manifest fingerprint changed after validation")

    contract, contract_source = trajectory_contract(manifest, algorithm_id)
    tracked_frame = str(contract["tracked_frame_physical"]).upper()

    trajectory_path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
    trajectory = Trajectory.from_csv(trajectory_path)
    bag = Path(dataset["bag_dir"]).expanduser()
    topic = dataset.get("topics", {}).get("lidar", dataset.get("lidar_topic"))
    point_time_field = dataset.get("timestamp", {}).get(
        "point_time_field", dataset.get("point_time_field", "timestamp")
    )
    point_time_unit = dataset.get("timestamp", {}).get(
        "point_time_unit", dataset.get("point_time_unit", "ns_absolute")
    )
    calibration = dataset.get("calibration", manifest.get("calibration", {}))

    selected_rows = read_scan_manifest(common_path)
    if not selected_rows:
        raise ValueError("strict common matched scan manifest is empty")
    if len(selected_rows) != int(common_metadata["common_matched_scan_count"]):
        raise ValueError("strict common map scan count disagrees with common metadata")
    if any(row.lidar_topic != topic for row in selected_rows):
        raise ValueError("strict common scan LiDAR topic does not match frozen dataset")
    selected_by_index = {row.scan_index: row for row in selected_rows}

    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id="sqlite3"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    if topic not in types:
        raise ValueError(f"bag missing lidar topic {topic}; available={sorted(types)}")
    cls = get_message(types[topic])

    chunks: list[np.ndarray] = []
    scan_index = 0
    encountered_selected = 0
    matched = 0
    interpolation_gaps: list[float] = []
    nearest_gaps: list[float] = []
    stamp_sources: dict[str, int] = {}
    common_timestamps: list[float] = []

    while reader.has_next():
        name, raw, bag_stamp_ns = reader.read_next()
        if name != topic:
            continue
        selected_row = selected_by_index.get(scan_index)
        if selected_row is None:
            scan_index += 1
            continue

        encountered_selected += 1
        msg = deserialize_message(raw, cls)
        observed_timestamp_s, observed_source = scan_timestamp(
            msg, bag_stamp_ns, point_time_field, point_time_unit
        )
        if abs(observed_timestamp_s - selected_row.timestamp_s) > 1e-6:
            raise ValueError(
                "strict common scan timestamp no longer matches bag: "
                f"scan={scan_index} manifest={selected_row.timestamp_s:.9f} "
                f"observed={observed_timestamp_s:.9f} source={observed_source}"
            )
        timestamp_s = selected_row.timestamp_s
        timestamp_source = selected_row.timestamp_source
        stamp_sources[timestamp_source] = stamp_sources.get(timestamp_source, 0) + 1

        try:
            match = trajectory.interpolate_pose(timestamp_s, tolerance_s)
        except TrajectoryMatchError as exc:
            raise ValueError(
                "COMMON INTERSECTION CONTRACT VIOLATION: "
                f"algorithm={algorithm_id} scan_index={scan_index} "
                f"timestamp_s={timestamp_s:.9f}"
            ) from exc

        scan = cloud_rows(msg, point_step=point_step, near_range_m=near_range_m)
        if scan.size:
            xyz_tracked = lidar_points_in_tracked_frame(
                scan[:, :3],
                tracked_frame_physical=tracked_frame,
                calibration=calibration,
            )
            pose = match.pose
            r_world_tracked = quaternion_matrix(pose.qx, pose.qy, pose.qz, pose.qw)
            xyz_world = (r_world_tracked @ xyz_tracked.T).T + np.array(
                [pose.x_m, pose.y_m, pose.z_m], dtype=np.float64
            )
            chunks.append(np.column_stack((xyz_world, scan[:, 3])).astype(np.float32))
        matched += 1
        interpolation_gaps.append(match.interpolation_gap_s)
        nearest_gaps.append(match.nearest_sample_gap_s)
        common_timestamps.append(timestamp_s)
        scan_index += 1

    selected = len(selected_rows)
    if encountered_selected != selected:
        raise ValueError(
            "bag ended before all strict common scans were encountered: "
            f"encountered={encountered_selected} expected={selected}"
        )
    if matched != selected or encountered_selected != selected:
        raise ValueError(
            "COMMON INTERSECTION CONTRACT VIOLATION: "
            f"algorithm={algorithm_id} selected={selected} matched={matched} "
            f"encountered={encountered_selected}"
        )
    if not chunks:
        raise ValueError("strict common scans produced no Unified Map points")

    cloud = voxel_downsample(np.concatenate(chunks, axis=0), voxel_m)
    paths = map_artifact_paths(run, algorithm_id)
    paths.unified_dir.mkdir(parents=True, exist_ok=True)
    write_binary_ply(paths.unified_map, cloud)
    ensure_relative_symlink(paths.unified_map, paths.compat_unified_map)

    timing = {
        "selected_scan_manifest": str(common_path),
        "selected_scan_count": selected,
        "matched_scan_count": matched,
        "unmatched_scan_count": 0,
        "matched_scan_ratio": 1.0,
        "max_interpolation_gap_s": max(interpolation_gaps, default=None),
        "median_interpolation_gap_s": float(np.median(interpolation_gaps)) if interpolation_gaps else None,
        "max_nearest_sample_gap_s": max(nearest_gaps, default=None),
        "first_common_timestamp_s": min(common_timestamps, default=None),
        "last_common_timestamp_s": max(common_timestamps, default=None),
        "timestamp_sources": stamp_sources,
        "trajectory_time_tolerance_s": tolerance_s,
    }
    metadata = build_map_metadata(
        map_source="UNIFIED_RECONSTRUCTION",
        algorithm_id=algorithm_id,
        dataset_id=dataset.get("dataset_id", "legacy_v1_dataset"),
        trajectory_source=str(trajectory_path),
        trajectory_role="ODOMETRY",
        voxel_m=voxel_m,
        point_count=len(cloud),
        generation_command=" ".join(sys.argv),
        generated_at=dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        timestamp_matching=timing,
    )
    metadata["scan_set_policy"] = "STRICT_COMMON_INTERSECTION"
    metadata["common_manifest"] = str(common_path)
    metadata["common_manifest_sha256"] = common_sha
    metadata["tracked_frame_physical"] = tracked_frame
    metadata["trajectory_contract_source"] = contract_source
    metadata["scan_frame_transform"] = (
        "IDENTITY_LIDAR_TO_LIDAR" if tracked_frame == "LIDAR" else "CANONICAL_LIDAR_TO_IMU"
    )
    metadata["world_gauge"] = contract.get("world_gauge", "UNKNOWN")
    write_unified_map_metadata(paths, metadata)
    merge_standardization_report(
        run / "standardized" / "standardization_report.json", algorithm_id, metadata
    )
    return {"map": str(paths.unified_map), "compat_map": str(paths.compat_unified_map), "metadata": metadata}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithm", required=True)
    args = parser.parse_args()
    result = reconstruct(args.run.resolve(), args.algorithm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
