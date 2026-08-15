#!/usr/bin/env python3
"""Display-only alignment transforms for cross-algorithm visualization.

These transforms are derived visualization products. They must never be used to
rewrite standardized trajectories, Native Maps, Unified Maps, or scientific
metrics.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np

from benchmark_base.lib.algorithm_roles import EVALUATION_ROLES, primary_evaluation_role
from benchmark_base.lib.trajectory import PoseSample, Trajectory, normalize_quaternion


DISPLAY_ALIGNMENT_MODES = frozenset({"NONE", "START_XY_YAW"})
DISPLAY_ALIGNMENT_ALIASES = {"raw": "NONE", "start_yaw": "START_XY_YAW"}


def normalize_display_alignment_mode(mode: str) -> str:
    value = mode.strip()
    canonical = DISPLAY_ALIGNMENT_ALIASES.get(value.lower(), value.upper())
    if canonical not in DISPLAY_ALIGNMENT_MODES:
        raise ValueError(f"unsupported display alignment mode: {mode}")
    return canonical


def compute_display_alignment(initial_pose: PoseSample, mode: str) -> np.ndarray:
    mode = normalize_display_alignment_mode(mode)
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
    matrix[0, 3] = -(c * initial_pose.x_m - s * initial_pose.y_m)
    matrix[1, 3] = -(s * initial_pose.x_m + c * initial_pose.y_m)
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


def resolve_display_trajectory_role(
    run: str | Path,
    algorithm_id: str,
    requested_role: str,
) -> str:
    """Resolve a display role without mislabeling runnable System Mapping IDs.

    Existing callers historically request ODOMETRY. If that role is not one of
    the algorithm's declared roles in the frozen run manifest, use the
    algorithm's declared primary role instead. Explicit valid roles remain
    untouched, which permits future role-qualified frontend/backend views.
    """
    requested = str(requested_role).upper()
    if requested not in EVALUATION_ROLES:
        raise ValueError(f"unsupported display trajectory role: {requested_role}")
    manifest_path = Path(run) / "manifest.json"
    if not manifest_path.is_file():
        return requested
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid frozen run manifest: {manifest_path}: {exc}") from exc
    algorithms = manifest.get("algorithms", {})
    algorithm = algorithms.get(algorithm_id, {}) if isinstance(algorithms, dict) else {}
    if not isinstance(algorithm, dict) or not algorithm:
        return requested
    declared = [str(role).upper() for role in algorithm.get("evaluation_roles", [])]
    if requested in declared:
        return requested
    return primary_evaluation_role(algorithm)


def display_alignment_metadata(
    *,
    algorithm_id: str,
    trajectory_role: str,
    trajectory_path: str | Path,
    mode: str,
) -> dict:
    canonical = normalize_display_alignment_mode(mode)
    trajectory = Trajectory.from_csv(trajectory_path)
    first = trajectory.samples[0]
    matrix = compute_display_alignment(first, canonical)
    return {
        "schema_version": 1,
        "mode": canonical,
        "algorithm_id": algorithm_id,
        "trajectory_role": trajectory_role,
        "source_trajectory": str(Path(trajectory_path)),
        "source_initial_pose": {
            "timestamp_s": first.timestamp_s,
            "x_m": first.x_m,
            "y_m": first.y_m,
            "z_m": first.z_m,
            "roll_rad": first.roll_rad,
            "pitch_rad": first.pitch_rad,
            "yaw_rad": first.yaw_rad,
            "qx": first.qx,
            "qy": first.qy,
            "qz": first.qz,
            "qw": first.qw,
        },
        "transform_matrix_4x4": matrix.tolist(),
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "scientific_artifacts_modified": False,
    }


def write_display_alignment_metadata(
    *,
    run: str | Path,
    algorithm_id: str,
    trajectory_role: str,
    trajectory_path: str | Path,
    mode: str,
) -> Path:
    resolved_role = resolve_display_trajectory_role(run, algorithm_id, trajectory_role)
    payload = display_alignment_metadata(
        algorithm_id=algorithm_id,
        trajectory_role=resolved_role,
        trajectory_path=trajectory_path,
        mode=mode,
    )
    path = Path(run) / "figures" / "display_alignment" / f"{algorithm_id}__{resolved_role.lower()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
