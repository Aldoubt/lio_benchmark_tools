#!/usr/bin/env python3
"""Reconstruct a unified comparison map from one bag and a timestamped trajectory.

Every Unified Map consumes the run-level frozen selected-scan manifest. LiDAR
scans are matched to standardized trajectories by timestamp and are rejected
when they cannot be matched within the configured tolerance.
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

from benchmark_base.lib.artifacts import build_map_metadata, merge_standardization_report, write_json  # noqa: E402
from benchmark_base.lib.cloud_contract import cloud_rows, scan_timestamp  # noqa: E402
from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.map_sampling import read_scan_manifest  # noqa: E402
from benchmark_base.lib.trajectory import Trajectory, TrajectoryMatchError  # noqa: E402
from evaluators.build_scan_manifest import build_manifest  # noqa: E402


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


def reconstruct(run: Path, algorithm_id: str) -> dict[str, Any]:
    manifest = load_json(run / "manifest.json")
    dataset = manifest["dataset"]
    standardization = manifest.get("standardization", manifest.get("evaluation", {}))
    point_step = int(standardization.get("map_point_step", 8))
    voxel_m = float(standardization.get("map_voxel_m", 0.12))
    near_range_m = float(standardization.get("near_range_m", 0.5))
    tolerance_s = float(standardization.get("trajectory_time_tolerance_s", 0.05))
    if point_step < 1 or voxel_m <= 0 or tolerance_s < 0:
        raise ValueError("invalid standardization point sampling/voxel/tolerance settings")

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
    r_li = np.asarray(calibration["rotation_lidar_to_imu_row_major"], dtype=np.float64).reshape(3, 3)
    t_li = np.asarray(calibration["translation_lidar_to_imu_m"], dtype=np.float64)

    sampling_path = build_manifest(run)
    selected_rows = read_scan_manifest(sampling_path)
    if not selected_rows:
        raise ValueError("selected scan manifest is empty")
    if any(row.lidar_topic != topic for row in selected_rows):
        raise ValueError("selected scan manifest LiDAR topic does not match frozen dataset")
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
    unmatched = 0
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
                "frozen selected scan timestamp no longer matches bag: "
                f"scan={scan_index} manifest={selected_row.timestamp_s:.9f} "
                f"observed={observed_timestamp_s:.9f} source={observed_source}"
            )
        timestamp_s = selected_row.timestamp_s
        timestamp_source = selected_row.timestamp_source
        stamp_sources[timestamp_source] = stamp_sources.get(timestamp_source, 0) + 1

        try:
            match = trajectory.interpolate_pose(timestamp_s, tolerance_s)
        except TrajectoryMatchError:
            unmatched += 1
            scan_index += 1
            continue

        scan = cloud_rows(msg, point_step=point_step, near_range_m=near_range_m)
        if scan.size:
            xyz_imu = (r_li @ scan[:, :3].astype(np.float64).T).T + t_li
            pose = match.pose
            r_wi = quaternion_matrix(pose.qx, pose.qy, pose.qz, pose.qw)
            xyz_world = (r_wi @ xyz_imu.T).T + np.array(
                [pose.x_m, pose.y_m, pose.z_m], dtype=np.float64
            )
            chunks.append(np.column_stack((xyz_world, scan[:, 3])).astype(np.float32))
        matched += 1
        interpolation_gaps.append(match.interpolation_gap_s)
        nearest_gaps.append(match.nearest_sample_gap_s)
        common_timestamps.append(timestamp_s)
        scan_index += 1

    if encountered_selected != len(selected_rows):
        raise ValueError(
            f"bag ended before all frozen selected scans were encountered: "
            f"encountered={encountered_selected} expected={len(selected_rows)}"
        )
    if not chunks:
        raise ValueError("no matched LiDAR scans produced map points")

    cloud = voxel_downsample(np.concatenate(chunks, axis=0), voxel_m)
    output_dir = run / "standardized" / "maps" / algorithm_id
    output_dir.mkdir(parents=True, exist_ok=True)
    map_path = output_dir / "unified_map.ply"
    write_binary_ply(map_path, cloud)

    selected = len(selected_rows)
    timing = {
        "selected_scan_manifest": str(sampling_path),
        "selected_scan_count": selected,
        "matched_scan_count": matched,
        "unmatched_scan_count": unmatched,
        "matched_scan_ratio": matched / selected if selected else 0.0,
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
        voxel_m=voxel_m,
        point_count=len(cloud),
        generation_command=" ".join(sys.argv),
        generated_at=dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        timestamp_matching=timing,
    )
    write_json(output_dir / "map_metadata.json", metadata)
    merge_standardization_report(
        run / "standardized" / "standardization_report.json", algorithm_id, metadata
    )
    return {"map": str(map_path), "metadata": metadata}


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
