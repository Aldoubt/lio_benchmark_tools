#!/usr/bin/env python3
"""Canonical LiDAR/IMU calibration helpers.

Dataset Registry owns a canonical LiDAR-to-IMU transform. Algorithm adapters
request either that transform, its mathematical inverse, or no extrinsic at all.
The module is intentionally ROS-independent so configuration generation and
unit tests remain portable.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable


CONFIRMED_CALIBRATION_STATUSES = frozenset({"CONFIRMED", "VERIFIED"})
EXTRINSIC_CONVENTIONS = frozenset({"LIDAR_TO_IMU", "IMU_TO_LIDAR", "NONE"})


def _finite_tuple(values: Iterable[float], expected: int, name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != expected:
        raise ValueError(f"{name} must have {expected} values")
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{name} must contain only finite values")
    return result


@dataclass(frozen=True)
class RigidTransform:
    """Rigid transform stored as row-major 3x3 rotation plus translation."""

    rotation: tuple[float, ...]
    translation: tuple[float, float, float]

    def __post_init__(self) -> None:
        rotation = _finite_tuple(self.rotation, 9, "rotation")
        translation = _finite_tuple(self.translation, 3, "translation")
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "translation", translation)


def invert_transform(transform: RigidTransform) -> RigidTransform:
    r = transform.rotation
    # R^-1 = R^T for a rigid-body rotation.
    rt = (
        r[0], r[3], r[6],
        r[1], r[4], r[7],
        r[2], r[5], r[8],
    )
    tx, ty, tz = transform.translation
    inverse_translation = (
        -(rt[0] * tx + rt[1] * ty + rt[2] * tz),
        -(rt[3] * tx + rt[4] * ty + rt[5] * tz),
        -(rt[6] * tx + rt[7] * ty + rt[8] * tz),
    )
    return RigidTransform(rotation=rt, translation=inverse_translation)


def canonical_lidar_to_imu(dataset: dict[str, Any]) -> RigidTransform:
    calibration = dataset.get("calibration")
    if not isinstance(calibration, dict):
        raise ValueError("dataset calibration object is required")
    return RigidTransform(
        rotation=tuple(calibration.get("rotation_lidar_to_imu_row_major", ())),
        translation=tuple(calibration.get("translation_lidar_to_imu_m", ())),
    )


def calibration_status(dataset: dict[str, Any]) -> str:
    calibration = dataset.get("calibration")
    if not isinstance(calibration, dict):
        return "UNKNOWN"
    value = calibration.get("status", "UNKNOWN")
    return str(value).strip().upper() or "UNKNOWN"


def resolve_algorithm_extrinsic(dataset: dict[str, Any], algorithm: dict[str, Any]) -> dict[str, Any]:
    """Resolve the run-local extrinsic representation required by an algorithm.

    This function never edits upstream configuration. It returns serializable
    data that adapters may write into run-local generated configuration files.
    """

    convention = str(algorithm.get("extrinsic_convention", "")).strip().upper()
    if convention not in EXTRINSIC_CONVENTIONS:
        raise ValueError(
            f"unsupported extrinsic convention for {algorithm.get('algorithm_id', '<unknown>')}: {convention or '<missing>'}"
        )

    if convention == "NONE":
        return {
            "algorithm_id": algorithm.get("algorithm_id"),
            "convention": "NONE",
            "rotation_row_major": None,
            "translation_m": None,
            "canonical_convention": "LIDAR_TO_IMU",
            "calibration_status": "NOT_REQUIRED",
            "calibration_source": None,
            "diagnostic_only": False,
        }

    canonical = canonical_lidar_to_imu(dataset)
    resolved = canonical if convention == "LIDAR_TO_IMU" else invert_transform(canonical)
    status = calibration_status(dataset)
    calibration = dataset["calibration"]
    return {
        "algorithm_id": algorithm.get("algorithm_id"),
        "convention": convention,
        "rotation_row_major": list(resolved.rotation),
        "translation_m": list(resolved.translation),
        "canonical_convention": "LIDAR_TO_IMU",
        "calibration_status": status,
        "calibration_source": calibration.get("source"),
        "diagnostic_only": status not in CONFIRMED_CALIBRATION_STATUSES,
    }
