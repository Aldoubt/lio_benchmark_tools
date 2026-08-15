#!/usr/bin/env python3
"""Shared baseline-suite vocabulary for registry and reporting contracts."""
from __future__ import annotations

ALGORITHM_TIERS = frozenset({"CORE", "RESEARCH", "LEGACY"})
EVALUATION_ROLES = frozenset({"ODOMETRY", "SYSTEM_MAPPING", "CONTROL", "DIAGNOSTIC"})
ADAPTER_STATUSES = frozenset({
    "PASS",
    "FAIL_IMPLEMENTATION",
    "FAIL_ALGORITHM",
    "BLOCKED_ENVIRONMENT",
    "BLOCKED_DEPENDENCY",
    "BLOCKED_INPUT",
    "BLOCKED_CALIBRATION",
    "NOT_TESTED",
})
SENSOR_PROFILE_KEYS = (
    "lidar",
    "imu",
    "camera",
    "kinematics",
    "gnss",
    "wheel_odometry",
)


def default_sensor_profile(*enabled: str) -> dict[str, bool]:
    unknown = set(enabled) - set(SENSOR_PROFILE_KEYS)
    if unknown:
        raise ValueError(f"unknown sensor profile keys: {sorted(unknown)}")
    return {key: key in enabled for key in SENSOR_PROFILE_KEYS}
