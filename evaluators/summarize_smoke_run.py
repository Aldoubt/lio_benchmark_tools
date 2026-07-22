#!/usr/bin/env python3
"""Create comparable diagnostic metrics for one multi-algorithm smoke run."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

from standardize_trajectory import normalize_samples, write_outputs


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


def stamp(value) -> float:
    return float(value.sec) + float(value.nanosec) * 1e-9


def row_from_pose(header, pose, topic: str) -> dict:
    if hasattr(pose, "position"):
        position, orientation = pose.position, pose.orientation
    else:
        position, orientation = pose.translation, pose.rotation
    return {
        "timestamp_s": stamp(header.stamp),
        "x_m": position.x,
        "y_m": position.y,
        "z_m": position.z,
        "qx": orientation.x,
        "qy": orientation.y,
        "qz": orientation.z,
        "qw": orientation.w,
    }


def read_samples(bag: Path, algorithm: str) -> tuple[list[dict], str]:
    topic = MAIN_TOPICS[algorithm]
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id="sqlite3"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    if topic not in types:
        raise ValueError(f"{algorithm}: missing topic {topic}; available={sorted(types)}")
    message_class = get_message(types[topic])
    rows: list[dict] = []
    while reader.has_next():
        current_topic, raw, _ = reader.read_next()
        if current_topic != topic:
            continue
        message = deserialize_message(raw, message_class)
        if algorithm in {"mola_lo", "mola_lio"}:
            transforms = [
                transform
                for transform in message.transforms
                if transform.header.frame_id in {"map", "odom"}
                and transform.child_frame_id in {"livox_frame", "base_link"}
            ]
            if not transforms:
                continue
            transform = transforms[0]
            rows.append(row_from_pose(transform.header, transform.transform, topic))
        else:
            rows.append(row_from_pose(message.header, message.pose.pose, topic))
    return rows, topic


def parse_resource(path: Path) -> dict:
    result: dict[str, str | int] = {}
    patterns = {
        "max_rss_kb": r"Maximum resident set size \(kbytes\): (\d+)",
        "elapsed_wall": r"Elapsed \(wall clock\) time .*: (.+)",
    }
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            result[key] = int(match.group(1)) if key == "max_rss_kb" else match.group(1).strip()
    return result


def parse_resource_monitor(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    result = {
        "wall_time_s": data.get("wall_time_s"),
        "mean_cpu_percent": data.get("mean_cpu_percent"),
        "peak_cpu_percent": data.get("peak_cpu_percent"),
        "mean_rss_mib": (float(data["mean_rss_bytes"]) / (1024 * 1024)
                          if data.get("mean_rss_bytes") is not None else None),
        "peak_rss_mib": (float(data["peak_rss_bytes"]) / (1024 * 1024)
                         if data.get("peak_rss_bytes") is not None else None),
        "peak_threads": data.get("peak_threads"),
        "disk_write_mib": (float(data["disk_write_bytes"]) / (1024 * 1024)
                           if data.get("disk_write_bytes") is not None else None),
        "samples": data.get("samples"),
    }
    return {key: value for key, value in result.items() if value is not None}


def trajectory_metrics(rows: list[dict]) -> dict:
    positions = [(float(row["x_m"]), float(row["y_m"]), float(row["z_m"])) for row in rows]
    path_length = sum(
        math.dist(previous, current) for previous, current in zip(positions, positions[1:])
    )
    displacement = math.dist(positions[0], positions[-1])
    z_values = [position[2] for position in positions]
    return {
        "samples": len(rows),
        "duration_s": float(rows[-1]["timestamp_s"] - rows[0]["timestamp_s"]),
        "path_length_m": path_length,
        "endpoint_displacement_m": displacement,
        "z_range_m": max(z_values) - min(z_values),
        "z_end_delta_m": z_values[-1] - z_values[0],
    }


def raw_directory(run: Path, algorithm: str) -> Path:
    """Use a retry output recorded in run status when one exists."""
    status_path = run / "metadata" / "run_status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        output_dir = status.get("algorithms", {}).get(algorithm, {}).get("result", {}).get("output_dir")
        if output_dir and Path(output_dir).exists():
            return Path(output_dir)
    except (OSError, json.JSONDecodeError):
        pass
    return run / "raw" / algorithm


def summarize_algorithm(run: Path, algorithm: str, expected_duration_s: float | None = None) -> dict:
    raw = raw_directory(run, algorithm)
    result = json.loads((raw / "run_result.json").read_text(encoding="utf-8"))
    resource = parse_resource(raw / "resource_time.txt")
    resource_monitor = parse_resource_monitor(raw / "resource_monitor.json")
    output_base = run / "standardized" / "trajectories" / algorithm
    topic = MAIN_TOPICS[algorithm]
    try:
        rows, topic = read_samples(raw / "trajectory", algorithm)
        normalized, standardization = normalize_samples(rows, topic)
        if len(normalized) < 2:
            raise ValueError(f"trajectory has only {len(normalized)} valid samples")
        write_outputs(normalized, standardization, output_base)
        metrics = trajectory_metrics(normalized)
        trajectory_error = None
    except (FileNotFoundError, OSError, ValueError, KeyError, RuntimeError) as exc:
        standardization = {}
        metrics = {}
        trajectory_error = str(exc)
    input_validation_path = raw / "input_validation.json"
    input_validation = json.loads(input_validation_path.read_text(encoding="utf-8")) if input_validation_path.is_file() else {}
    health_flags: list[str] = []
    if metrics and expected_duration_s and metrics["duration_s"] < expected_duration_s * 0.98:
        health_flags.append("trajectory_short")
    return {
        "algorithm": algorithm,
        "status": result.get("status"),
        "topic": topic,
        "metric_class": "diagnostic/conditional/non-ground-truth",
        "standardized_output": str(output_base) if metrics else None,
        "standardization": standardization,
        "trajectory": metrics,
        "trajectory_error": trajectory_error,
        "health_flags": health_flags,
        "input": {
            key: input_validation.get(key)
            for key in ("frames", "input_points", "output_points", "dropped_ratio", "output_time_backtracks")
            if key in input_validation
        },
        "resource": resource,
        "resource_monitor": resource_monitor,
    }


def write_report(output: Path, rows: list[dict], title: str, description: str) -> None:
    lines = [
        f"# {title}",
        "",
        description,
        "",
        "| Algorithm | Status | Health | Samples | Duration (s) | Path (m) | End displacement (m) | Z range (m) | Input dropped | Time cleanup | Mean CPU % | Peak CPU % | Peak RSS (MiB) | Threads |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in rows:
        trajectory = item["trajectory"]
        standardization = item["standardization"]
        input_data = item["input"]
        resource = item["resource"]
        removed = (standardization.get("zero_timestamp_samples_removed", 0)
                   + standardization.get("duplicate_timestamps_removed", 0))
        dropped = input_data.get("dropped_ratio", "")
        trajectory = item.get("trajectory", {})
        monitor = item.get("resource_monitor", {})
        number = lambda value, digits=2: f"{float(value):.{digits}f}" if value is not None else ""
        lines.append(
            f"| {item['algorithm']} | {item['status']} | {'; '.join(item.get('health_flags', [])) or 'normal'} | {trajectory.get('samples', '')} | {number(trajectory.get('duration_s'))} | "
            f"{number(trajectory.get('path_length_m'))} | {number(trajectory.get('endpoint_displacement_m'))} | {number(trajectory.get('z_range_m'), 3)} | "
            f"{dropped} | {removed} | {number(monitor.get('mean_cpu_percent'))} | {number(monitor.get('peak_cpu_percent'))} | "
            f"{number(monitor.get('peak_rss_mib'), 1)} | {monitor.get('peak_threads', '')} |"
        )
    lines.extend(
        [
            "",
            "Health flags are diagnostic: trajectory_short means the canonical trajectory covers less than 98% of the manifest duration; path_divergence means the path is an order-of-magnitude outlier from the stable trajectory group. "
            "Resource values come from the monitored algorithm process tree. Parent-process values from GNU time are retained in the JSON but are not used for the peak RSS column. "
            "Samples, path length, endpoint displacement, and Z range are diagnostic health signals only. "
            "No absolute accuracy ranking is valid without independent ground truth.",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--name", default="round1_comparison")
    args = parser.parse_args()
    run = args.run.resolve()
    status = json.loads((run / "metadata" / "run_status.json").read_text(encoding="utf-8"))
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    expected_duration_s = float(manifest.get("dataset", {}).get("duration_s") or 0.0) or None
    algorithms = [algorithm for algorithm, entry in status["algorithms"].items() if entry.get("result")]
    rows = [summarize_algorithm(run, algorithm, expected_duration_s) for algorithm in algorithms]
    stable_paths = [item["trajectory"].get("path_length_m") for item in rows if item["trajectory"].get("path_length_m", 0.0) <= 1000.0]
    if stable_paths:
        nominal_path = sorted(stable_paths)[len(stable_paths) // 2]
        for item in rows:
            path_length = item["trajectory"].get("path_length_m")
            if path_length is not None and path_length > max(1000.0, nominal_path * 5.0):
                item["health_flags"].append("path_divergence")
    full_bag = all((item["result"].get("smoke_duration_s") is None and item["result"].get("duration_s") is None) for item in status["algorithms"].values() if item.get("result"))
    title = "Full Bag Algorithm Comparison" if full_bag else "Round 1 Smoke Comparison"
    description = (
        "This is a complete-bag, 1.0x diagnostic comparison without independent ground truth. "
        "It does not rank absolute accuracy and does not report ATE/RPE."
        if full_bag
        else "This is a manually controlled, 1.0x diagnostic comparison without independent ground truth. "
        "It does not rank absolute accuracy and does not report ATE/RPE."
    )
    output = run / "metrics" / f"{args.name}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"metric_class": "diagnostic/conditional/non-ground-truth", "algorithms": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = run / "reports" / f"{args.name}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    write_report(report, rows, title, description)
    print(json.dumps({"json": str(output), "report": str(report), "algorithms": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
