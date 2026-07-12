#!/usr/bin/env python3
"""统一使用 MID360 原始点云和各前端轨迹重建、可视化地图。"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
from scipy.spatial.transform import Rotation


@dataclass(frozen=True)
class Algorithm:
    key: str
    label: str
    csv_path: Path
    color: str


ALGORITHMS = (
    Algorithm("fast_livo2", "FAST-LIVO2", Path("date/output/fast_livo_trajectory.csv"), "#1f77b4"),
    Algorithm("point_lio", "Point-LIO", Path("date/output/point_lio/results/point_lio_trajectory.csv"), "#ff7f0e"),
    Algorithm("glim", "GLIM odometry", Path("date/output/glim_odometry/results/glim_odometry_trajectory.csv"), "#2ca02c"),
    Algorithm("dlio", "DLIO", Path("date/output/dlio_final/results/dlio_10hz_trajectory.csv"), "#d62728"),
)


def load_trajectory(path: Path) -> dict[str, np.ndarray]:
    if not path.is_file():
        raise FileNotFoundError(f"轨迹不存在: {path}")
    with path.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) < 2:
        raise ValueError(f"轨迹样本不足: {path}")
    keys = ("x_m", "y_m", "z_m", "roll_rad", "pitch_rad", "yaw_rad", "distance_m", "elapsed_s")
    data = {key: np.asarray([float(row[key]) for row in rows], dtype=np.float64) for key in keys}
    positions = np.column_stack((data["x_m"], data["y_m"], data["z_m"]))
    rotations = Rotation.from_euler("xyz", np.column_stack((data["roll_rad"], data["pitch_rad"], data["yaw_rad"]))).as_matrix()
    # Preserve the gravity-aligned Z axis. Removing full initial roll/pitch would
    # project a long horizontal path into Z; only remove initial yaw for display.
    yaw0_inv = Rotation.from_euler("z", -data["yaw_rad"][0]).as_matrix()
    data["positions"] = (yaw0_inv @ (positions - positions[0]).T).T
    data["rotations"] = np.einsum("ij,njk->nik", yaw0_inv, rotations)
    return data


def read_selected_scans(bag: Path, scan_step: int, point_step: int) -> list[np.ndarray]:
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id="sqlite3"), rosbag2_py.ConverterOptions("cdr", "cdr"))
    types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    topic = "/livox/lidar"
    if topic not in types:
        raise ValueError(f"bag 缺少 {topic}")
    cls = get_message(types[topic])
    scans: list[np.ndarray] = []
    scan_index = 0
    dtype = np.dtype({
        "names": ["x", "y", "z", "intensity", "tag", "line", "timestamp"],
        "formats": ["<f4", "<f4", "<f4", "<f4", "u1", "u1", "<f8"],
        "offsets": [0, 4, 8, 12, 16, 17, 18],
        "itemsize": 26,
    })
    while reader.has_next():
        name, raw, _ = reader.read_next()
        if name != topic:
            continue
        if scan_index % scan_step == 0:
            msg = deserialize_message(raw, cls)
            if msg.point_step != 26 or msg.is_bigendian:
                raise ValueError(f"不支持的 MID360 点布局: point_step={msg.point_step}, bigendian={msg.is_bigendian}")
            points = np.frombuffer(msg.data, dtype=dtype, count=msg.width * msg.height)[::point_step]
            xyz_i = np.column_stack((points["x"], points["y"], points["z"], points["intensity"])).astype(np.float32)
            valid = np.isfinite(xyz_i).all(axis=1) & (np.linalg.norm(xyz_i[:, :3], axis=1) >= 0.5)
            scans.append(xyz_i[valid])
        scan_index += 1
    if not scans:
        raise ValueError("没有读取到点云")
    return scans


def reconstruct_map(scans: list[np.ndarray], trajectory: dict[str, np.ndarray], voxel: float) -> np.ndarray:
    positions, rotations = trajectory["positions"], trajectory["rotations"]
    # All output poses describe the IMU/body. This is the calibrated LiDAR->IMU translation.
    lidar_to_body = np.array([0.011, 0.02329, -0.04412], dtype=np.float64)
    chunks: list[np.ndarray] = []
    for index, scan in enumerate(scans):
        pose_index = round(index * (len(positions) - 1) / max(1, len(scans) - 1))
        xyz_body = scan[:, :3].astype(np.float64) + lidar_to_body
        xyz_world = (rotations[pose_index] @ xyz_body.T).T + positions[pose_index]
        chunks.append(np.column_stack((xyz_world, scan[:, 3])).astype(np.float32))
    cloud = np.concatenate(chunks)
    voxel_keys = np.floor(cloud[:, :3] / voxel).astype(np.int32)
    _, retained = np.unique(voxel_keys, axis=0, return_index=True)
    return cloud[np.sort(retained)]


def write_binary_ply(path: Path, cloud: np.ndarray) -> None:
    header = ("ply\nformat binary_little_endian 1.0\n" f"element vertex {len(cloud)}\n"
              "property float x\nproperty float y\nproperty float z\nproperty float intensity\nend_header\n")
    records = np.empty(len(cloud), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4")])
    for index, name in enumerate(records.dtype.names or ()):
        records[name] = cloud[:, index]
    with path.open("wb") as stream:
        stream.write(header.encode("ascii"))
        records.tofile(stream)


def map_views(path: Path, cloud: np.ndarray, title: str) -> None:
    max_points = 250_000
    shown = cloud[::max(1, len(cloud) // max_points)]
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), constrained_layout=True)
    for axis, (a, b), labels in zip(axes, ((0, 1), (0, 2), (1, 2)), (("X", "Y"), ("X", "Z"), ("Y", "Z"))):
        axis.scatter(shown[:, a], shown[:, b], c=shown[:, 2], s=0.15, cmap="viridis", rasterized=True)
        axis.set(xlabel=f"{labels[0]} (m)", ylabel=f"{labels[1]} (m)")
        axis.set_aspect("equal", adjustable="box"); axis.grid(alpha=0.2)
    fig.suptitle(title)
    fig.savefig(path, dpi=180); plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bag", type=Path, default=Path("date/mid360_init_state2"))
    parser.add_argument("--output", type=Path, default=Path("date/output/frontend_visual_comparison"))
    parser.add_argument("--scan-step", type=int, default=5)
    parser.add_argument("--point-step", type=int, default=8)
    parser.add_argument("--voxel", type=float, default=0.12)
    args = parser.parse_args()
    if min(args.scan_step, args.point_step) < 1 or args.voxel <= 0:
        raise ValueError("采样步长必须 >= 1，体素必须 > 0")
    args.output.mkdir(parents=True, exist_ok=True)
    trajectories = {algorithm.key: load_trajectory(algorithm.csv_path) for algorithm in ALGORITHMS}
    scans = read_selected_scans(args.bag, args.scan_step, args.point_step)

    summaries: dict[str, Any] = {}
    maps: dict[str, np.ndarray] = {}
    for algorithm in ALGORITHMS:
        cloud = reconstruct_map(scans, trajectories[algorithm.key], args.voxel)
        maps[algorithm.key] = cloud
        write_binary_ply(args.output / f"{algorithm.key}_map.ply", cloud)
        map_views(args.output / f"{algorithm.key}_map_views.png", cloud, f"{algorithm.label} reconstructed MID360 map")
        extents = np.ptp(cloud[:, :3], axis=0)
        summaries[algorithm.key] = {"label": algorithm.label, "map_points": len(cloud), "extent_xyz_m": extents.tolist()}

    fig, axes = plt.subplots(1, 3, figsize=(18, 6), constrained_layout=True)
    for algorithm in ALGORITHMS:
        trajectory = trajectories[algorithm.key]
        pos = trajectory["positions"]
        distance = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(pos, axis=0), axis=1))))
        axes[0].plot(pos[:, 0], pos[:, 1], label=algorithm.label, color=algorithm.color, linewidth=1.2)
        axes[1].plot(distance, pos[:, 2], label=algorithm.label, color=algorithm.color, linewidth=1.0)
        axes[2].plot(np.linspace(0, 100, len(pos)), pos[:, 2], label=algorithm.label, color=algorithm.color, linewidth=1.0)
    axes[0].set(xlabel="X (m)", ylabel="Y (m)", title="Start-normalized XY trajectories"); axes[0].axis("equal")
    axes[1].set(xlabel="3D path distance (m)", ylabel="relative Z (m)", title="Z vs estimated distance")
    axes[2].set(xlabel="trajectory progress (%)", ylabel="relative Z (m)", title="Z vs normalized progress")
    for axis in axes: axis.grid(alpha=0.3); axis.legend()
    fig.savefig(args.output / "trajectory_comparison.png", dpi=180); plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(14, 12), constrained_layout=True)
    for axis, algorithm in zip(axes.flat, ALGORITHMS):
        cloud = maps[algorithm.key]
        shown = cloud[::max(1, len(cloud) // 180_000)]
        axis.scatter(shown[:, 0], shown[:, 1], c=shown[:, 2], s=0.12, cmap="viridis", rasterized=True)
        axis.set(title=algorithm.label, xlabel="X (m)", ylabel="Y (m)"); axis.set_aspect("equal", adjustable="box"); axis.grid(alpha=0.2)
    fig.suptitle("Frontend map comparison — identical MID360 samples and voxel size")
    fig.savefig(args.output / "map_comparison_xy.png", dpi=180); plt.close(fig)

    metadata = {"bag": str(args.bag), "scan_step": args.scan_step, "point_step": args.point_step,
                "voxel_m": args.voxel, "selected_scans": len(scans), "algorithms": summaries}
    (args.output / "visualization_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
