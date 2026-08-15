#!/usr/bin/env python3
"""Pure eligibility rules for benchmark report scoreboards."""
from __future__ import annotations

from typing import Any


COMMON_LIO = "COMMON_LIO"
SYSTEM_MAPPING = "SYSTEM_MAPPING"
CONTROL_EXTENSION = "CONTROL_EXTENSION"
SCOREBOARDS = (COMMON_LIO, SYSTEM_MAPPING, CONTROL_EXTENSION)


def _common_lio_sensor_profile(record: dict[str, Any]) -> bool:
    profile = record.get("sensor_profile", {})
    if not isinstance(profile, dict):
        return False
    return bool(profile.get("lidar")) and bool(profile.get("imu")) and not any(
        bool(profile.get(key)) for key in ("camera", "kinematics", "gnss", "wheel_odometry")
    )


def eligible_scoreboards(record: dict[str, Any]) -> tuple[str, ...]:
    """Return every report view to which an algorithm/mode may contribute.

    Eligibility describes method/input comparability, not success. A blocked or
    missing run remains listed in its eligible scoreboard and carries its status.
    """

    roles = set(record.get("evaluation_roles", ()))
    boards: list[str] = []
    if "ODOMETRY" in roles and _common_lio_sensor_profile(record):
        boards.append(COMMON_LIO)
    if "SYSTEM_MAPPING" in roles:
        boards.append(SYSTEM_MAPPING)
    if "CONTROL" in roles or ("ODOMETRY" in roles and not _common_lio_sensor_profile(record)):
        boards.append(CONTROL_EXTENSION)
    return tuple(boards)


def group_manifest_algorithms(manifest: dict[str, Any]) -> dict[str, list[str]]:
    grouped = {board: [] for board in SCOREBOARDS}
    algorithms = manifest.get("algorithms", {})
    if not isinstance(algorithms, dict):
        raise ValueError("manifest algorithms must be an object")
    for algorithm_id, record in algorithms.items():
        if not isinstance(record, dict):
            continue
        for board in eligible_scoreboards(record):
            grouped[board].append(algorithm_id)
    return grouped


def scoreboard_title(board: str) -> str:
    titles = {
        COMMON_LIO: "Common LiDAR + IMU Odometry",
        SYSTEM_MAPPING: "System Mapping / Global Optimization",
        CONTROL_EXTENSION: "Control / Extension",
    }
    try:
        return titles[board]
    except KeyError as exc:
        raise ValueError(f"unknown scoreboard: {board}") from exc
