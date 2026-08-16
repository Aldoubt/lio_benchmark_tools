#!/usr/bin/env python3
"""Trajectory world-gauge and tracked-frame semantics helpers.

This module is intentionally descriptive.  It does not transform trajectories
or fit one estimator to another.  It only checks whether the frames published
at runtime are consistent with the source-backed contract recorded for an
algorithm.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


POSE_SEMANTICS = {"T_PARENT_TRACKED"}
TRACKED_FRAMES = {"IMU_BODY", "LIDAR", "BASE", "UNKNOWN"}
WORLD_GAUGES = {
    "GRAVITY_ALIGNED",
    "INITIAL_BODY_ALIGNED",
    "INITIAL_LIDAR_ALIGNED",
    "CONFIG_DEPENDENT",
    "UNKNOWN",
}
CHILD_FRAME_POLICIES = {"INPUT_LIDAR_FRAME"}


class FrameAuditStatus(str, Enum):
    MATCH = "MATCH"
    FRAME_LABEL_MISMATCH = "FRAME_LABEL_MISMATCH"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"


@dataclass(frozen=True)
class FrameAuditClassification:
    status: FrameAuditStatus
    reasons: tuple[str, ...]


def validate_trajectory_contract(contract: dict[str, Any]) -> None:
    if not isinstance(contract, dict):
        raise ValueError("trajectory_contract must be an object")
    pose_semantics = contract.get("pose_semantics")
    tracked = contract.get("tracked_frame_physical")
    world = contract.get("world_gauge")
    if pose_semantics not in POSE_SEMANTICS:
        raise ValueError(f"unsupported trajectory pose semantics: {pose_semantics!r}")
    if tracked not in TRACKED_FRAMES:
        raise ValueError(f"unsupported tracked frame: {tracked!r}")
    if world not in WORLD_GAUGES:
        raise ValueError(f"unsupported world gauge: {world!r}")

    parents = contract.get("expected_parent_frames", [])
    children = contract.get("expected_child_frames", [])
    if not isinstance(parents, list) or not all(isinstance(v, str) and v for v in parents):
        raise ValueError("expected_parent_frames must be a list of non-empty strings")
    if not isinstance(children, list) or not all(isinstance(v, str) and v for v in children):
        raise ValueError("expected_child_frames must be a list of non-empty strings")

    policy = contract.get("child_frame_policy")
    if policy is not None and policy not in CHILD_FRAME_POLICIES:
        raise ValueError(f"unsupported child frame policy: {policy!r}")
    if children and policy is not None:
        raise ValueError("use either expected_child_frames or child_frame_policy, not both")


def classify_frame_audit(
    contract: dict[str, Any],
    audit: dict[str, Any],
) -> FrameAuditClassification:
    validate_trajectory_contract(contract)
    if audit.get("status") != "AVAILABLE":
        return FrameAuditClassification(
            FrameAuditStatus.AUDIT_UNAVAILABLE,
            (f"frame audit status is {audit.get('status', 'UNKNOWN')}",),
        )

    reasons: list[str] = []
    observed_parents = tuple(audit.get("parent_frame_ids") or ())
    observed_children = tuple(audit.get("child_frame_ids") or ())

    expected_parents = tuple(contract.get("expected_parent_frames") or ())
    if expected_parents and set(observed_parents) != set(expected_parents):
        reasons.append(
            f"parent frame mismatch: expected={list(expected_parents)} observed={list(observed_parents)}"
        )

    expected_children = tuple(contract.get("expected_child_frames") or ())
    if expected_children and set(observed_children) != set(expected_children):
        reasons.append(
            f"child frame mismatch: expected={list(expected_children)} observed={list(observed_children)}"
        )

    # INPUT_LIDAR_FRAME is deliberately a semantic policy rather than a hard-coded
    # label.  The actual label is dataset-dependent and is preserved by the
    # frame-audit artifact for later inspection.
    if contract.get("child_frame_policy") == "INPUT_LIDAR_FRAME" and len(observed_children) != 1:
        reasons.append(
            f"input LiDAR child frame is not stable: observed={list(observed_children)}"
        )

    if reasons:
        return FrameAuditClassification(FrameAuditStatus.FRAME_LABEL_MISMATCH, tuple(reasons))
    return FrameAuditClassification(FrameAuditStatus.MATCH, ())
