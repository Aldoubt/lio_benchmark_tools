#!/usr/bin/env python3
"""Read-only trajectory frame-semantics audit helpers.

This module does not read ROS bags itself. Runtime ROS extraction lives in an
evaluator so the core contract remains unit-testable without ROS installed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable

from benchmark_base.lib.trajectory import PoseSample, normalize_quaternion, rpy_from_quaternion


@dataclass(frozen=True)
class RawPoseObservation:
    timestamp_s: float
    parent_frame_id: str
    child_frame_id: str
    x_m: float
    y_m: float
    z_m: float
    qx: float
    qy: float
    qz: float
    qw: float

    @property
    def quaternion(self) -> tuple[float, float, float, float]:
        return normalize_quaternion((self.qx, self.qy, self.qz, self.qw))


@dataclass(frozen=True)
class TrajectoryFrameAudit:
    algorithm_id: str
    status: str
    source_topic: str
    message_type: str
    raw_bag: str
    raw_message_count: int
    parent_frame_ids: tuple[str, ...]
    child_frame_ids: tuple[str, ...]
    parent_frame_change_count: int
    child_frame_change_count: int
    raw_first_timestamp_s: float
    raw_last_timestamp_s: float
    raw_first_x_m: float
    raw_first_y_m: float
    raw_first_z_m: float
    raw_first_qx: float
    raw_first_qy: float
    raw_first_qz: float
    raw_first_qw: float
    raw_first_roll_rad: float
    raw_first_pitch_rad: float
    raw_first_yaw_rad: float
    standardized_status: str
    standardized_first_timestamp_s: float | None
    standardized_first_x_m: float | None
    standardized_first_y_m: float | None
    standardized_first_z_m: float | None
    standardized_first_qx: float | None
    standardized_first_qy: float | None
    standardized_first_qz: float | None
    standardized_first_qw: float | None
    standardized_first_roll_rad: float | None
    standardized_first_pitch_rad: float | None
    standardized_first_yaw_rad: float | None
    raw_to_standardized_first_timestamp_delta_s: float | None
    raw_to_standardized_first_position_delta_m: float | None
    raw_to_standardized_first_orientation_delta_rad: float | None
    pose_semantics: str
    declared_pose_represents: str
    declared_world_frame_semantics: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parent_frame_ids"] = list(self.parent_frame_ids)
        payload["child_frame_ids"] = list(self.child_frame_ids)
        return payload


def quaternion_angle_difference(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    """Return the shortest SO(3) angle between two quaternions."""
    ql = normalize_quaternion(left)
    qr = normalize_quaternion(right)
    dot = abs(sum(a * b for a, b in zip(ql, qr)))
    dot = max(-1.0, min(1.0, dot))
    return 2.0 * math.acos(dot)


def _change_count(values: Iterable[str]) -> int:
    items = tuple(values)
    return sum(current != previous for previous, current in zip(items, items[1:]))


def _pose_semantics(message_type: str) -> str:
    if message_type == "nav_msgs/msg/Odometry":
        return "T_parent_child"
    if message_type in {
        "geometry_msgs/msg/PoseStamped",
        "geometry_msgs/msg/PoseWithCovarianceStamped",
    }:
        return "T_parent_pose"
    return "UNKNOWN"


def build_frame_audit(
    *,
    algorithm_id: str,
    source_topic: str,
    message_type: str,
    raw_bag: str,
    observations: tuple[RawPoseObservation, ...] | list[RawPoseObservation],
    standardized_first: PoseSample | None,
    declared_pose_represents: str = "UNKNOWN",
    declared_world_frame_semantics: str = "UNKNOWN",
) -> TrajectoryFrameAudit:
    values = tuple(observations)
    if not values:
        raise ValueError("trajectory frame audit requires at least one raw pose observation")

    first = values[0]
    last = values[-1]
    raw_q = first.quaternion
    raw_roll, raw_pitch, raw_yaw = rpy_from_quaternion(*raw_q)
    parent_frames = tuple(sorted(set(item.parent_frame_id for item in values)))
    child_frames = tuple(sorted(set(item.child_frame_id for item in values)))

    if standardized_first is None:
        std_status = "MISSING"
        std_values: tuple[float | None, ...] = (None,) * 10
        time_delta = position_delta = orientation_delta = None
    else:
        std_status = "AVAILABLE"
        std_q = normalize_quaternion(
            (
                standardized_first.qx,
                standardized_first.qy,
                standardized_first.qz,
                standardized_first.qw,
            )
        )
        std_values = (
            standardized_first.timestamp_s,
            standardized_first.x_m,
            standardized_first.y_m,
            standardized_first.z_m,
            std_q[0],
            std_q[1],
            std_q[2],
            std_q[3],
            standardized_first.roll_rad,
            standardized_first.pitch_rad,
        )
        time_delta = standardized_first.timestamp_s - first.timestamp_s
        position_delta = math.sqrt(
            (standardized_first.x_m - first.x_m) ** 2
            + (standardized_first.y_m - first.y_m) ** 2
            + (standardized_first.z_m - first.z_m) ** 2
        )
        orientation_delta = quaternion_angle_difference(raw_q, std_q)

    if standardized_first is None:
        std_timestamp = std_x = std_y = std_z = None
        std_qx = std_qy = std_qz = std_qw = None
        std_roll = std_pitch = std_yaw = None
    else:
        std_timestamp, std_x, std_y, std_z, std_qx, std_qy, std_qz, std_qw, std_roll, std_pitch = std_values
        std_yaw = standardized_first.yaw_rad

    return TrajectoryFrameAudit(
        algorithm_id=algorithm_id,
        status="AVAILABLE",
        source_topic=source_topic,
        message_type=message_type,
        raw_bag=raw_bag,
        raw_message_count=len(values),
        parent_frame_ids=parent_frames,
        child_frame_ids=child_frames,
        parent_frame_change_count=_change_count(item.parent_frame_id for item in values),
        child_frame_change_count=_change_count(item.child_frame_id for item in values),
        raw_first_timestamp_s=first.timestamp_s,
        raw_last_timestamp_s=last.timestamp_s,
        raw_first_x_m=first.x_m,
        raw_first_y_m=first.y_m,
        raw_first_z_m=first.z_m,
        raw_first_qx=raw_q[0],
        raw_first_qy=raw_q[1],
        raw_first_qz=raw_q[2],
        raw_first_qw=raw_q[3],
        raw_first_roll_rad=raw_roll,
        raw_first_pitch_rad=raw_pitch,
        raw_first_yaw_rad=raw_yaw,
        standardized_status=std_status,
        standardized_first_timestamp_s=std_timestamp,
        standardized_first_x_m=std_x,
        standardized_first_y_m=std_y,
        standardized_first_z_m=std_z,
        standardized_first_qx=std_qx,
        standardized_first_qy=std_qy,
        standardized_first_qz=std_qz,
        standardized_first_qw=std_qw,
        standardized_first_roll_rad=std_roll,
        standardized_first_pitch_rad=std_pitch,
        standardized_first_yaw_rad=std_yaw,
        raw_to_standardized_first_timestamp_delta_s=time_delta,
        raw_to_standardized_first_position_delta_m=position_delta,
        raw_to_standardized_first_orientation_delta_rad=orientation_delta,
        pose_semantics=_pose_semantics(message_type),
        declared_pose_represents=(declared_pose_represents or "UNKNOWN").strip().upper(),
        declared_world_frame_semantics=(declared_world_frame_semantics or "UNKNOWN").strip().upper(),
    )
