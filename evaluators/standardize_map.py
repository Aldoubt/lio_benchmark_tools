#!/usr/bin/env python3
"""Reconstruct a unified comparison map from one bag and a timestamped trajectory.

Unlike the historical exploratory visualizer, this script never aligns scans to
trajectory samples by normalized array index. Every retained LiDAR scan is
matched against the standardized trajectory by timestamp and is rejected when
it cannot be matched within the configured tolerance.
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
from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.trajectory import Trajectory, TrajectoryMatchError  # noqa: E402


POINTFIELD_DTYPES = {
    1: "i1",
    2: "u1",
    3: "<i2",
    4: "<u2",
    5: "<i4",
    6: "<u4",
    7: "<f4",
    8: "<f8",
}


def pointcloud_dtype(msg: Any) -> np.dtype:
    if msg.is_bigendian:
        raise ValueError("big-endian PointCloud2 is not supported")
    names: list[str] = []
    formats: list[Any] = []
    offsets: list[int] = []
    for field in msg.fields:
        if field.datatype not in POINTFIELD_DTYPES:
            raise ValueError(f"unsupported PointField datatype {field.datatype} for {field.name}")
        names.append(field.name)
        base = np.dtype(POINTFIELD_DTYPES[field.datatype])
        formats.append(base if field.count == 1 else (base, (field.count,)))
        offsets.append(field.offset)
    return np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": msg.point_step})


def cloud_rows(msg: Any, point_step: int, near_range_m: float) -> np.ndarray:
    if hasattr(msg, "points") and hasattr(msg, "point_num"):
        points = msg.points[::point_step]
        if not points:
            return np.empty((0, 4), dtype=np.float32)
        xyz = np.asarray([(point.x, point.y, point.z) for point in points], dtype=np.float64)
        intensity = np.asarray([point.reflectivity for point in points], dtype=np.float64)
        valid = np.isfinite(xyz).all(axis=1) & np.isfinite(intensity)
        if near_range_m > 0:
            valid &= np.linalg.norm(xyz, axis=1) >= near_range_m
        return np.column_stack((xyz[valid], intensity[valid])).astype(np.float32)
    if msg.row_step != msg.point_step * msg.width:
        raise ValueError("PointCloud2 row padding is not supported by the unified map standardizer")
    dtype = pointcloud_dtype(msg)
    points = np.frombuffer(msg.data, dtype=dtype, count=msg.width * msg.height)[::point_step]
    for field in ("x", "y", "z"):
        if field not in points.dtype.names:
            raise ValueError(f"PointCloud2 missing required field: {field}")
    xyz = np.column_stack((points["x"], points["y"], points["z"])).astype(np.float64)
    intensity = (
        np.asarray(points["intensity"], dtype=np.float64)
        if "intensity" in (points.dtype.names or ()) and points["intensity"].ndim == 1
        else np.zeros(len(points), dtype=np.float64)
    )
    valid = np.isfinite(xyz).all(axis=1) & np.isfinite(intensity)
    if near_range_m > 0:
        valid &= np.linalg.norm(xyz, axis=1) >= near_range_m
    return np.column_stack((xyz[valid], intensity[valid])).astype(np.float32)


def point_time_to_seconds(value: float, unit: str) -> float:
    scales = {
        "s": 1.0,
        "sec": 1.0,
        "ms": 1e-3,
        "us": 1e-6,
        "ns": 1e-9,
        "ns_absolute": 1e-9,
        "us_absolute": 1e-6,
    }
    if unit not in scales:
        raise ValueError(f"unsupported point time unit: {unit}")
    return float(value) * scales[unit]


def scan_timestamp(msg: Any, bag_stamp_ns: int, point_time_field: str, point_time_unit: str) -> tuple[float, str]:
    stamp = getattr(getattr(msg, "header", None), "stamp", None)
    if stamp is not None and (stamp.sec != 0 or stamp.nanosec != 0):
        return stamp.sec + stamp.nanosec * 1e-9, "HEADER_STAMP"
    if point_time_field:
        if hasattr(msg, "points") and hasattr(msg, "timebase") and msg.points:
            first = getattr(msg.points[0], point_time_field, None)
            if first is not None:
                timebase = point_time_to_seconds(float(msg.timebase), "ns_absolute")
                offset_unit = "ns" if point_time_unit == "ns_relative_to_timebase" else point_time_unit
                offset = point_time_to_seconds(float(first), offset_unit)
                return timebase + offset, f"CUSTOM_POINT:{point_time_field}:{point_time_unit}"
        dtype = pointcloud_dtype(msg)
        if point_time_field in (dtype.names or ()) and msg.width * msg.height:
            values = np.frombuffer(msg.data, dtype=dtype, count=msg.width * msg.height)[point_time_field]
            values = np.asarray(values).reshape(-1)
            finite = values[np.isfinite(values)]
            if finite.size:
                return point_time_to_seconds(float(finite[0]), point_time_unit), f"POINT_FIELD:{point_time_field}:{point_time_unit}"
    return bag_stamp_ns * 1e-9, "ROSBAG_RECORD_TIME"


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
    records = np.empty(len(cloud), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4")])
    records["x"], records["y"], records["z"], records["intensity"] = cloud.T
    with path.open("wb") as stream:
        stream.write(header.encode("ascii"))
        records.tofile(stream)


def reconstruct(run: Path, algorithm_id: str) -> dict[str, Any]:
    manifest = load_json(run / "manifest.json")
    dataset = manifest["dataset"]
    standardization = manifest.get("standardization", manifest.get("evaluation", {}))
    scan_step = int(standardization.get("map_scan_step", 5))
    point_step = int(standardization.get("map_point_step", 8))
    voxel_m = float(standardization.get("map_voxel_m", 0.12))
    near_range_m = float(standardization.get("near_range_m", 0.5))
    tolerance_s = float(standardization.get("trajectory_time_tolerance_s", 0.05))
    if min(scan_step, point_step) < 1 or voxel_m <= 0 or tolerance_s < 0:
        raise ValueError("invalid standardization sampling/voxel/tolerance settings")
    trajectory_path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
    trajectory = Trajectory.from_csv(trajectory_path)
    bag = Path(dataset["bag_dir"]).expanduser()
    topic = dataset.get("topics", {}).get("lidar", dataset.get("lidar_topic"))
    point_time_field = dataset.get("timestamp", {}).get("point_time_field", dataset.get("point_time_field", "timestamp"))
    point_time_unit = dataset.get("timestamp", {}).get("point_time_unit", dataset.get("point_time_unit", "ns_absolute"))
    calibration = dataset.get("calibration", manifest.get("calibration", {}))
    r_li = np.asarray(calibration["rotation_lidar_to_imu_row_major"], dtype=np.float64).reshape(3, 3)
    t_li = np.asarray(calibration["translation_lidar_to_imu_m"], dtype=np.float64)

    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id="sqlite3"), rosbag2_py.ConverterOptions("cdr", "cdr"))
    types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    if topic not in types:
        raise ValueError(f"bag missing lidar topic {topic}; available={sorted(types)}")
    cls = get_message(types[topic])
    chunks: list[np.ndarray] = []
    scan_index = 0
    selected = 0
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
        if scan_index % scan_step:
            scan_index += 1
            continue
        selected += 1
        msg = deserialize_message(raw, cls)
        timestamp_s, timestamp_source = scan_timestamp(msg, bag_stamp_ns, point_time_field, point_time_unit)
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
            xyz_world = (r_wi @ xyz_imu.T).T + np.array([pose.x_m, pose.y_m, pose.z_m], dtype=np.float64)
            chunks.append(np.column_stack((xyz_world, scan[:, 3])).astype(np.float32))
        matched += 1
        interpolation_gaps.append(match.interpolation_gap_s)
        nearest_gaps.append(match.nearest_sample_gap_s)
        common_timestamps.append(timestamp_s)
        scan_index += 1

    if not chunks:
        raise ValueError("no matched LiDAR scans produced map points")
    cloud = voxel_downsample(np.concatenate(chunks, axis=0), voxel_m)
    output_dir = run / "standardized" / "maps" / algorithm_id
    output_dir.mkdir(parents=True, exist_ok=True)
    map_path = output_dir / "unified_map.ply"
    write_binary_ply(map_path, cloud)
    timing = {
        "selected_scan_count": selected,
        "matched_scan_count": matched,
        "unmatched_scan_count": unmatched,
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
    merge_standardization_report(run / "standardized" / "standardization_report.json", algorithm_id, metadata)
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
