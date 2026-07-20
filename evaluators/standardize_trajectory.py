#!/usr/bin/env python3
"""Standardize a ROS trajectory bag into canonical CSV, TUM and metadata."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


FIELDS = ("timestamp_s", "x_m", "y_m", "z_m", "qx", "qy", "qz", "qw", "roll_rad", "pitch_rad", "yaw_rad", "source_topic")


def quaternion_to_rpy(x: float, y: float, z: float, w: float) -> tuple[float, float, float]:
    norm = math.sqrt(x*x + y*y + z*z + w*w)
    if norm < 1e-12:
        raise ValueError("zero quaternion")
    x, y, z, w = x/norm, y/norm, z/norm, w/norm
    return (math.atan2(2*(w*x+y*z), 1-2*(x*x+y*y)), math.asin(max(-1.0, min(1.0, 2*(w*y-z*x)))), math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z)))


def normalize_samples(samples: list[dict], source_topic: str) -> tuple[list[dict], dict]:
    zero_times = sum(float(row["timestamp_s"]) == 0.0 for row in samples)
    original_backtracks = sum(float(b["timestamp_s"]) < float(a["timestamp_s"]) for a, b in zip(samples, samples[1:]))
    samples = [dict(row) for row in samples if float(row["timestamp_s"]) != 0.0]
    samples.sort(key=lambda row: float(row["timestamp_s"]))
    result: list[dict] = []
    duplicates = 0
    seen: set[float] = set()
    for row in samples:
        stamp = float(row["timestamp_s"])
        if stamp in seen:
            duplicates += 1
            continue
        seen.add(stamp)
        q = [float(row[key]) for key in ("qx", "qy", "qz", "qw")]
        norm = math.sqrt(sum(value*value for value in q))
        q = [value/norm for value in q]
        roll, pitch, yaw = quaternion_to_rpy(*q)
        result.append({"timestamp_s": stamp, "x_m": float(row["x_m"]), "y_m": float(row["y_m"]), "z_m": float(row["z_m"]), "qx": q[0], "qy": q[1], "qz": q[2], "qw": q[3], "roll_rad": roll, "pitch_rad": pitch, "yaw_rad": yaw, "source_topic": source_topic})
    metadata = {"input_samples": len(samples) + zero_times, "output_samples": len(result), "zero_timestamp_samples_removed": zero_times, "duplicate_timestamps_removed": duplicates, "input_time_backtracks": original_backtracks, "sorted_by_sensor_time": True, "source_topic": source_topic}
    return result, metadata


def write_outputs(rows: list[dict], metadata: dict, output_base: Path) -> None:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    with output_base.with_suffix(".csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
    with output_base.with_suffix(".tum").open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write("{timestamp_s:.9f} {x_m:.9f} {y_m:.9f} {z_m:.9f} {qx:.9f} {qy:.9f} {qz:.9f} {qw:.9f}\n".format(**row))
    output_base.with_suffix(".metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bag", type=Path); parser.add_argument("--topic", required=True); parser.add_argument("--output-base", type=Path, required=True)
    args = parser.parse_args()
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    reader = rosbag2_py.SequentialReader(); reader.open(rosbag2_py.StorageOptions(uri=str(args.bag), storage_id="sqlite3"), rosbag2_py.ConverterOptions("cdr", "cdr"))
    types = {x.name: x.type for x in reader.get_all_topics_and_types()}
    if args.topic not in types: raise ValueError(f"missing trajectory topic: {args.topic}")
    cls, samples = get_message(types[args.topic]), []
    while reader.has_next():
        topic, raw, _ = reader.read_next()
        if topic != args.topic: continue
        msg = deserialize_message(raw, cls)
        pose = msg.pose.pose if hasattr(msg.pose, "pose") else msg.pose
        stamp = msg.header.stamp
        samples.append({"timestamp_s": stamp.sec + stamp.nanosec*1e-9, "x_m": pose.position.x, "y_m": pose.position.y, "z_m": pose.position.z, "qx": pose.orientation.x, "qy": pose.orientation.y, "qz": pose.orientation.z, "qw": pose.orientation.w})
    rows, metadata = normalize_samples(samples, args.topic)
    if len(rows) < 2: raise ValueError(f"trajectory has only {len(rows)} valid samples")
    write_outputs(rows, metadata, args.output_base); print(json.dumps(metadata, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
