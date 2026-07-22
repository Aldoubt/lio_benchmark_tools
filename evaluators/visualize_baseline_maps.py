#!/usr/bin/env python3
"""Build baseline-aligned trajectory and map comparisons for a benchmark run."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
from scipy.spatial.transform import Rotation, Slerp


ALGORITHMS = (
    ("kiss_icp", "KISS-ICP", "#7f8c8d"),
    ("mola_lo", "MOLA-LO", "#9b59b6"),
    ("mola_lio", "MOLA-LIO", "#8e44ad"),
    ("fast_livo2", "FAST-LIVO2 baseline", "#e67e22"),
    ("point_lio", "Point-LIO", "#2980b9"),
    ("dlio", "DLIO", "#c0392b"),
    ("glim_odometry", "GLIM odometry", "#27ae60"),
    ("glim_full_slam", "GLIM full SLAM", "#16a085"),
    ("lio_sam_no_loop", "LIO-SAM no-loop", "#34495e"),
    ("lio_sam_loop", "LIO-SAM loop", "#2c3e50"),
)

MAIN_TOPICS = {
    "kiss_icp": "/kiss/odometry",
    "mola_lo": "/tf",
    "mola_lio": "/tf",
    "fast_livo2": "/aft_mapped_to_init",
    "point_lio": "/aft_mapped_to_init",
    "dlio": "/odom",
    "glim_odometry": "/glim_ros/odom",
    "glim_full_slam": "/glim_ros/odom_corrected",
    "lio_sam_no_loop": "/lio_sam/mapping/odometry",
    "lio_sam_loop": "/lio_sam/mapping/odometry",
}


def load_trajectory(path: Path) -> dict[str, np.ndarray]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if len(rows) < 2:
        raise ValueError(f"trajectory has fewer than two rows: {path}")
    data = {key: np.asarray([float(row[key]) for row in rows], dtype=np.float64) for key in ("timestamp_s", "x_m", "y_m", "z_m", "qx", "qy", "qz", "qw")}
    order = np.argsort(data["timestamp_s"], kind="stable")
    data = {key: value[order] for key, value in data.items()}
    _, unique = np.unique(data["timestamp_s"], return_index=True)
    unique = np.sort(unique)
    data = {key: value[unique] for key, value in data.items()}
    data["positions"] = np.column_stack((data["x_m"], data["y_m"], data["z_m"]))
    data["rotations"] = Rotation.from_quat(np.column_stack((data["qx"], data["qy"], data["qz"], data["qw"])))
    data["slerp"] = Slerp(data["timestamp_s"], data["rotations"])
    return data


def pose_at(trajectory: dict[str, np.ndarray], times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    positions = np.column_stack([np.interp(times, trajectory["timestamp_s"], trajectory["positions"][:, axis]) for axis in range(3)])
    rotations = trajectory["slerp"](times).as_matrix()
    return positions, rotations


def read_scans(bag: Path, topic: str, scan_step: int, point_step: int, stop_after_s: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    db_files = sorted(bag.glob("*.db3"))
    if len(db_files) != 1:
        raise ValueError(f"expected one sqlite3 bag file, found {len(db_files)} in {bag}")
    connection = sqlite3.connect(f"file:{db_files[0]}?mode=ro", uri=True)
    topic_row = connection.execute("SELECT id, type FROM topics WHERE name = ?", (topic,)).fetchone()
    if topic_row is None:
        connection.close()
        raise ValueError(f"bag missing LiDAR topic {topic}")
    topic_id, type_name = topic_row
    message_class = get_message(type_name)
    points, times, intensities = [], [], []
    frame_ids = [row[0] for row in connection.execute("SELECT id FROM messages WHERE topic_id = ? ORDER BY id", (topic_id,))]
    for message_id in frame_ids[::scan_step]:
        row = connection.execute("SELECT data FROM messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            continue
        message = deserialize_message(row[0], message_class)
        header_time = float(message.header.stamp.sec) + float(message.header.stamp.nanosec) * 1e-9
        if stop_after_s is not None and header_time > stop_after_s:
            break
        selected = message.points[::point_step]
        xyz = np.asarray([[point.x, point.y, point.z] for point in selected], dtype=np.float64)
        intensity = np.asarray([point.reflectivity for point in selected], dtype=np.float64)
        point_times = header_time + np.asarray([point.offset_time for point in selected], dtype=np.float64) * 1e-9
        valid = np.isfinite(xyz).all(axis=1) & np.isfinite(point_times) & (np.linalg.norm(xyz, axis=1) >= 0.5) & (np.linalg.norm(xyz, axis=1) <= 100.0)
        points.append(xyz[valid]); times.append(point_times[valid]); intensities.append(intensity[valid])
    connection.close()
    if not points:
        raise ValueError("no valid LiDAR scans found")
    return np.concatenate(points), np.concatenate(times), np.concatenate(intensities)


def initial_yaw_translation_alignment(reference: dict[str, np.ndarray], candidate: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray, dict]:
    start = max(reference["timestamp_s"][0], candidate["timestamp_s"][0])
    end = min(reference["timestamp_s"][-1], candidate["timestamp_s"][-1])
    if end <= start:
        raise ValueError("baseline and candidate have no common time window")
    times = np.linspace(start, end, min(500, max(2, int((end - start) * 10))))
    reference_positions, reference_rotations = pose_at(reference, np.asarray([start]))
    candidate_positions, candidate_rotations = pose_at(candidate, np.asarray([start]))
    reference_yaw = math.atan2(reference_rotations[0, 1, 0], reference_rotations[0, 0, 0])
    candidate_yaw = math.atan2(candidate_rotations[0, 1, 0], candidate_rotations[0, 0, 0])
    yaw = reference_yaw - candidate_yaw
    rotation_2d = np.array([[math.cos(yaw), -math.sin(yaw)], [math.sin(yaw), math.cos(yaw)]])
    rotation = np.eye(3)
    rotation[:2, :2] = rotation_2d
    translation = reference_positions[0] - (rotation @ candidate_positions[0])
    reference_positions, _ = pose_at(reference, times)
    candidate_positions, _ = pose_at(candidate, times)
    aligned = (rotation @ candidate_positions.T).T + translation
    errors = np.linalg.norm(aligned - reference_positions, axis=1)
    return rotation, translation, {
        "method": "initial_yaw_translation",
        "common_start_s": float(start),
        "common_end_s": float(end),
        "common_duration_s": float(end - start),
        "samples": int(len(times)),
        "rmse_m": float(np.sqrt(np.mean(errors**2))),
        "mean_m": float(np.mean(errors)),
        "p95_m": float(np.percentile(errors, 95)),
        "max_m": float(np.max(errors)),
    }


def voxel_downsample(cloud: np.ndarray, voxel: float) -> np.ndarray:
    keys = np.floor(cloud[:, :3] / voxel).astype(np.int64)
    _, retained = np.unique(keys, axis=0, return_index=True)
    return cloud[np.sort(retained)]


def reconstruct_map(points: np.ndarray, times: np.ndarray, intensities: np.ndarray, trajectory: dict[str, np.ndarray], alignment: tuple[np.ndarray, np.ndarray], extrinsic_rotation: np.ndarray, extrinsic_translation: np.ndarray, origin: np.ndarray, voxel: float) -> np.ndarray:
    start = max(float(times[0]), float(trajectory["timestamp_s"][0]))
    end = min(float(times[-1]), float(trajectory["timestamp_s"][-1]))
    mask = (times >= start) & (times <= end)
    selected_points, selected_times, selected_intensities = points[mask], times[mask], intensities[mask]
    positions, rotations = pose_at(trajectory, selected_times)
    lidar_in_body = (extrinsic_rotation @ selected_points.T).T + extrinsic_translation
    world = np.einsum("nij,nj->ni", rotations, lidar_in_body) + positions
    alignment_rotation, alignment_translation = alignment
    aligned = (alignment_rotation @ world.T).T + alignment_translation - origin
    return voxel_downsample(np.column_stack((aligned, selected_intensities)), voxel)


def write_ply(path: Path, cloud: np.ndarray) -> None:
    records = np.empty(len(cloud), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4")])
    for index, name in enumerate(records.dtype.names or ()):
        records[name] = cloud[:, index]
    header = "ply\nformat binary_little_endian 1.0\n" f"element vertex {len(records)}\n" "property float x\nproperty float y\nproperty float z\nproperty float intensity\nend_header\n"
    with path.open("wb") as stream:
        stream.write(header.encode("ascii"))
        records.tofile(stream)


def plot_cloud(path: Path, cloud: np.ndarray, title: str) -> None:
    shown = cloud[::max(1, len(cloud) // 180_000)]
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), constrained_layout=True)
    for axis, (first, second), labels in zip(axes, ((0, 1), (0, 2), (1, 2)), (("X", "Y"), ("X", "Z"), ("Y", "Z"))):
        axis.scatter(shown[:, first], shown[:, second], c=shown[:, 2], s=0.12, cmap="viridis", rasterized=True)
        axis.set(xlabel=f"{labels[0]} (m)", ylabel=f"{labels[1]} (m)"); axis.set_aspect("equal", adjustable="box"); axis.grid(alpha=0.2)
    fig.suptitle(title)
    fig.savefig(path, dpi=170); plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--scan-step", type=int, default=1)
    parser.add_argument("--point-step", type=int, default=20)
    parser.add_argument("--voxel", type=float, default=0.12)
    parser.add_argument("--algorithms", help="Comma-separated successful algorithm keys; default: successful outputs in run status")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.baseline != "fast_livo2":
        raise ValueError("this comparison is intentionally anchored to FAST-LIVO2 LIO")
    if min(args.scan_step, args.point_step) < 1 or args.voxel <= 0:
        raise ValueError("scan-step and point-step must be >= 1; voxel must be > 0")
    run = args.run.resolve()
    output = (args.output or run / "figures" / "fast_livo2_baseline_maps").resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    status = json.loads((run / "metadata" / "run_status.json").read_text(encoding="utf-8"))
    known = {algorithm: (label, color) for algorithm, label, color in ALGORITHMS}
    requested = ([item.strip() for item in args.algorithms.split(",") if item.strip()]
                 if args.algorithms else [algorithm for algorithm, entry in status["algorithms"].items()
                                          if entry.get("result", {}).get("status") == "SUCCESS"])
    unknown = sorted(set(requested) - set(known))
    if unknown:
        raise ValueError(f"unknown algorithms: {unknown}")
    if args.baseline not in requested:
        raise ValueError(f"baseline {args.baseline} is not a successful selected algorithm")
    selected = [(algorithm, known[algorithm][0], known[algorithm][1]) for algorithm in requested]
    trajectories = {algorithm: load_trajectory(run / "standardized" / "trajectories" / f"{algorithm}.csv") for algorithm, _, _ in selected}
    baseline = trajectories[args.baseline]
    alignments: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    comparisons: dict[str, dict] = {}
    for algorithm, _, _ in selected:
        if algorithm == args.baseline:
            alignments[algorithm] = (np.eye(3), np.zeros(3))
            comparisons[algorithm] = {"method": "baseline", "rmse_m": 0.0, "mean_m": 0.0, "p95_m": 0.0, "max_m": 0.0}
        else:
            rotation, translation, metrics = initial_yaw_translation_alignment(baseline, trajectories[algorithm])
            alignments[algorithm] = (rotation, translation)
            comparisons[algorithm] = metrics

    input_stop_time = max(float(trajectory["timestamp_s"][-1]) for trajectory in trajectories.values()) + 0.2
    points, times, intensities = read_scans(Path(manifest["dataset"]["bag_dir"]), manifest["dataset"]["lidar_topic"], args.scan_step, args.point_step, input_stop_time)
    calibration = manifest["calibration"]["lidar_to_imu"]
    extrinsic_rotation = np.asarray(calibration["rotation"], dtype=np.float64).reshape(3, 3)
    extrinsic_translation = np.asarray(calibration["translation"], dtype=np.float64)
    common_start = max(float(baseline["timestamp_s"][0]), *(float(trajectory["timestamp_s"][0]) for trajectory in trajectories.values()))
    origin, _ = pose_at(baseline, np.asarray([common_start]))
    origin = origin[0]
    maps: dict[str, np.ndarray] = {}
    metadata: dict[str, dict] = {}
    for algorithm, label, _ in selected:
        cloud = reconstruct_map(points, times, intensities, trajectories[algorithm], alignments[algorithm], extrinsic_rotation, extrinsic_translation, origin, args.voxel)
        maps[algorithm] = cloud
        write_ply(output / f"{algorithm}_map.ply", cloud)
        plot_cloud(output / f"{algorithm}_map_views.png", cloud, f"{label}, FAST-LIVO2 baseline frame")
        metadata[algorithm] = {"label": label, "map_points": int(len(cloud)), "extent_xyz_m": np.ptp(cloud[:, :3], axis=0).tolist()}

    fig, ax = plt.subplots(figsize=(11, 8), constrained_layout=True)
    for algorithm, label, color in selected:
        trajectory = trajectories[algorithm]
        start = max(float(baseline["timestamp_s"][0]), float(trajectory["timestamp_s"][0]))
        end = min(float(baseline["timestamp_s"][-1]), float(trajectory["timestamp_s"][-1]))
        sample_times = np.linspace(start, end, min(500, max(2, int((end - start) * 10))))
        positions, _ = pose_at(trajectory, sample_times)
        rotation, translation = alignments[algorithm]
        positions = (rotation @ positions.T).T + translation - origin
        ax.plot(positions[:, 0], positions[:, 1], label=label, color=color, linewidth=1.2)
    ax.set(xlabel="X relative to FAST-LIVO2 (m)", ylabel="Y relative to FAST-LIVO2 (m)", title="Trajectories aligned to FAST-LIVO2 LIO"); ax.axis("equal"); ax.grid(alpha=0.25); ax.legend(fontsize=8)
    fig.savefig(output / "trajectory_baseline_comparison.png", dpi=180); plt.close(fig)

    columns = min(5, max(1, len(selected)))
    rows = math.ceil(len(selected) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(4.5 * columns, 3.8 * rows), squeeze=False, constrained_layout=True)
    for axis, (algorithm, label, _) in zip(axes.flat, selected):
        cloud = maps[algorithm]
        shown = cloud[::max(1, len(cloud) // 120_000)]
        axis.scatter(shown[:, 0], shown[:, 1], c=shown[:, 2], s=0.1, cmap="viridis", rasterized=True)
        axis.set(title=label, xlabel="X (m)", ylabel="Y (m)"); axis.set_aspect("equal", adjustable="box"); axis.grid(alpha=0.15)
    for axis in axes.flat[len(selected):]:
        axis.set_visible(False)
    fig.suptitle("Maps in FAST-LIVO2 baseline frame")
    fig.savefig(output / "map_comparison_xy.png", dpi=180); plt.close(fig)

    output_metadata = {
        "baseline": args.baseline,
        "selected_algorithms": [algorithm for algorithm, _, _ in selected],
        "alignment": "initial_yaw_translation",
        "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
        "bag": manifest["dataset"]["bag_dir"],
        "lidar_topic": manifest["dataset"]["lidar_topic"],
        "scan_step": args.scan_step,
        "point_step": args.point_step,
        "voxel_m": args.voxel,
        "input_points_used": int(len(points)),
        "point_time_range_s": [float(times.min()), float(times.max())],
        "trajectory_comparison": comparisons,
        "maps": metadata,
    }
    (output / "visualization_metadata.json").write_text(json.dumps(output_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_lines = [
        "# FAST-LIVO2 Baseline Comparison",
        "",
        "Relative diagnostic only. Each algorithm is aligned at the common start with initial yaw and translation; no independent ground truth is available.",
        "",
        "| Algorithm | RMSE to FAST (m) | P95 (m) | Max (m) | Map points |",
        "|---|---:|---:|---:|---:|",
    ]
    for algorithm, label, _ in selected:
        comparison = comparisons[algorithm]
        report_lines.append(f"| {label} | {comparison['rmse_m']:.4f} | {comparison['p95_m']:.4f} | {comparison['max_m']:.4f} | {metadata[algorithm]['map_points']} |")
    (output / "baseline_comparison.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    (output / "README.md").write_text("# FAST-LIVO2 baseline map comparison\n\nAll maps use the same raw MID360 points, real point timestamps, the manifest LiDAR-to-IMU extrinsic, and an initial-yaw+translation alignment to the FAST-LIVO2 LIO trajectory. This is a relative diagnostic comparison without independent ground truth.\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "algorithms": len(selected), "input_points_used": int(len(points))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
