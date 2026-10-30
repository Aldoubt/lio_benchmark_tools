#!/usr/bin/env python3
"""只读分析 ROS 2 bag 中的 MID360 点云、IMU 与时间戳。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from timing_audit import audit_timestamps, nearest_header_offsets, series_stats


def stamp_seconds(message: Any) -> float:
    stamp = message.header.stamp
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def vector_stats(rows: list[tuple[float, float, float]]) -> dict[str, Any]:
    axes = list(zip(*rows))
    return {
        name: series_stats(list(axis))
        for name, axis in zip(("x", "y", "z"), axes)
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bag", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--gap-threshold-s", type=float, default=0.5)
    parser.add_argument("--offset-threshold-s", type=float, default=0.2)
    args = parser.parse_args()
    audit_timestamps([], [], gap_threshold_s=args.gap_threshold_s,
                     offset_threshold_s=args.offset_threshold_s)
    if not args.bag.is_dir():
        raise FileNotFoundError(f"rosbag2 目录不存在: {args.bag}")

    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else {}
    dataset = manifest.get("dataset", {})
    lidar_topic = dataset.get("lidar_topic", "/livox/lidar")
    imu_topic = dataset.get("imu_topic", "/livox/imu")
    imu_unit = dataset.get("imu_acceleration_unit", "UNRESOLVED")
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(args.bag), storage_id="sqlite3"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    type_map = {item.name: item.type for item in reader.get_all_topics_and_types()}
    message_types = {}
    unavailable_topics: dict[str, str] = {}
    for topic, type_name in type_map.items():
        try:
            message_types[topic] = get_message(type_name)
        except (ImportError, ModuleNotFoundError) as exc:
            # Bags may contain zero-count custom topics from an unavailable
            # driver package. They are irrelevant to the benchmark inputs.
            unavailable_topics[topic] = f"{type_name}: {exc}"
    if unavailable_topics:
        print("Skipping unavailable message types: " + "; ".join(f"{topic} ({detail})" for topic, detail in unavailable_topics.items()))
    recorded_times: dict[str, list[float]] = {topic: [] for topic in type_map}
    header_times: dict[str, list[float]] = {topic: [] for topic in type_map}
    paired_headers: dict[str, list[float | None]] = {topic: [] for topic in type_map}
    point_fields: dict[str, list[dict[str, Any]]] = {}
    frame_ids: dict[str, set[str]] = {topic: set() for topic in type_map}
    acceleration: list[tuple[float, float, float]] = []
    angular_velocity: list[tuple[float, float, float]] = []
    custom_time_ranges: list[float] = []
    custom_time_backtracks = 0
    custom_ring_counts: dict[int, int] = {}

    while reader.has_next():
        topic, raw, recorded_ns = reader.read_next()
        recorded_times[topic].append(recorded_ns * 1e-9)
        paired_headers[topic].append(None)
        if topic not in message_types:
            continue
        message = deserialize_message(raw, message_types[topic])
        if hasattr(message, "header"):
            header_times[topic].append(stamp_seconds(message))
            paired_headers[topic][-1] = header_times[topic][-1]
            frame_ids[topic].add(message.header.frame_id)
        if hasattr(message, "fields") and topic not in point_fields:
            point_fields[topic] = [
                {"name": field.name, "offset": field.offset, "datatype": field.datatype, "count": field.count}
                for field in message.fields
            ]
        if topic == imu_topic:
            acceleration.append((message.linear_acceleration.x, message.linear_acceleration.y, message.linear_acceleration.z))
            angular_velocity.append((message.angular_velocity.x, message.angular_velocity.y, message.angular_velocity.z))
        if topic == lidar_topic and hasattr(message, "points") and hasattr(message, "timebase"):
            offsets = [int(point.offset_time) for point in message.points]
            if offsets:
                custom_time_ranges.append((max(offsets) - min(offsets)) * 1e-9)
                custom_time_backtracks += sum(b < a for a, b in zip(offsets, offsets[1:]))
            for point in message.points:
                custom_ring_counts[int(point.line)] = custom_ring_counts.get(int(point.line), 0) + 1

    topics: dict[str, Any] = {}
    for topic in type_map:
        rec = recorded_times[topic]
        hdr = header_times[topic]
        rec_dt = [b - a for a, b in zip(rec, rec[1:])]
        hdr_dt = [b - a for a, b in zip(hdr, hdr[1:])]
        timing = audit_timestamps(rec, paired_headers[topic],
                                  gap_threshold_s=args.gap_threshold_s,
                                  offset_threshold_s=args.offset_threshold_s)
        topics[topic] = {
            "type": type_map[topic],
            "count": len(rec),
            "frame_ids": sorted(frame_ids[topic]),
            "recorded_first_s": rec[0] if rec else None,
            "recorded_last_s": rec[-1] if rec else None,
            "recorded_dt_s": series_stats(rec_dt),
            "recorded_time_reversals": sum(value <= 0.0 for value in rec_dt),
            "header_first_s": hdr[0] if hdr else None,
            "header_last_s": hdr[-1] if hdr else None,
            "header_dt_s": series_stats(hdr_dt),
            "header_time_reversals": sum(value <= 0.0 for value in hdr_dt),
            "record_minus_header_s": timing["record_minus_header_s"],
            "timing_audit": timing,
            "decode_status": "unavailable_type" if topic in unavailable_topics else "available",
            "point_fields": point_fields.get(topic),
        }

    accel_norm = [math.sqrt(x * x + y * y + z * z) for x, y, z in acceleration]
    gyro_norm = [math.sqrt(x * x + y * y + z * z) for x, y, z in angular_velocity]
    lidar_hdr = header_times.get(lidar_topic, [])
    imu_hdr = header_times.get(imu_topic, [])
    nearest = nearest_header_offsets(lidar_hdr, imu_hdr)

    result = {
        "bag": str(args.bag.resolve()),
        "topics": topics,
        "imu": {
            "note": "全数据集统计；不能假定全程静止，均值不等同于静态零偏。",
            "declared_acceleration_unit": imu_unit,
            "linear_acceleration": vector_stats(acceleration),
            "linear_acceleration_norm": series_stats(accel_norm),
            "angular_velocity_rad_s": vector_stats(angular_velocity),
            "angular_velocity_norm_rad_s": series_stats(gyro_norm),
        },
        "lidar_minus_nearest_imu_header_s": series_stats(nearest),
        "point_time_validation": {
            "field": dataset.get("point_time_field", "UNRESOLVED"),
            "datatype": dataset.get("point_time_datatype", "UNRESOLVED"),
            "unit": dataset.get("point_time_unit", "UNRESOLVED"),
            "semantics": dataset.get("point_time_semantics", "UNRESOLVED"),
            "frame_time_range_s": series_stats(custom_time_ranges),
            "input_order_time_backtracks": custom_time_backtracks,
            "line_counts": {str(key): value for key, value in sorted(custom_ring_counts.items())},
            "note": "Livox CustomMsg points can be interleaved by line; adapters sort by offset_time before emitting PointCloud2."
        },
        "limitations": [
            "record_minus_header_s 是跨时钟域时差观测，不是已证实的传输延迟。",
            "长间隔不证明丢包；旧 reversal 字段包括重复戳，严格回退与重复计数见 timing_audit。",
            "nearest-header 仅按时间数值关联；时钟重置后不保证同一采集时段。",
            "已有 odometry/TF 可作为系统历史输出参考，但不是独立真值，不能用于绝对精度。",
            "IMU 全程统计不能代替已识别静止区间的零偏和噪声估计。",
        ],
        "unavailable_message_types": unavailable_topics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
