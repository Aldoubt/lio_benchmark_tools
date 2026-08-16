#!/usr/bin/env python3
"""Map reconstruction transforms keyed by the physical tracked frame."""
from __future__ import annotations

from typing import Any

import numpy as np


def lidar_points_in_tracked_frame(
    points_lidar: np.ndarray,
    *,
    tracked_frame_physical: str,
    calibration: dict[str, Any],
) -> np.ndarray:
    """Express LiDAR scan points in the physical frame tracked by a trajectory."""
    points = np.asarray(points_lidar, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("LiDAR points must be an Nx3 array")

    tracked = str(tracked_frame_physical).upper()
    if tracked == "LIDAR":
        return points.copy()
    if tracked != "IMU_BODY":
        raise ValueError(f"unsupported tracked frame for unified map reconstruction: {tracked}")

    try:
        rotation_values = calibration["rotation_lidar_to_imu_row_major"]
        translation_values = calibration["translation_lidar_to_imu_m"]
        rotation = np.asarray(rotation_values, dtype=np.float64).reshape(3, 3)
        translation = np.asarray(translation_values, dtype=np.float64).reshape(3)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid canonical LiDAR-to-IMU calibration") from exc
    if not np.isfinite(rotation).all() or not np.isfinite(translation).all():
        raise ValueError("invalid canonical LiDAR-to-IMU calibration")
    return (rotation @ points.T).T + translation
