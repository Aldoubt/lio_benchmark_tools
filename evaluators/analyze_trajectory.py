#!/usr/bin/env python3
"""从 ROS 2 Odometry bag 计算 Z 漂移指标并导出 CSV/JSON/PNG。"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message


def rpy(x: float, y: float, z: float, w: float) -> tuple[float, float, float]:
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return roll, pitch, yaw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bag", type=Path)
    parser.add_argument("--topic", default="/aft_mapped_to_init")
    parser.add_argument("--name", default="trajectory")
    parser.add_argument("--min-dt", type=float, default=0.0, help="Minimum sensor-time interval between retained odometry samples")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(args.bag), storage_id="sqlite3"), rosbag2_py.ConverterOptions("cdr", "cdr"))
    types = {x.name: x.type for x in reader.get_all_topics_and_types()}
    if args.topic not in types:
        raise ValueError(f"轨迹话题不存在: {args.topic}; 可用话题: {sorted(types)}")
    cls = get_message(types[args.topic])
    rows: list[dict[str, float]] = []
    while reader.has_next():
        topic, raw, _ = reader.read_next()
        if topic != args.topic:
            continue
        msg = deserialize_message(raw, cls)
        p, q, s = msg.pose.pose.position, msg.pose.pose.orientation, msg.header.stamp
        # Some odometry nodes publish one default-initialized sample before receiving sensor time.
        # Mixing epoch zero with real timestamps would corrupt duration without adding a real pose.
        if s.sec == 0 and s.nanosec == 0:
            continue
        stamp = s.sec + s.nanosec * 1e-9
        if rows and args.min_dt > 0.0 and stamp - rows[-1]["time_s"] < args.min_dt:
            continue
        roll, pitch, yaw = rpy(q.x, q.y, q.z, q.w)
        rows.append({"time_s": stamp, "x_m": p.x, "y_m": p.y, "z_m": p.z,
                     "roll_rad": roll, "pitch_rad": pitch, "yaw_rad": yaw})
    if len(rows) < 2:
        raise ValueError(f"轨迹样本不足: {len(rows)}")
    t0 = rows[0]["time_s"]
    distance = 0.0
    for index, row in enumerate(rows):
        row["elapsed_s"] = row["time_s"] - t0
        if index:
            previous = rows[index - 1]
            distance += math.sqrt(sum((row[k] - previous[k]) ** 2 for k in ("x_m", "y_m", "z_m")))
        row["distance_m"] = distance
    zs = [row["z_m"] for row in rows]
    dz = rows[-1]["z_m"] - rows[0]["z_m"]
    metrics = {
        "topic": args.topic, "samples": len(rows), "duration_s": rows[-1]["elapsed_s"],
        "path_length_3d_m": distance, "z_start_m": rows[0]["z_m"], "z_end_m": rows[-1]["z_m"],
        "z_min_m": min(zs), "z_max_m": max(zs), "z_range_m": max(zs) - min(zs),
        "metric_class": "diagnostic/conditional/non-ground-truth",
        "z_end_delta_m": dz,
        "z_end_delta_abs_m": abs(dz),
        "z_end_delta_cm_per_100m_estimated_path": abs(dz) / distance * 10000.0 if distance else None,
        "roll_range_deg": math.degrees(max(r["roll_rad"] for r in rows) - min(r["roll_rad"] for r in rows)),
        "pitch_range_deg": math.degrees(max(r["pitch_rad"] for r in rows) - min(r["pitch_rad"] for r in rows)),
        "warning": "首尾高度误差只有在起点和终点真实等高时才代表闭合误差；本 bag 无真值轨迹。",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / f"{args.name}_trajectory.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    metrics["algorithm"] = args.name
    (args.output_dir / f"{args.name}_trajectory_statistics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(3, 1, figsize=(10, 9), constrained_layout=True)
        axes[0].plot([r["elapsed_s"] for r in rows], zs); axes[0].set(xlabel="time (s)", ylabel="z (m)", title=f"{args.name} Z vs time"); axes[0].grid()
        axes[1].plot([r["distance_m"] for r in rows], zs); axes[1].set(xlabel="3D path distance (m)", ylabel="z (m)", title="Z vs distance"); axes[1].grid()
        axes[2].plot([r["elapsed_s"] for r in rows], [math.degrees(r["roll_rad"]) for r in rows], label="roll")
        axes[2].plot([r["elapsed_s"] for r in rows], [math.degrees(r["pitch_rad"]) for r in rows], label="pitch")
        axes[2].set(xlabel="time (s)", ylabel="angle (deg)", title="Roll / pitch"); axes[2].legend(); axes[2].grid()
        fig.savefig(args.output_dir / f"{args.name}_z_drift.png", dpi=150); plt.close(fig)
    except ImportError as exc:
        metrics["plot_error"] = str(exc)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
