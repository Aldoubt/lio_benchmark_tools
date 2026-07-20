"""Small, dependency-light SE(3) utilities used by evaluation and map building."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np


def normalized_quaternion(q: Sequence[float]) -> np.ndarray:
    value = np.asarray(q, dtype=float)
    norm = float(np.linalg.norm(value))
    if value.shape != (4,) or norm < 1e-12:
        raise ValueError("四元数必须是非零的 4 元向量 [x,y,z,w]")
    return value / norm


def slerp(q0: Sequence[float], q1: Sequence[float], fraction: float) -> np.ndarray:
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("插值比例必须位于 [0,1]")
    a, b = normalized_quaternion(q0), normalized_quaternion(q1)
    dot = float(np.dot(a, b))
    if dot < 0.0:
        b, dot = -b, -dot
    dot = max(-1.0, min(1.0, dot))
    if dot > 0.9995:
        return normalized_quaternion(a + fraction * (b - a))
    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    return (math.sin((1.0 - fraction) * theta) / sin_theta) * a + (math.sin(fraction * theta) / sin_theta) * b


def quaternion_matrix(q: Sequence[float]) -> np.ndarray:
    x, y, z, w = normalized_quaternion(q)
    return np.array([
        [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)],
        [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)],
        [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)],
    ])


@dataclass(frozen=True)
class Pose:
    timestamp_s: float
    translation: np.ndarray
    quaternion_xyzw: np.ndarray


def interpolate_pose(before: Pose, after: Pose, timestamp_s: float, max_gap_s: float) -> Pose:
    if after.timestamp_s <= before.timestamp_s:
        raise ValueError("轨迹时间必须严格递增")
    if timestamp_s < before.timestamp_s or timestamp_s > after.timestamp_s:
        raise ValueError("查询时间超出位姿区间")
    gap = after.timestamp_s - before.timestamp_s
    if gap > max_gap_s:
        raise ValueError(f"位姿时间缺口 {gap:.6f}s 超过阈值 {max_gap_s:.6f}s")
    ratio = (timestamp_s - before.timestamp_s) / gap
    return Pose(timestamp_s, before.translation + ratio * (after.translation - before.translation), slerp(before.quaternion_xyzw, after.quaternion_xyzw, ratio))


def transform_points(points_lidar: np.ndarray, world_from_base: Pose, rotation_base_lidar: Sequence[float], translation_base_lidar: Sequence[float]) -> np.ndarray:
    points = np.asarray(points_lidar, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("点云必须是 N×3")
    r_bl = np.asarray(rotation_base_lidar, dtype=float).reshape(3, 3)
    t_bl = np.asarray(translation_base_lidar, dtype=float).reshape(3)
    r_wb = quaternion_matrix(world_from_base.quaternion_xyzw)
    return (r_wb @ ((r_bl @ points.T).T + t_bl).T).T + world_from_base.translation


def invert_transform(rotation: Sequence[float], translation: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    r = np.asarray(rotation, dtype=float).reshape(3, 3)
    t = np.asarray(translation, dtype=float).reshape(3)
    return r.T, -(r.T @ t)
