#!/usr/bin/env python3
"""ROS-independent conversion from raw pose observations to standard trajectory."""
from __future__ import annotations

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
SOURCE_KIND = "RUN_LOCAL_ROS2_BAG"


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
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "algorithm_id": str(algorithm_id),
        "source_kind": SOURCE_KIND,
        "source_bag": str(source_bag),
        "source_topic": str(source_topic),
        "source_message_type": str(source_message_type),
        "timestamp_policy": TIMESTAMP_POLICY,
        "sample_count": int(sample_count),
        "start_timestamp_s": float(start_timestamp_s),
        "end_timestamp_s": float(end_timestamp_s),
        "output": str(output),
    }
