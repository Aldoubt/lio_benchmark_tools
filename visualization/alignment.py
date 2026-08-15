#!/usr/bin/env python3
"""Display-only alignment helpers.

These transforms never rewrite standardized artifacts. They exist only so maps
from estimators with different arbitrary initial origins/yaws can be compared
from a common visual start frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from benchmark_base.lib.trajectory import Trajectory


@dataclass(frozen=True)
class StartYawAlignment:
    origin_xyz: tuple[float, float, float]
    initial_yaw_rad: float

    def apply_xyz(self, xyz: np.ndarray) -> np.ndarray:
        points = np.asarray(xyz, dtype=np.float64)
        origin = np.asarray(self.origin_xyz, dtype=np.float64)
        shifted = points - origin
        c = math.cos(-self.initial_yaw_rad)
        s = math.sin(-self.initial_yaw_rad)
        rotation = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
        return (rotation @ shifted.T).T


def load_start_yaw_alignment(trajectory_path: str | Path) -> StartYawAlignment:
    trajectory = Trajectory.from_csv(trajectory_path)
    first = trajectory.samples[0]
    return StartYawAlignment((first.x_m, first.y_m, first.z_m), first.yaw_rad)
