#!/usr/bin/env python3
"""Compatibility wrapper around the benchmark Display Alignment contract."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from benchmark_base.lib.display_alignment import (
    apply_display_transform_xyz,
    compute_display_alignment,
)
from benchmark_base.lib.trajectory import Trajectory


@dataclass(frozen=True)
class StartYawAlignment:
    origin_xyz: tuple[float, float, float]
    initial_yaw_rad: float
    transform_matrix: tuple[tuple[float, ...], ...]

    def apply_xyz(self, xyz: np.ndarray) -> np.ndarray:
        return apply_display_transform_xyz(xyz, np.asarray(self.transform_matrix, dtype=np.float64))


def load_start_yaw_alignment(trajectory_path: str | Path) -> StartYawAlignment:
    trajectory = Trajectory.from_csv(trajectory_path)
    first = trajectory.samples[0]
    matrix = compute_display_alignment(first, "START_XY_YAW")
    return StartYawAlignment(
        (first.x_m, first.y_m, first.z_m),
        first.yaw_rad,
        tuple(tuple(float(value) for value in row) for row in matrix),
    )
