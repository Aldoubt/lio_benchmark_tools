#!/usr/bin/env python3
"""Standard trajectory contract and timestamp interpolation utilities."""
from __future__ import annotations

import bisect
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


STANDARD_TRAJECTORY_COLUMNS = (
    "timestamp_s",
    "x_m",
    "y_m",
    "z_m",
    "qx",
    "qy",
    "qz",
    "qw",
    "roll_rad",
    "pitch_rad",
    "yaw_rad",
    "source_topic",
)


class TrajectoryError(ValueError):
    """Base error for trajectory contract violations."""


class TrajectoryMatchError(TrajectoryError):
    """Raised when a requested timestamp cannot be matched safely."""


@dataclass(frozen=True)
class PoseSample:
    timestamp_s: float
    x_m: float
    y_m: float
    z_m: float
    qx: float
    qy: float
    qz: float
    qw: float
    roll_rad: float
    pitch_rad: float
    yaw_rad: float
    source_topic: str = ""


@dataclass(frozen=True)
class PoseMatch:
    pose: PoseSample
    interpolation_gap_s: float
    nearest_sample_gap_s: float
    exact: bool


def normalize_quaternion(q: Iterable[float]) -> tuple[float, float, float, float]:
    values = tuple(float(value) for value in q)
    if len(values) != 4:
        raise TrajectoryError("quaternion must contain exactly four values")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-15:
        raise TrajectoryError("zero-length quaternion is invalid")
    return tuple(value / norm for value in values)  # type: ignore[return-value]


def quaternion_from_rpy(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    return normalize_quaternion(
        (
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
            cr * cp * cy + sr * sp * sy,
        )
    )


def rpy_from_quaternion(qx: float, qy: float, qz: float, qw: float) -> tuple[float, float, float]:
    qx, qy, qz, qw = normalize_quaternion((qx, qy, qz, qw))
    roll = math.atan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
    sin_pitch = 2.0 * (qw * qy - qz * qx)
    pitch = math.asin(max(-1.0, min(1.0, sin_pitch)))
    yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
    return roll, pitch, yaw


def quaternion_slerp(
    q0: Iterable[float], q1: Iterable[float], fraction: float
) -> tuple[float, float, float, float]:
    if not 0.0 <= fraction <= 1.0:
        raise TrajectoryError(f"SLERP fraction outside [0,1]: {fraction}")
    a = normalize_quaternion(q0)
    b = normalize_quaternion(q1)
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0.0:
        b = tuple(-value for value in b)
        dot = -dot
    dot = max(-1.0, min(1.0, dot))
    if dot > 0.9995:
        blended = tuple((1.0 - fraction) * x + fraction * y for x, y in zip(a, b))
        return normalize_quaternion(blended)
    theta_0 = math.acos(dot)
    sin_theta_0 = math.sin(theta_0)
    theta = theta_0 * fraction
    scale_a = math.sin(theta_0 - theta) / sin_theta_0
    scale_b = math.sin(theta) / sin_theta_0
    return normalize_quaternion(tuple(scale_a * x + scale_b * y for x, y in zip(a, b)))


class Trajectory:
    def __init__(self, samples: Iterable[PoseSample]) -> None:
        values = tuple(samples)
        if len(values) < 2:
            raise TrajectoryError("trajectory requires at least two samples")
        timestamps = tuple(sample.timestamp_s for sample in values)
        if any(not math.isfinite(value) for value in timestamps):
            raise TrajectoryError("trajectory contains non-finite timestamps")
        if any(b <= a for a, b in zip(timestamps, timestamps[1:])):
            raise TrajectoryError("trajectory timestamps must be strictly increasing")
        self.samples = values
        self.timestamps = timestamps

    @classmethod
    def from_csv(cls, path: str | Path) -> "Trajectory":
        path = Path(path)
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise TrajectoryError(f"trajectory CSV missing header: {path}")
            missing = [name for name in STANDARD_TRAJECTORY_COLUMNS if name not in reader.fieldnames]
            if missing:
                raise TrajectoryError(f"trajectory CSV missing columns: {', '.join(missing)}")
            samples = [
                PoseSample(
                    timestamp_s=float(row["timestamp_s"]),
                    x_m=float(row["x_m"]),
                    y_m=float(row["y_m"]),
                    z_m=float(row["z_m"]),
                    qx=float(row["qx"]),
                    qy=float(row["qy"]),
                    qz=float(row["qz"]),
                    qw=float(row["qw"]),
                    roll_rad=float(row["roll_rad"]),
                    pitch_rad=float(row["pitch_rad"]),
                    yaw_rad=float(row["yaw_rad"]),
                    source_topic=row.get("source_topic", ""),
                )
                for row in reader
            ]
        return cls(samples)

    def write_csv(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=STANDARD_TRAJECTORY_COLUMNS)
            writer.writeheader()
            for sample in self.samples:
                writer.writerow({name: getattr(sample, name) for name in STANDARD_TRAJECTORY_COLUMNS})

    def interpolate_pose(self, timestamp_s: float, tolerance_s: float) -> PoseMatch:
        if tolerance_s < 0.0:
            raise TrajectoryMatchError("tolerance_s must be non-negative")
        if timestamp_s < self.timestamps[0] or timestamp_s > self.timestamps[-1]:
            raise TrajectoryMatchError(
                f"timestamp {timestamp_s:.9f} outside trajectory range "
                f"[{self.timestamps[0]:.9f}, {self.timestamps[-1]:.9f}]"
            )
        index = bisect.bisect_left(self.timestamps, timestamp_s)
        if index < len(self.timestamps) and math.isclose(self.timestamps[index], timestamp_s, rel_tol=0.0, abs_tol=1e-12):
            return PoseMatch(self.samples[index], 0.0, 0.0, True)
        if index == 0 or index >= len(self.samples):
            raise TrajectoryMatchError("timestamp cannot be bracketed")
        left = self.samples[index - 1]
        right = self.samples[index]
        left_gap = timestamp_s - left.timestamp_s
        right_gap = right.timestamp_s - timestamp_s
        nearest_gap = min(left_gap, right_gap)
        if nearest_gap > tolerance_s:
            raise TrajectoryMatchError(
                f"nearest trajectory sample gap {nearest_gap:.6f}s exceeds tolerance {tolerance_s:.6f}s"
            )
        interval = right.timestamp_s - left.timestamp_s
        fraction = left_gap / interval
        q = quaternion_slerp(
            (left.qx, left.qy, left.qz, left.qw),
            (right.qx, right.qy, right.qz, right.qw),
            fraction,
        )
        roll, pitch, yaw = rpy_from_quaternion(*q)
        source_topic = left.source_topic if left.source_topic == right.source_topic else f"{left.source_topic}|{right.source_topic}"
        pose = PoseSample(
            timestamp_s=timestamp_s,
            x_m=left.x_m + fraction * (right.x_m - left.x_m),
            y_m=left.y_m + fraction * (right.y_m - left.y_m),
            z_m=left.z_m + fraction * (right.z_m - left.z_m),
            qx=q[0],
            qy=q[1],
            qz=q[2],
            qw=q[3],
            roll_rad=roll,
            pitch_rad=pitch,
            yaw_rad=yaw,
            source_topic=source_topic,
        )
        return PoseMatch(pose, interval, nearest_gap, False)
