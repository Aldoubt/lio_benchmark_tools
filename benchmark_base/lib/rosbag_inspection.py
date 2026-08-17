#!/usr/bin/env python3
"""Shared read-only ROS 2 bag inspection used by analysis and dataset intake.

This is the only MID360 intake module that imports ROS bag/message runtime
packages. Pure evidence classification and dataset freezing remain ROS-free.
"""
from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message


def stamp_seconds(message: Any) -> float:
    stamp = message.header.stamp
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def series_stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "std": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "std": statistics.pstdev(values),
        "min": min(values),
        "max": max(values),
    }


def vector_stats(rows: list[tuple[float, float, float]]) -> dict[str, Any]:
    axes = list(zip(*rows))
    return {
        name: series_stats(list(axis))
        for name, axis in zip(("x", "y", "z"), axes)
    }


def inspect_ros2_bag(bag: Path) -> dict[str, Any]:
    """Read a ROS 2 bag without modifying it and return observed sensor evidence."""
    bag = bag.expanduser().resolve()
    if not bag.is_dir():
        raise FileNotFoundError(f"rosbag2 directory does not exist: {bag}")

    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id="sqlite3"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    type_map = {item.name: item.type for item in reader.get_all_topics_and_types()}
    message_types = {topic: get_message(type_name) for topic, type_name in type_map.items()}
    recorded_times: dict[str, list[float]] = {topic: [] for topic in type_map}
    header_times: dict[str, list[float]] = {topic: [] for topic in type_map}
    point_fields: dict[str, list[dict[str, Any]]] = {}
    frame_ids: dict[str, set[str]] = {topic: set() for topic in type_map}
    acceleration: list[tuple[float, float, float]] = []
    angular_velocity: list[tuple[float, float, float]] = []
    custom_samples: dict[str, int] = {}

    while reader.has_next():
        topic, raw, recorded_ns = reader.read_next()
        recorded_times[topic].append(recorded_ns * 1e-9)
        is_custom = "CustomMsg" in type_map[topic]
        sample_custom_layout = is_custom and custom_samples.get(topic, 0) < 3
        message = deserialize_message(raw, message_types[topic])
        if sample_custom_layout:
            custom_samples[topic] = custom_samples.get(topic, 0) + 1
        if hasattr(message, "header"):
            header_times[topic].append(stamp_seconds(message))
            frame_ids[topic].add(message.header.frame_id)
        if hasattr(message, "fields") and topic not in point_fields:
            point_fields[topic] = [
                {
                    "name": field.name,
                    "offset": field.offset,
                    "datatype": field.datatype,
                    "count": field.count,
                }
                for field in message.fields
            ]
        elif (
            hasattr(message, "points")
            and topic not in point_fields
            and sample_custom_layout
        ):
            point_fields[topic] = [
                {"name": name, "datatype": datatype}
                for name, datatype in (
                    ("timebase", "uint64 absolute ns"),
                    ("offset_time", "uint32 relative ns"),
                    ("x", "float32 m"),
                    ("y", "float32 m"),
                    ("z", "float32 m"),
                    ("reflectivity", "uint8"),
                    ("tag", "uint8"),
                    ("line", "uint8"),
                )
            ]
        if type_map[topic] == "sensor_msgs/msg/Imu":
            acceleration.append(
                (
                    message.linear_acceleration.x,
                    message.linear_acceleration.y,
                    message.linear_acceleration.z,
                )
            )
            angular_velocity.append(
                (
                    message.angular_velocity.x,
                    message.angular_velocity.y,
                    message.angular_velocity.z,
                )
            )

    topics: dict[str, Any] = {}
    for topic in type_map:
        rec = recorded_times[topic]
        hdr = header_times[topic]
        rec_dt = [b - a for a, b in zip(rec, rec[1:])]
        hdr_dt = [b - a for a, b in zip(hdr, hdr[1:])]
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
            "record_minus_header_s": series_stats([a - b for a, b in zip(rec, hdr)]),
            "point_fields": point_fields.get(topic),
        }

    accel_norm = [math.sqrt(x * x + y * y + z * z) for x, y, z in acceleration]
    gyro_norm = [math.sqrt(x * x + y * y + z * z) for x, y, z in angular_velocity]
    lidar_topics = [
        topic
        for topic, type_name in type_map.items()
        if "PointCloud2" in type_name or "CustomMsg" in type_name
    ]
    imu_topics = [
        topic for topic, type_name in type_map.items() if type_name == "sensor_msgs/msg/Imu"
    ]
    lidar_hdr = header_times.get(lidar_topics[0], []) if lidar_topics else []
    imu_hdr = header_times.get(imu_topics[0], []) if imu_topics else []
    nearest: list[float] = []
    index = 0
    for lidar_time in lidar_hdr:
        while (
            index + 1 < len(imu_hdr)
            and abs(imu_hdr[index + 1] - lidar_time) <= abs(imu_hdr[index] - lidar_time)
        ):
            index += 1
        if imu_hdr:
            nearest.append(lidar_time - imu_hdr[index])

    return {
        "bag": str(bag),
        "topics": topics,
        "imu": {
            "note": "Full-dataset statistics; do not treat motion data means as static bias evidence.",
            "linear_acceleration_m_s2": vector_stats(acceleration),
            "linear_acceleration_norm_m_s2": series_stats(accel_norm),
            "angular_velocity_rad_s": vector_stats(angular_velocity),
            "angular_velocity_norm_rad_s": series_stats(gyro_norm),
        },
        "lidar_minus_nearest_imu_header_s": series_stats(nearest),
        "limitations": [
            "Bag inspection alone does not provide ground-truth trajectory accuracy.",
            "Full-dataset IMU statistics do not replace a known stationary interval for bias/noise estimation.",
            "Livox CustomMsg header timestamps are audited across the full bag; point-layout evidence is sampled only as needed and does not prove a physical sensor model.",
            "Livox message layout does not prove a physical sensor model such as MID360.",
        ],
    }
