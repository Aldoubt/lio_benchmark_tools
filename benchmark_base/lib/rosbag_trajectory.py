#!/usr/bin/env python3
"""Shared ROS 2 bag reader for trajectory pose messages."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

from benchmark_base.lib.frame_audit import RawPoseObservation


SUPPORTED_POSE_MESSAGE_TYPES = {
    "nav_msgs/msg/Odometry",
    "geometry_msgs/msg/PoseStamped",
    "geometry_msgs/msg/PoseWithCovarianceStamped",
}


def normalize_topic(value: str) -> str:
    value = str(value).strip()
    if not value:
        return ""
    return "/" + value.lstrip("/")


def storage_identifier(bag: Path) -> str:
    metadata = bag / "metadata.yaml"
    if not metadata.is_file():
        raise ValueError(f"not a rosbag2 directory: {bag}")
    text = metadata.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^\s*storage_identifier:\s*([^\s#]+)", text, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    if any(bag.glob("*.db3")):
        return "sqlite3"
    if any(bag.glob("*.mcap")):
        return "mcap"
    raise ValueError(f"unable to determine rosbag2 storage identifier: {bag}")


def open_reader(bag: Path) -> rosbag2_py.SequentialReader:
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id=storage_identifier(bag)),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    return reader


def topic_map(bag: Path) -> dict[str, tuple[str, str]]:
    reader = open_reader(bag)
    return {
        normalize_topic(item.name): (item.name, item.type)
        for item in reader.get_all_topics_and_types()
    }


def find_bag_for_topic(raw_dir: Path, declared_topic: str) -> tuple[Path, str, str]:
    target = normalize_topic(declared_topic)
    if not target:
        raise ValueError("trajectory topic is not declared")
    matches: list[tuple[Path, str, str]] = []
    if raw_dir.is_dir():
        for metadata in sorted(raw_dir.rglob("metadata.yaml")):
            bag = metadata.parent
            try:
                topics = topic_map(bag)
            except Exception:
                continue
            if target in topics:
                actual_topic, message_type = topics[target]
                matches.append((bag, actual_topic, message_type))
    if not matches:
        raise ValueError(f"no raw rosbag under {raw_dir} contains trajectory topic {target}")
    if len(matches) > 1:
        options = ", ".join(str(item[0]) for item in matches)
        raise ValueError(f"multiple raw rosbags contain trajectory topic {target}: {options}")
    return matches[0]


def stamp_seconds(message: Any, recorded_ns: int) -> float:
    if hasattr(message, "header") and hasattr(message.header, "stamp"):
        stamp = message.header.stamp
        value = float(stamp.sec) + float(stamp.nanosec) * 1e-9
        if value != 0.0:
            return value
    return recorded_ns * 1e-9


def pose_fields(message: Any, message_type: str) -> tuple[str, str, Any]:
    if message_type == "nav_msgs/msg/Odometry":
        return str(message.header.frame_id), str(message.child_frame_id), message.pose.pose
    if message_type == "geometry_msgs/msg/PoseStamped":
        return str(message.header.frame_id), "", message.pose
    if message_type == "geometry_msgs/msg/PoseWithCovarianceStamped":
        return str(message.header.frame_id), "", message.pose.pose
    raise ValueError(f"unsupported trajectory message type: {message_type}")


def read_pose_observations(
    bag: Path,
    topic: str,
    message_type: str,
) -> tuple[RawPoseObservation, ...]:
    if message_type not in SUPPORTED_POSE_MESSAGE_TYPES:
        raise ValueError(f"unsupported trajectory message type: {message_type}")
    message_class = get_message(message_type)
    target = normalize_topic(topic)
    reader = open_reader(bag)
    rows: list[RawPoseObservation] = []
    while reader.has_next():
        current_topic, raw, recorded_ns = reader.read_next()
        if normalize_topic(current_topic) != target:
            continue
        message = deserialize_message(raw, message_class)
        parent, child, pose = pose_fields(message, message_type)
        rows.append(
            RawPoseObservation(
                timestamp_s=stamp_seconds(message, recorded_ns),
                parent_frame_id=parent,
                child_frame_id=child,
                x_m=float(pose.position.x),
                y_m=float(pose.position.y),
                z_m=float(pose.position.z),
                qx=float(pose.orientation.x),
                qy=float(pose.orientation.y),
                qz=float(pose.orientation.z),
                qw=float(pose.orientation.w),
            )
        )
    if not rows:
        raise ValueError(f"trajectory topic {target} has no readable pose messages in {bag}")
    return tuple(rows)
