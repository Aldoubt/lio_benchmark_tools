#!/usr/bin/env python3
"""Relative SE(3) motion primitives for ground-truth-free diagnostics.

This module is ROS-independent. It removes only each estimator's initial world
gauge and never fits one estimator trajectory to another.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence

import numpy as np

from benchmark_base.lib.calibration import RigidTransform, invert_transform
from benchmark_base.lib.trajectory import PoseSample, Trajectory, normalize_quaternion


TARGET_PHYSICAL_FRAME = "IMU_BODY"
SAMPLE_PERIOD_S = 0.1
SUSTAIN_SAMPLES = 3
TRANSLATION_THRESHOLDS_M = (0.05, 0.10, 0.20, 0.50)
ROTATION_THRESHOLDS_DEG = (1.0, 2.0, 5.0, 10.0)


@dataclass(frozen=True)
class SE3Pose:
    rotation: tuple[float, ...]
    translation: tuple[float, float, float]

    def __post_init__(self) -> None:
        rotation = tuple(float(value) for value in self.rotation)
        translation = tuple(float(value) for value in self.translation)
        if len(rotation) != 9:
            raise ValueError("SE3 rotation must contain 9 row-major values")
        if len(translation) != 3:
            raise ValueError("SE3 translation must contain 3 values")
        if not all(math.isfinite(value) for value in (*rotation, *translation)):
            raise ValueError("SE3 pose must contain only finite values")
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "translation", translation)


@dataclass(frozen=True)
class SustainedOnset:
    crossed: bool
    onset_relative_time_s: float | None
    onset_value: float | None
    onset_index: int | None


def _rotation_matrix(values: Iterable[float]) -> np.ndarray:
    matrix = np.asarray(tuple(values), dtype=np.float64)
    if matrix.size != 9:
        raise ValueError("rotation must contain 9 values")
    matrix = matrix.reshape(3, 3)
    if not np.isfinite(matrix).all():
        raise ValueError("rotation must be finite")
    return matrix


def _translation_vector(values: Iterable[float]) -> np.ndarray:
    vector = np.asarray(tuple(values), dtype=np.float64)
    if vector.shape != (3,) or not np.isfinite(vector).all():
        raise ValueError("translation must contain 3 finite values")
    return vector


def quaternion_to_rotation(
    qx: float, qy: float, qz: float, qw: float
) -> tuple[float, ...]:
    x, y, z, w = normalize_quaternion((qx, qy, qz, qw))
    matrix = np.asarray(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    return tuple(float(value) for value in matrix.reshape(-1))


def pose_from_sample(sample: PoseSample) -> SE3Pose:
    return SE3Pose(
        rotation=quaternion_to_rotation(sample.qx, sample.qy, sample.qz, sample.qw),
        translation=(sample.x_m, sample.y_m, sample.z_m),
    )


def pose_from_rigid_transform(transform: RigidTransform) -> SE3Pose:
    return SE3Pose(rotation=transform.rotation, translation=transform.translation)


def compose_pose(left: SE3Pose, right: SE3Pose) -> SE3Pose:
    left_r = _rotation_matrix(left.rotation)
    right_r = _rotation_matrix(right.rotation)
    left_t = _translation_vector(left.translation)
    right_t = _translation_vector(right.translation)
    rotation = left_r @ right_r
    translation = left_t + left_r @ right_t
    return SE3Pose(
        rotation=tuple(float(value) for value in rotation.reshape(-1)),
        translation=tuple(float(value) for value in translation),
    )


def invert_pose(pose: SE3Pose) -> SE3Pose:
    rotation = _rotation_matrix(pose.rotation)
    translation = _translation_vector(pose.translation)
    inverse_rotation = rotation.T
    inverse_translation = -(inverse_rotation @ translation)
    return SE3Pose(
        rotation=tuple(float(value) for value in inverse_rotation.reshape(-1)),
        translation=tuple(float(value) for value in inverse_translation),
    )


def relative_pose(origin: SE3Pose, current: SE3Pose) -> SE3Pose:
    """Return ``origin^-1 * current`` without any estimator-to-estimator fit."""
    return compose_pose(invert_pose(origin), current)


def normalize_pose_to_imu(
    pose: SE3Pose,
    tracked_frame_physical: str,
    canonical_lidar_to_imu: RigidTransform | None,
) -> SE3Pose:
    tracked = str(tracked_frame_physical).strip().upper()
    if tracked == "IMU_BODY":
        return pose
    if tracked != "LIDAR":
        raise ValueError(f"unsupported tracked physical frame for Relative SE(3): {tracked or '<missing>'}")
    if canonical_lidar_to_imu is None:
        raise ValueError("LiDAR-tracked trajectory requires canonical LiDAR-to-IMU calibration")
    # Canonical calibration is T_IL. A world LiDAR pose T_WL becomes a world
    # IMU pose by right-multiplying T_LI = inverse(T_IL).
    lidar_to_imu_inverse = invert_transform(canonical_lidar_to_imu)
    return compose_pose(pose, pose_from_rigid_transform(lidar_to_imu_inverse))


def common_evaluation_times(
    trajectories: Mapping[str, Trajectory],
    *,
    sample_period_s: float = SAMPLE_PERIOD_S,
) -> tuple[float, float, tuple[float, ...]]:
    if len(trajectories) < 2:
        raise ValueError("Relative SE(3) requires at least two trajectories")
    period = float(sample_period_s)
    if period <= 0.0 or not math.isfinite(period):
        raise ValueError("sample period must be finite and positive")
    start = max(trajectory.timestamps[0] for trajectory in trajectories.values())
    end = min(trajectory.timestamps[-1] for trajectory in trajectories.values())
    if end <= start:
        raise ValueError("eligible trajectories have no common time interval")
    count = int(math.floor((end - start) / period + 1e-12))
    times = [start + index * period for index in range(count + 1)]
    if end - times[-1] > 1e-9:
        times.append(end)
    else:
        times[-1] = end
    return start, end, tuple(times)


def rotation_geodesic_rad(rotation: Iterable[float] | np.ndarray) -> float:
    matrix = np.asarray(rotation, dtype=np.float64)
    if matrix.size != 9:
        raise ValueError("relative rotation must contain 9 values")
    matrix = matrix.reshape(3, 3)
    cosine = float((np.trace(matrix) - 1.0) * 0.5)
    return math.acos(max(-1.0, min(1.0, cosine)))


def sustained_onset(
    relative_times_s: Sequence[float],
    values: Sequence[float],
    *,
    threshold: float,
    sustain_samples: int = SUSTAIN_SAMPLES,
) -> SustainedOnset:
    times = tuple(float(value) for value in relative_times_s)
    metrics = tuple(float(value) for value in values)
    threshold_value = float(threshold)
    if len(times) != len(metrics):
        raise ValueError("onset times and values must have equal length")
    if sustain_samples <= 0:
        raise ValueError("sustain_samples must be positive")
    if not math.isfinite(threshold_value):
        raise ValueError("onset threshold must be finite")
    if any(not math.isfinite(value) for value in (*times, *metrics)):
        raise ValueError("onset inputs must be finite")
    consecutive = 0
    for index, value in enumerate(metrics):
        consecutive = consecutive + 1 if value >= threshold_value else 0
        if consecutive >= sustain_samples:
            onset_index = index - sustain_samples + 1
            return SustainedOnset(
                crossed=True,
                onset_relative_time_s=times[onset_index],
                onset_value=metrics[onset_index],
                onset_index=onset_index,
            )
    return SustainedOnset(False, None, None, None)
