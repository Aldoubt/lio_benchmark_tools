#!/usr/bin/env python3
"""ROS-independent conversion from raw pose observations to standard trajectory."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Iterable

from benchmark_base.lib.frame_audit import RawPoseObservation
from benchmark_base.lib.trajectory import (
    PoseSample,
    Trajectory,
    TrajectoryError,
    normalize_quaternion,
    rpy_from_quaternion,
)


TIMESTAMP_POLICY = "HEADER_STAMP_ELSE_BAG_RECORD_TIME"
TIMESTAMP_DUPLICATE_POLICY = "COALESCE_EXACT_TIMESTAMP_KEEP_LAST_PUBLISHED_STATE"
TIMESTAMP_REGRESSION_POLICY = "FAIL_CLOSED"
SOURCE_KIND = "RUN_LOCAL_ROS2_BAG"


@dataclass(frozen=True)
class TimestampCanonicalization:
    policy: str
    raw_sample_count: int
    canonical_sample_count: int
    duplicate_group_count: int
    coalesced_sample_count: int


def _finite_pose(observation: RawPoseObservation) -> None:
    values = (
        observation.timestamp_s,
        observation.x_m,
        observation.y_m,
        observation.z_m,
        observation.qx,
        observation.qy,
        observation.qz,
        observation.qw,
    )
    if any(not math.isfinite(float(value)) for value in values):
        raise TrajectoryError("raw pose observation contains non-finite values")


def canonicalize_pose_observations(
    observations: Iterable[RawPoseObservation],
) -> tuple[tuple[RawPoseObservation, ...], TimestampCanonicalization]:
    """Convert repeated same-time state revisions into one state per timestamp.

    Input order is preserved. Exact duplicate timestamps are interpreted as
    multiple published revisions of the same declared estimator time and the
    last published state is retained. Any backwards timestamp remains a hard
    failure; this function never sorts or retimes observations.
    """
    raw = tuple(observations)
    canonical: list[RawPoseObservation] = []
    duplicate_groups = 0
    coalesced = 0
    previous_raw_timestamp: float | None = None
    in_duplicate_group = False

    for observation in raw:
        _finite_pose(observation)
        timestamp = float(observation.timestamp_s)
        if previous_raw_timestamp is not None and timestamp < previous_raw_timestamp:
            raise TrajectoryError(
                f"trajectory timestamp regression: {timestamp:.9f} < {previous_raw_timestamp:.9f}"
            )
        if canonical and timestamp == float(canonical[-1].timestamp_s):
            if not in_duplicate_group:
                duplicate_groups += 1
            canonical[-1] = observation
            coalesced += 1
            in_duplicate_group = True
        else:
            canonical.append(observation)
            in_duplicate_group = False
        previous_raw_timestamp = timestamp

    summary = TimestampCanonicalization(
        policy=TIMESTAMP_DUPLICATE_POLICY,
        raw_sample_count=len(raw),
        canonical_sample_count=len(canonical),
        duplicate_group_count=duplicate_groups,
        coalesced_sample_count=coalesced,
    )
    return tuple(canonical), summary


def trajectory_from_observations(
    observations: Iterable[RawPoseObservation],
    *,
    source_topic: str,
) -> Trajectory:
    """Preserve estimator poses while normalizing them into the CSV contract."""
    samples: list[PoseSample] = []
    for observation in observations:
        _finite_pose(observation)
        qx, qy, qz, qw = normalize_quaternion(
            (observation.qx, observation.qy, observation.qz, observation.qw)
        )
        roll, pitch, yaw = rpy_from_quaternion(qx, qy, qz, qw)
        samples.append(
            PoseSample(
                timestamp_s=float(observation.timestamp_s),
                x_m=float(observation.x_m),
                y_m=float(observation.y_m),
                z_m=float(observation.z_m),
                qx=qx,
                qy=qy,
                qz=qz,
                qw=qw,
                roll_rad=roll,
                pitch_rad=pitch,
                yaw_rad=yaw,
                source_topic=str(source_topic),
            )
        )
    return Trajectory(samples)


def trajectory_topic_from_algorithm(algorithm: dict[str, Any]) -> str:
    topics = algorithm.get("topics", {})
    outputs = topics.get("outputs", {}) if isinstance(topics, dict) else {}
    value = outputs.get("trajectory") if isinstance(outputs, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("frozen algorithm contract is missing trajectory output topic")
    return value.strip()


def trajectory_output_paths(run: Path, algorithm_id: str) -> tuple[Path, Path]:
    return (
        run / "standardized" / "trajectories" / f"{algorithm_id}.csv",
        run / "metadata" / "algorithms" / algorithm_id / "trajectory_standardization.json",
    )


def ensure_standardized_trajectory_absent(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing standardized trajectory: {path}")


def build_trajectory_standardization_metadata(
    *,
    algorithm_id: str,
    source_bag: str,
    source_topic: str,
    source_message_type: str,
    sample_count: int,
    start_timestamp_s: float,
    end_timestamp_s: float,
    output: str,
    timestamp_canonicalization: TimestampCanonicalization | None = None,
) -> dict[str, Any]:
    canonicalization = timestamp_canonicalization or TimestampCanonicalization(
        policy=TIMESTAMP_DUPLICATE_POLICY,
        raw_sample_count=int(sample_count),
        canonical_sample_count=int(sample_count),
        duplicate_group_count=0,
        coalesced_sample_count=0,
    )
    if canonicalization.canonical_sample_count != int(sample_count):
        raise ValueError("timestamp canonicalization sample count does not match trajectory sample count")
    return {
        "schema_version": 1,
        "algorithm_id": str(algorithm_id),
        "source_kind": SOURCE_KIND,
        "source_bag": str(source_bag),
        "source_topic": str(source_topic),
        "source_message_type": str(source_message_type),
        "timestamp_policy": TIMESTAMP_POLICY,
        "timestamp_duplicate_policy": TIMESTAMP_DUPLICATE_POLICY,
        "timestamp_regression_policy": TIMESTAMP_REGRESSION_POLICY,
        "raw_sample_count": int(canonicalization.raw_sample_count),
        "sample_count": int(sample_count),
        "duplicate_timestamp_group_count": int(canonicalization.duplicate_group_count),
        "coalesced_duplicate_sample_count": int(canonicalization.coalesced_sample_count),
        "start_timestamp_s": float(start_timestamp_s),
        "end_timestamp_s": float(end_timestamp_s),
        "output": str(output),
    }
