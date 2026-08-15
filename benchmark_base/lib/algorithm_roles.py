#!/usr/bin/env python3
"""Shared baseline-suite vocabulary for registry and reporting contracts."""
from __future__ import annotations

from typing import Any

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


def primary_evaluation_role(algorithm: dict[str, Any]) -> str:
    """Return the declared primary role for a runnable algorithm identity.

    Runnable IDs preserve registry ordering: single-role records such as
    ``glim_full_slam`` remain SYSTEM_MAPPING, while multi-role implementations
    such as current Leg-KILO use the first declared role for the compatibility
    trajectory path until a role-qualified path is selected explicitly.
    """
    roles = algorithm.get("evaluation_roles", [])
    if not isinstance(roles, list) or not roles:
        raise ValueError("algorithm has no declared evaluation_roles")
    role = str(roles[0]).upper()
    if role not in EVALUATION_ROLES:
        raise ValueError(f"unsupported primary evaluation role: {role}")
    return role
