#!/usr/bin/env python3
"""Shared trajectory interpolation, alignment, and LiDAR world projection helpers.

This module is the single implementation used by reconstructed-map generation and
viewer/report world-pointcloud diagnostics. It does not define absolute accuracy.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation, Slerp


@dataclass(frozen=True)
class TrajectoryModel:
    timestamp_s: np.ndarray
    positions: np.ndarray
    rotations: Rotation
    slerp: Slerp


@dataclass(frozen=True)
class IndexedLidarScan:
    bag_time_s: float
    header_timestamp_s: float
    points_xyz: np.ndarray
    point_times_s: np.ndarray
    intensity: np.ndarray


def load_standardized_trajectory(path: Path) -> TrajectoryModel:
    rows = list(csv.DictReader(Path(path).open(encoding="utf-8")))
    if len(rows) < 2:
        raise ValueError(f"trajectory has fewer than two rows: {path}")
    keys = ("timestamp_s", "x_m", "y_m", "z_m", "qx", "qy", "qz", "qw")
    data = {
        key: np.asarray([float(row[key]) for row in rows], dtype=np.float64)
        for key in keys
    }
    order = np.argsort(data["timestamp_s"], kind="stable")
    data = {key: values[order] for key, values in data.items()}
    _, unique = np.unique(data["timestamp_s"], return_index=True)
    unique = np.sort(unique)
    data = {key: values[unique] for key, values in data.items()}
    if len(data["timestamp_s"]) < 2:
        raise ValueError(f"trajectory has fewer than two unique timestamps: {path}")
    positions = np.column_stack((data["x_m"], data["y_m"], data["z_m"]))
    rotations = Rotation.from_quat(
        np.column_stack((data["qx"], data["qy"], data["qz"], data["qw"]))
    )
    return TrajectoryModel(
        timestamp_s=data["timestamp_s"],
        positions=positions,
        rotations=rotations,
        slerp=Slerp(data["timestamp_s"], rotations),
    )


def pose_at(
    model: TrajectoryModel,
    times_s: np.ndarray,
    *,
    max_gap_s: float | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    times = np.asarray(times_s, dtype=np.float64).reshape(-1)
    positions = np.full((len(times), 3), np.nan, dtype=np.float64)
    rotations = np.full((len(times), 3, 3), np.nan, dtype=np.float64)
    finite = np.isfinite(times)
    valid = finite & (times >= model.timestamp_s[0]) & (times <= model.timestamp_s[-1])

    if max_gap_s is not None:
        if max_gap_s <= 0:
            raise ValueError("max_gap_s must be > 0 when provided")
        indices = np.searchsorted(model.timestamp_s, times, side="right")
        exact_last = times == model.timestamp_s[-1]
        left = np.clip(indices - 1, 0, len(model.timestamp_s) - 1)
        right = np.clip(indices, 0, len(model.timestamp_s) - 1)
        interval = model.timestamp_s[right] - model.timestamp_s[left]
        interval[exact_last] = 0.0
        valid &= interval <= float(max_gap_s)

    if np.any(valid):
        valid_times = times[valid]
        positions[valid] = np.column_stack(
            [
                np.interp(valid_times, model.timestamp_s, model.positions[:, axis])
                for axis in range(3)
            ]
        )
        rotations[valid] = model.slerp(valid_times).as_matrix()
    return positions, rotations, valid


def initial_yaw_translation_alignment(
    reference: TrajectoryModel,
    candidate: TrajectoryModel,
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    start = max(float(reference.timestamp_s[0]), float(candidate.timestamp_s[0]))
    end = min(float(reference.timestamp_s[-1]), float(candidate.timestamp_s[-1]))
    if end <= start:
        raise ValueError("baseline and candidate have no common time window")
    sample_count = min(500, max(2, int((end - start) * 10)))
    times = np.linspace(start, end, sample_count)

    reference_start, reference_rotation, reference_valid = pose_at(
        reference, np.asarray([start])
    )
    candidate_start, candidate_rotation, candidate_valid = pose_at(
        candidate, np.asarray([start])
    )
    if not bool(reference_valid[0] and candidate_valid[0]):
        raise ValueError("common alignment start is not covered by both trajectories")
    reference_yaw = math.atan2(
        reference_rotation[0, 1, 0], reference_rotation[0, 0, 0]
    )
    candidate_yaw = math.atan2(
        candidate_rotation[0, 1, 0], candidate_rotation[0, 0, 0]
    )
    yaw = reference_yaw - candidate_yaw
    rotation = np.eye(3, dtype=np.float64)
    rotation[:2, :2] = np.asarray(
        [[math.cos(yaw), -math.sin(yaw)], [math.sin(yaw), math.cos(yaw)]],
        dtype=np.float64,
    )
    translation = reference_start[0] - rotation @ candidate_start[0]

    reference_positions, _, reference_mask = pose_at(reference, times)
    candidate_positions, _, candidate_mask = pose_at(candidate, times)
    mask = reference_mask & candidate_mask
    if not np.any(mask):
        raise ValueError("no valid common samples for trajectory alignment")
    aligned = (rotation @ candidate_positions[mask].T).T + translation
    errors = np.linalg.norm(aligned - reference_positions[mask], axis=1)
    return rotation, translation, {
        "method": "initial_yaw_translation",
        "common_start_s": start,
        "common_end_s": end,
        "common_duration_s": end - start,
        "samples": float(np.count_nonzero(mask)),
        "rmse_m": float(np.sqrt(np.mean(errors**2))),
        "mean_m": float(np.mean(errors)),
        "p95_m": float(np.percentile(errors, 95)),
        "max_m": float(np.max(errors)),
    }


def project_points_to_display_world(
    points_xyz: np.ndarray,
    point_times_s: np.ndarray,
    trajectory: TrajectoryModel,
    extrinsic_rotation: np.ndarray,
    extrinsic_translation: np.ndarray,
    alignment_rotation: np.ndarray,
    alignment_translation: np.ndarray,
    origin: np.ndarray,
    max_gap_s: float | None,
) -> tuple[np.ndarray, np.ndarray]:
    points = np.asarray(points_xyz, dtype=np.float64)
    times = np.asarray(point_times_s, dtype=np.float64).reshape(-1)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points_xyz must have shape (N, 3)")
    if len(points) != len(times):
        raise ValueError("points_xyz and point_times_s must have equal length")

    positions, rotations, pose_valid = pose_at(
        trajectory, times, max_gap_s=max_gap_s
    )
    input_valid = np.isfinite(points).all(axis=1) & np.isfinite(times)
    valid = pose_valid & input_valid
    output = np.full_like(points, np.nan, dtype=np.float64)
    if not np.any(valid):
        return output, valid

    extrinsic_rotation = np.asarray(extrinsic_rotation, dtype=np.float64).reshape(3, 3)
    extrinsic_translation = np.asarray(extrinsic_translation, dtype=np.float64).reshape(3)
    alignment_rotation = np.asarray(alignment_rotation, dtype=np.float64).reshape(3, 3)
    alignment_translation = np.asarray(alignment_translation, dtype=np.float64).reshape(3)
    origin = np.asarray(origin, dtype=np.float64).reshape(3)

    selected_points = points[valid]
    lidar_in_body = (
        extrinsic_rotation @ selected_points.T
    ).T + extrinsic_translation
    world = np.einsum("nij,nj->ni", rotations[valid], lidar_in_body) + positions[valid]
    output[valid] = (
        (alignment_rotation @ world.T).T + alignment_translation - origin
    )
    return output, valid
