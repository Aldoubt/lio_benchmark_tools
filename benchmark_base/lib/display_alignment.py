#!/usr/bin/env python3
"""Display-only alignment transforms for cross-algorithm visualization.

These transforms are derived visualization products. They must never be used to
rewrite standardized trajectories, Native Maps, Unified Maps, or scientific
metrics.
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from benchmark_base.lib.trajectory import PoseSample, normalize_quaternion


DISPLAY_ALIGNMENT_MODES = frozenset({"NONE", "START_XY_YAW"})


def compute_display_alignment(initial_pose: PoseSample, mode: str) -> np.ndarray:
    mode = mode.strip().upper()
    if mode not in DISPLAY_ALIGNMENT_MODES:
        raise ValueError(f"unsupported display alignment mode: {mode}")
    if mode == "NONE":
        return np.eye(4, dtype=np.float64)

    angle = -float(initial_pose.yaw_rad)
    c = math.cos(angle)
    s = math.sin(angle)
    matrix = np.eye(4, dtype=np.float64)
    matrix[0, 0] = c
    matrix[0, 1] = -s
    matrix[1, 0] = s
    matrix[1, 1] = c
    # Translate in the rotated display frame so start X/Y becomes zero.
    matrix[0, 3] = -(c * initial_pose.x_m - s * initial_pose.y_m)
    matrix[1, 3] = -(s * initial_pose.x_m + c * initial_pose.y_m)
    # Z, roll and pitch are intentionally not normalized away.
    return matrix


def _validate_matrix(matrix: np.ndarray) -> np.ndarray:
    value = np.asarray(matrix, dtype=np.float64)
    if value.shape != (4, 4) or not np.isfinite(value).all():
        raise ValueError("display transform must be a finite 4x4 matrix")
    return value


def apply_display_transform_xyz(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    transform = _validate_matrix(matrix)
    xyz = np.asarray(points, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("points must have shape Nx3")
    # Use a new array so visualization cannot mutate scientific artifacts in memory.
    homogeneous = np.column_stack((xyz.copy(), np.ones(len(xyz), dtype=np.float64)))
    return (transform @ homogeneous.T).T[:, :3]


def _quaternion_multiply(
    left: Iterable[float], right: Iterable[float]
) -> tuple[float, float, float, float]:
    lx, ly, lz, lw = normalize_quaternion(left)
    rx, ry, rz, rw = normalize_quaternion(right)
    return normalize_quaternion(
        (
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        )
    )


def apply_display_transform_pose(
    position: Iterable[float],
    quaternion: Iterable[float],
    matrix: np.ndarray,
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    transform = _validate_matrix(matrix)
    values = tuple(float(value) for value in position)
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError("position must contain three finite values")
    transformed = apply_display_transform_xyz(np.asarray([values], dtype=np.float64), transform)[0]
    yaw = math.atan2(transform[1, 0], transform[0, 0])
    q_align = (0.0, 0.0, math.sin(yaw * 0.5), math.cos(yaw * 0.5))
    q_out = _quaternion_multiply(q_align, quaternion)
    return (float(transformed[0]), float(transformed[1]), float(transformed[2])), q_out
