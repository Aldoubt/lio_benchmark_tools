#!/usr/bin/env python3
"""Relative SE(3) motion benchmark core.

This module is ROS-independent. It compares relative motion disagreement when
no ground-truth trajectory is available. It never fits one estimator to
another and never mutates standardized trajectories.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from benchmark_base.lib.calibration import (
    CONFIRMED_CALIBRATION_STATUSES,
    RigidTransform,
    calibration_status,
    canonical_lidar_to_imu,
    invert_transform,
)
from benchmark_base.lib.trajectory import PoseSample, Trajectory, normalize_quaternion
from benchmark_base.lib.trajectory_semantics import classify_frame_audit


TARGET_PHYSICAL_FRAME = "IMU_BODY"
SAMPLE_PERIOD_S = 0.1
SUSTAIN_SAMPLES = 3
TRANSLATION_THRESHOLDS_M = (0.05, 0.10, 0.20, 0.50)
ROTATION_THRESHOLDS_DEG = (1.0, 2.0, 5.0, 10.0)
RELATIVE_SE3_SCHEMA = "lio_benchmark_relative_se3/v1"

NORMALIZED_MOTION_FIELDS = (
    "algorithm_id",
    "timestamp_s",
    "relative_time_s",
    "x_m",
    "y_m",
    "z_m",
    "qx",
    "qy",
    "qz",
    "qw",
    "tracked_frame_physical",
    "target_frame_physical",
)
PAIRWISE_SAMPLE_FIELDS = (
    "left_algorithm_id",
    "right_algorithm_id",
    "timestamp_s",
    "relative_time_s",
    "dx_m",
    "dy_m",
    "dz_m",
    "xy_m",
    "z_abs_m",
    "xyz_m",
    "rotation_rad",
    "rotation_deg",
)
PAIRWISE_SUMMARY_FIELDS = (
    "left_algorithm_id",
    "right_algorithm_id",
    "overlap_start_s",
    "overlap_end_s",
    "overlap_duration_s",
    "sample_period_s",
    "sample_count",
    "xy_rmse_m",
    "xy_median_m",
    "xy_p95_m",
    "xy_max_m",
    "xy_peak_timestamp_s",
    "xy_peak_relative_time_s",
    "z_abs_rmse_m",
    "z_abs_median_m",
    "z_abs_p95_m",
    "z_abs_max_m",
    "z_abs_peak_timestamp_s",
    "z_abs_peak_relative_time_s",
    "xyz_rmse_m",
    "xyz_median_m",
    "xyz_p95_m",
    "xyz_max_m",
    "xyz_peak_timestamp_s",
    "xyz_peak_relative_time_s",
    "rotation_rmse_deg",
    "rotation_median_deg",
    "rotation_p95_deg",
    "rotation_max_deg",
    "rotation_peak_timestamp_s",
    "rotation_peak_relative_time_s",
    "physical_frame_normalization_uses_calibration",
    "calibration_status",
    "scientific_status",
    "diagnostic_reasons",
)
ONSET_FIELDS = (
    "left_algorithm_id",
    "right_algorithm_id",
    "metric",
    "threshold",
    "unit",
    "sustain_samples",
    "crossed",
    "onset_timestamp_s",
    "onset_relative_time_s",
    "onset_value",
)


class RelativeSE3Error(ValueError):
    """Raised when the Relative SE(3) run contract cannot be satisfied."""


@dataclass(frozen=True)
class SE3Pose:
    rotation: tuple[float, ...]
    translation: tuple[float, float, float]

    def __post_init__(self) -> None:
        rotation = tuple(float(value) for value in self.rotation)
        translation = tuple(float(value) for value in self.translation)
        if len(rotation) != 9:
            raise ValueError("SE3 rotation must contain 9 row-major values")
        if len(translation) != 3:
            raise ValueError("SE3 translation must contain 3 values")
        if not all(math.isfinite(value) for value in (*rotation, *translation)):
            raise ValueError("SE3 pose must contain only finite values")
        object.__setattr__(self, "rotation", rotation)
        object.__setattr__(self, "translation", translation)


@dataclass(frozen=True)
class SustainedOnset:
    crossed: bool
    onset_relative_time_s: float | None
    onset_value: float | None
    onset_index: int | None


def _rotation_matrix(values: Iterable[float] | np.ndarray) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.size != 9:
        raise ValueError("rotation must contain 9 values")
    matrix = matrix.reshape(3, 3)
    if not np.isfinite(matrix).all():
        raise ValueError("rotation must be finite")
    return matrix


def _translation_vector(values: Iterable[float]) -> np.ndarray:
    vector = np.asarray(tuple(values), dtype=np.float64)
    if vector.shape != (3,) or not np.isfinite(vector).all():
        raise ValueError("translation must contain 3 finite values")
    return vector


def quaternion_to_rotation(
    qx: float, qy: float, qz: float, qw: float
) -> tuple[float, ...]:
    x, y, z, w = normalize_quaternion((qx, qy, qz, qw))
    matrix = np.asarray(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    return tuple(float(value) for value in matrix.reshape(-1))


def rotation_to_quaternion(rotation: Iterable[float] | np.ndarray) -> tuple[float, float, float, float]:
    matrix = _rotation_matrix(rotation)
    trace = float(np.trace(matrix))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        qw = 0.25 * scale
        qx = (matrix[2, 1] - matrix[1, 2]) / scale
        qy = (matrix[0, 2] - matrix[2, 0]) / scale
        qz = (matrix[1, 0] - matrix[0, 1]) / scale
    elif matrix[0, 0] > matrix[1, 1] and matrix[0, 0] > matrix[2, 2]:
        scale = math.sqrt(max(0.0, 1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2])) * 2.0
        qw = (matrix[2, 1] - matrix[1, 2]) / scale
        qx = 0.25 * scale
        qy = (matrix[0, 1] + matrix[1, 0]) / scale
        qz = (matrix[0, 2] + matrix[2, 0]) / scale
    elif matrix[1, 1] > matrix[2, 2]:
        scale = math.sqrt(max(0.0, 1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2])) * 2.0
        qw = (matrix[0, 2] - matrix[2, 0]) / scale
        qx = (matrix[0, 1] + matrix[1, 0]) / scale
        qy = 0.25 * scale
        qz = (matrix[1, 2] + matrix[2, 1]) / scale
    else:
        scale = math.sqrt(max(0.0, 1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1])) * 2.0
        qw = (matrix[1, 0] - matrix[0, 1]) / scale
        qx = (matrix[0, 2] + matrix[2, 0]) / scale
        qy = (matrix[1, 2] + matrix[2, 1]) / scale
        qz = 0.25 * scale
    return normalize_quaternion((qx, qy, qz, qw))


def pose_from_sample(sample: PoseSample) -> SE3Pose:
    return SE3Pose(
        rotation=quaternion_to_rotation(sample.qx, sample.qy, sample.qz, sample.qw),
        translation=(sample.x_m, sample.y_m, sample.z_m),
    )


def pose_from_rigid_transform(transform: RigidTransform) -> SE3Pose:
    return SE3Pose(rotation=transform.rotation, translation=transform.translation)


def compose_pose(left: SE3Pose, right: SE3Pose) -> SE3Pose:
    left_r = _rotation_matrix(left.rotation)
    right_r = _rotation_matrix(right.rotation)
    left_t = _translation_vector(left.translation)
    right_t = _translation_vector(right.translation)
    rotation = left_r @ right_r
    translation = left_t + left_r @ right_t
    return SE3Pose(
        rotation=tuple(float(value) for value in rotation.reshape(-1)),
        translation=tuple(float(value) for value in translation),
    )


def invert_pose(pose: SE3Pose) -> SE3Pose:
    rotation = _rotation_matrix(pose.rotation)
    translation = _translation_vector(pose.translation)
    inverse_rotation = rotation.T
    inverse_translation = -(inverse_rotation @ translation)
    return SE3Pose(
        rotation=tuple(float(value) for value in inverse_rotation.reshape(-1)),
        translation=tuple(float(value) for value in inverse_translation),
    )


def relative_pose(origin: SE3Pose, current: SE3Pose) -> SE3Pose:
    """Return ``origin^-1 * current`` without any estimator-to-estimator fit."""
    return compose_pose(invert_pose(origin), current)


def normalize_pose_to_imu(
    pose: SE3Pose,
    tracked_frame_physical: str,
    canonical_lidar_to_imu: RigidTransform | None,
) -> SE3Pose:
    tracked = str(tracked_frame_physical).strip().upper()
    if tracked == "IMU_BODY":
        return pose
    if tracked != "LIDAR":
        raise ValueError(f"unsupported tracked physical frame for Relative SE(3): {tracked or '<missing>'}")
    if canonical_lidar_to_imu is None:
        raise ValueError("LiDAR-tracked trajectory requires canonical LiDAR-to-IMU calibration")
    # Canonical calibration is T_IL. A world LiDAR pose T_WL becomes a world
    # IMU pose by right-multiplying T_LI = inverse(T_IL).
    lidar_to_imu_inverse = invert_transform(canonical_lidar_to_imu)
    return compose_pose(pose, pose_from_rigid_transform(lidar_to_imu_inverse))


def common_evaluation_times(
    trajectories: Mapping[str, Trajectory],
    *,
    sample_period_s: float = SAMPLE_PERIOD_S,
) -> tuple[float, float, tuple[float, ...]]:
    if len(trajectories) < 2:
        raise ValueError("Relative SE(3) requires at least two trajectories")
    period = float(sample_period_s)
    if period <= 0.0 or not math.isfinite(period):
        raise ValueError("sample period must be finite and positive")
    start = max(trajectory.timestamps[0] for trajectory in trajectories.values())
    end = min(trajectory.timestamps[-1] for trajectory in trajectories.values())
    if end <= start:
        raise ValueError("eligible trajectories have no common time interval")
    count = int(math.floor((end - start) / period + 1e-12))
    times = [start + index * period for index in range(count + 1)]
    if end - times[-1] > 1e-9:
        times.append(end)
    else:
        times[-1] = end
    return start, end, tuple(times)


def rotation_geodesic_rad(rotation: Iterable[float] | np.ndarray) -> float:
    matrix = _rotation_matrix(rotation)
    cosine = float((np.trace(matrix) - 1.0) * 0.5)
    return math.acos(max(-1.0, min(1.0, cosine)))


def sustained_onset(
    relative_times_s: Sequence[float],
    values: Sequence[float],
    *,
    threshold: float,
    sustain_samples: int = SUSTAIN_SAMPLES,
) -> SustainedOnset:
    times = tuple(float(value) for value in relative_times_s)
    metrics = tuple(float(value) for value in values)
    threshold_value = float(threshold)
    if len(times) != len(metrics):
        raise ValueError("onset times and values must have equal length")
    if sustain_samples <= 0:
        raise ValueError("sustain_samples must be positive")
    if not math.isfinite(threshold_value):
        raise ValueError("onset threshold must be finite")
    if any(not math.isfinite(value) for value in (*times, *metrics)):
        raise ValueError("onset inputs must be finite")
    consecutive = 0
    for index, value in enumerate(metrics):
        consecutive = consecutive + 1 if value >= threshold_value else 0
        if consecutive >= sustain_samples:
            onset_index = index - sustain_samples + 1
            return SustainedOnset(
                crossed=True,
                onset_relative_time_s=times[onset_index],
                onset_value=metrics[onset_index],
                onset_index=onset_index,
            )
    return SustainedOnset(False, None, None, None)


def _load_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _load_provenance_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
    except OSError:
        return {}
    return {
        str(row.get("algorithm_id")): {str(key): str(value) for key, value in row.items()}
        for row in rows
        if row.get("algorithm_id")
    }


def _fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path.resolve()),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _max_gap(trajectory: Trajectory) -> float:
    return max(right - left for left, right in zip(trajectory.timestamps, trajectory.timestamps[1:]))


def _interpolated_world_pose(
    trajectory: Trajectory,
    timestamp_s: float,
    tracked_frame: str,
    lidar_to_imu: RigidTransform | None,
) -> SE3Pose:
    pose = trajectory.interpolate_pose(
        timestamp_s,
        tolerance_s=_max_gap(trajectory) + 1e-12,
    ).pose
    return normalize_pose_to_imu(pose_from_sample(pose), tracked_frame, lidar_to_imu)


def _metric_summary(samples: list[dict[str, Any]], field: str) -> dict[str, float]:
    values = [float(row[field]) for row in samples]
    maximum = max(values)
    peak_index = values.index(maximum)
    return {
        "rmse": math.sqrt(sum(value * value for value in values) / len(values)),
        "median": float(statistics.median(values)),
        "p95": float(np.percentile(np.asarray(values, dtype=np.float64), 95.0)),
        "max": maximum,
        "peak_timestamp_s": float(samples[peak_index]["timestamp_s"]),
        "peak_relative_time_s": float(samples[peak_index]["relative_time_s"]),
    }


def _diagnostic_reasons_for_pair(
    manifest: dict[str, Any],
    left_id: str,
    right_id: str,
    *,
    uses_calibration: bool,
    calibration_state: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    algorithms = manifest.get("algorithms", {})
    for algorithm_id in (left_id, right_id):
        algorithm = algorithms.get(algorithm_id, {}) if isinstance(algorithms, dict) else {}
        convention = str(algorithm.get("extrinsic_convention", "")).strip().upper() if isinstance(algorithm, dict) else ""
        if convention != "NONE" and calibration_state not in CONFIRMED_CALIBRATION_STATUSES:
            reasons.append(f"{algorithm_id} estimator calibration status is {calibration_state}")
    if uses_calibration and calibration_state not in CONFIRMED_CALIBRATION_STATUSES:
        reasons.append(f"physical-frame normalization calibration status is {calibration_state}")
    return tuple(dict.fromkeys(reasons))


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def compare_run(run: str | Path, algorithm_ids: Sequence[str] | None = None) -> Path:
    """Compute Relative SE(3) disagreement from one frozen benchmark run.

    The output directory is immutable: an existing ``metrics/relative_se3`` is
    refused so a later comparison cannot silently overwrite scientific evidence.
    """
    run = Path(run).resolve()
    manifest_path = run / "manifest.json"
    manifest = _load_json_object(manifest_path)
    if manifest is None:
        raise RelativeSE3Error(f"missing or invalid run manifest: {manifest_path}")
    algorithms = manifest.get("algorithms", {})
    if not isinstance(algorithms, dict):
        raise RelativeSE3Error("frozen run manifest algorithms must be an object")
    requested = list(algorithm_ids) if algorithm_ids is not None else list(algorithms)
    if len(requested) != len(set(requested)):
        raise RelativeSE3Error("algorithm selection contains duplicates")
    unknown = [algorithm_id for algorithm_id in requested if algorithm_id not in algorithms]
    if unknown:
        raise RelativeSE3Error(f"algorithms are not selected in frozen run: {', '.join(unknown)}")

    output_dir = run / "metrics" / "relative_se3"
    if output_dir.exists():
        raise RelativeSE3Error(f"refusing to overwrite existing Relative SE(3) output: {output_dir}")

    provenance_rows = _load_provenance_rows(run / "metrics" / "runtime_provenance.csv")
    dataset = manifest.get("dataset", {})
    dataset = dataset if isinstance(dataset, dict) else {}
    calibration_state = calibration_status(dataset)
    canonical: RigidTransform | None = None
    canonical_error: str | None = None
    try:
        canonical = canonical_lidar_to_imu(dataset)
    except (TypeError, ValueError, KeyError) as exc:
        canonical_error = str(exc)

    eligible: dict[str, Trajectory] = {}
    algorithm_metadata: dict[str, dict[str, Any]] = {}
    blocked: dict[str, dict[str, Any]] = {}

    for algorithm_id in requested:
        algorithm = algorithms[algorithm_id]
        contract = algorithm.get("trajectory_contract", {}) if isinstance(algorithm, dict) else {}
        tracked = str(contract.get("tracked_frame_physical", "UNKNOWN")).strip().upper() if isinstance(contract, dict) else "UNKNOWN"
        reasons: list[str] = []

        trajectory_path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
        trajectory: Trajectory | None = None
        fingerprint: dict[str, Any] | None = None
        if not trajectory_path.is_file():
            reasons.append(f"standardized trajectory missing: {trajectory_path}")
        else:
            try:
                trajectory = Trajectory.from_csv(trajectory_path)
                fingerprint = _fingerprint(trajectory_path)
            except (OSError, ValueError) as exc:
                reasons.append(f"standardized trajectory invalid: {exc}")

        identity = _load_json_object(
            run / "metadata" / "algorithms" / algorithm_id / "runtime_identity.json"
        )
        identity_status = str(identity.get("identity_status", "UNKNOWN")) if identity else "MISSING"
        if identity_status != "FROZEN":
            reasons.append(f"runtime identity status is {identity_status}")

        provenance = provenance_rows.get(algorithm_id)
        provenance_status = str(provenance.get("status", "MISSING")) if provenance else "MISSING"
        evidence_source = str(provenance.get("identity_evidence_source", "MISSING")) if provenance else "MISSING"
        provenance_identity_status = str(provenance.get("runtime_identity_status", "MISSING")) if provenance else "MISSING"
        provenance_frame_status = str(provenance.get("frame_contract_status", "MISSING")) if provenance else "MISSING"
        if provenance_status != "MATCH":
            reasons.append(f"runtime provenance status is {provenance_status}")
        if evidence_source != "RUNTIME_IDENTITY":
            reasons.append(f"runtime provenance evidence source is {evidence_source}")
        if provenance_identity_status != "FROZEN":
            reasons.append(f"runtime provenance identity status is {provenance_identity_status}")
        if provenance_frame_status != "MATCH":
            reasons.append(f"runtime provenance frame contract status is {provenance_frame_status}")

        frame_audit = _load_json_object(run / "metadata" / "frame_audit" / f"{algorithm_id}.json")
        frame_status = "MISSING"
        if frame_audit is None or not isinstance(contract, dict):
            reasons.append("trajectory frame audit is missing or invalid")
        else:
            try:
                frame_result = classify_frame_audit(contract, frame_audit)
                frame_status = frame_result.status.value
                if frame_status != "MATCH":
                    reasons.extend(frame_result.reasons)
            except ValueError as exc:
                frame_status = "INVALID"
                reasons.append(f"trajectory frame contract invalid: {exc}")

        if tracked not in {"IMU_BODY", "LIDAR"}:
            reasons.append(f"unsupported tracked physical frame: {tracked}")
        uses_calibration = tracked == "LIDAR"
        if uses_calibration and canonical is None:
            reasons.append(
                "LiDAR physical-frame normalization calibration unavailable: "
                + (canonical_error or "unknown calibration error")
            )

        algorithm_metadata[algorithm_id] = {
            "trajectory": fingerprint,
            "runtime_identity_status": identity_status,
            "runtime_provenance_status": provenance_status,
            "identity_evidence_source": evidence_source,
            "frame_audit_status": frame_status,
            "tracked_frame_physical": tracked,
            "target_frame_physical": TARGET_PHYSICAL_FRAME,
            "physical_frame_normalization_uses_calibration": uses_calibration,
            "calibration_status": calibration_state,
        }
        if reasons or trajectory is None:
            blocked[algorithm_id] = {
                "reasons": list(dict.fromkeys(reasons)),
                **algorithm_metadata[algorithm_id],
            }
        else:
            eligible[algorithm_id] = trajectory

    if len(eligible) < 2:
        detail = "; ".join(
            f"{algorithm_id}: {'; '.join(record['reasons'])}"
            for algorithm_id, record in sorted(blocked.items())
        )
        raise RelativeSE3Error(
            "Relative SE(3) requires at least two eligible algorithms"
            + (f"; {detail}" if detail else "")
        )

    try:
        common_start, common_end, evaluation_times = common_evaluation_times(eligible)
    except ValueError as exc:
        raise RelativeSE3Error(str(exc)) from exc

    normalized: dict[str, list[SE3Pose]] = {}
    normalized_rows: list[dict[str, Any]] = []
    for algorithm_id in sorted(eligible):
        trajectory = eligible[algorithm_id]
        tracked = algorithm_metadata[algorithm_id]["tracked_frame_physical"]
        transform = canonical if tracked == "LIDAR" else None
        try:
            start_pose = _interpolated_world_pose(trajectory, common_start, tracked, transform)
            motions = [
                relative_pose(
                    start_pose,
                    _interpolated_world_pose(trajectory, timestamp, tracked, transform),
                )
                for timestamp in evaluation_times
            ]
        except (ValueError, TypeError) as exc:
            raise RelativeSE3Error(f"failed to normalize {algorithm_id}: {exc}") from exc
        normalized[algorithm_id] = motions
        for timestamp, motion in zip(evaluation_times, motions):
            qx, qy, qz, qw = rotation_to_quaternion(motion.rotation)
            normalized_rows.append(
                {
                    "algorithm_id": algorithm_id,
                    "timestamp_s": timestamp,
                    "relative_time_s": timestamp - common_start,
                    "x_m": motion.translation[0],
                    "y_m": motion.translation[1],
                    "z_m": motion.translation[2],
                    "qx": qx,
                    "qy": qy,
                    "qz": qz,
                    "qw": qw,
                    "tracked_frame_physical": tracked,
                    "target_frame_physical": TARGET_PHYSICAL_FRAME,
                }
            )

    pair_sample_rows: list[dict[str, Any]] = []
    pair_summary_rows: list[dict[str, Any]] = []
    onset_rows: list[dict[str, Any]] = []

    for left_id, right_id in combinations(sorted(eligible), 2):
        samples: list[dict[str, Any]] = []
        for timestamp, left_pose, right_pose in zip(
            evaluation_times, normalized[left_id], normalized[right_id]
        ):
            left_t = _translation_vector(left_pose.translation)
            right_t = _translation_vector(right_pose.translation)
            delta = left_t - right_t
            left_r = _rotation_matrix(left_pose.rotation)
            right_r = _rotation_matrix(right_pose.rotation)
            rotation_rad = rotation_geodesic_rad(left_r.T @ right_r)
            row = {
                "left_algorithm_id": left_id,
                "right_algorithm_id": right_id,
                "timestamp_s": timestamp,
                "relative_time_s": timestamp - common_start,
                "dx_m": float(delta[0]),
                "dy_m": float(delta[1]),
                "dz_m": float(delta[2]),
                "xy_m": float(math.hypot(delta[0], delta[1])),
                "z_abs_m": float(abs(delta[2])),
                "xyz_m": float(np.linalg.norm(delta)),
                "rotation_rad": rotation_rad,
                "rotation_deg": math.degrees(rotation_rad),
            }
            samples.append(row)
            pair_sample_rows.append(row)

        xy = _metric_summary(samples, "xy_m")
        z_abs = _metric_summary(samples, "z_abs_m")
        xyz = _metric_summary(samples, "xyz_m")
        rotation = _metric_summary(samples, "rotation_deg")
        uses_calibration = bool(
            algorithm_metadata[left_id]["physical_frame_normalization_uses_calibration"]
            or algorithm_metadata[right_id]["physical_frame_normalization_uses_calibration"]
        )
        diagnostic_reasons = _diagnostic_reasons_for_pair(
            manifest,
            left_id,
            right_id,
            uses_calibration=uses_calibration,
            calibration_state=calibration_state,
        )
        pair_summary_rows.append(
            {
                "left_algorithm_id": left_id,
                "right_algorithm_id": right_id,
                "overlap_start_s": common_start,
                "overlap_end_s": common_end,
                "overlap_duration_s": common_end - common_start,
                "sample_period_s": SAMPLE_PERIOD_S,
                "sample_count": len(samples),
                "xy_rmse_m": xy["rmse"],
                "xy_median_m": xy["median"],
                "xy_p95_m": xy["p95"],
                "xy_max_m": xy["max"],
                "xy_peak_timestamp_s": xy["peak_timestamp_s"],
                "xy_peak_relative_time_s": xy["peak_relative_time_s"],
                "z_abs_rmse_m": z_abs["rmse"],
                "z_abs_median_m": z_abs["median"],
                "z_abs_p95_m": z_abs["p95"],
                "z_abs_max_m": z_abs["max"],
                "z_abs_peak_timestamp_s": z_abs["peak_timestamp_s"],
                "z_abs_peak_relative_time_s": z_abs["peak_relative_time_s"],
                "xyz_rmse_m": xyz["rmse"],
                "xyz_median_m": xyz["median"],
                "xyz_p95_m": xyz["p95"],
                "xyz_max_m": xyz["max"],
                "xyz_peak_timestamp_s": xyz["peak_timestamp_s"],
                "xyz_peak_relative_time_s": xyz["peak_relative_time_s"],
                "rotation_rmse_deg": rotation["rmse"],
                "rotation_median_deg": rotation["median"],
                "rotation_p95_deg": rotation["p95"],
                "rotation_max_deg": rotation["max"],
                "rotation_peak_timestamp_s": rotation["peak_timestamp_s"],
                "rotation_peak_relative_time_s": rotation["peak_relative_time_s"],
                "physical_frame_normalization_uses_calibration": uses_calibration,
                "calibration_status": calibration_state,
                "scientific_status": "DIAGNOSTIC_ONLY" if diagnostic_reasons else "DESCRIPTIVE_NO_GROUND_TRUTH",
                "diagnostic_reasons": ";".join(diagnostic_reasons),
            }
        )

        relative_times = [float(row["relative_time_s"]) for row in samples]
        for metric in ("xy_m", "z_abs_m", "xyz_m"):
            values = [float(row[metric]) for row in samples]
            for threshold in TRANSLATION_THRESHOLDS_M:
                onset = sustained_onset(
                    relative_times,
                    values,
                    threshold=threshold,
                    sustain_samples=SUSTAIN_SAMPLES,
                )
                onset_rows.append(
                    {
                        "left_algorithm_id": left_id,
                        "right_algorithm_id": right_id,
                        "metric": metric,
                        "threshold": threshold,
                        "unit": "m",
                        "sustain_samples": SUSTAIN_SAMPLES,
                        "crossed": onset.crossed,
                        "onset_timestamp_s": None if onset.onset_relative_time_s is None else common_start + onset.onset_relative_time_s,
                        "onset_relative_time_s": onset.onset_relative_time_s,
                        "onset_value": onset.onset_value,
                    }
                )
        rotation_values = [float(row["rotation_deg"]) for row in samples]
        for threshold in ROTATION_THRESHOLDS_DEG:
            onset = sustained_onset(
                relative_times,
                rotation_values,
                threshold=threshold,
                sustain_samples=SUSTAIN_SAMPLES,
            )
            onset_rows.append(
                {
                    "left_algorithm_id": left_id,
                    "right_algorithm_id": right_id,
                    "metric": "rotation_deg",
                    "threshold": threshold,
                    "unit": "deg",
                    "sustain_samples": SUSTAIN_SAMPLES,
                    "crossed": onset.crossed,
                    "onset_timestamp_s": None if onset.onset_relative_time_s is None else common_start + onset.onset_relative_time_s,
                    "onset_relative_time_s": onset.onset_relative_time_s,
                    "onset_value": onset.onset_value,
                }
            )

    metadata = {
        "schema": RELATIVE_SE3_SCHEMA,
        "schema_version": 1,
        "run": str(run),
        "run_id": manifest.get("run_id", run.name),
        "requested_algorithms": requested,
        "eligible_algorithms": sorted(eligible),
        "blocked_algorithms": blocked,
        "algorithms": algorithm_metadata,
        "target_physical_frame": TARGET_PHYSICAL_FRAME,
        "common_start_s": common_start,
        "common_end_s": common_end,
        "sample_period_s": SAMPLE_PERIOD_S,
        "sustain_samples": SUSTAIN_SAMPLES,
        "translation_thresholds_m": list(TRANSLATION_THRESHOLDS_M),
        "rotation_thresholds_deg": list(ROTATION_THRESHOLDS_DEG),
        "world_gauge_normalization": "T(t0)^-1 * T(t)",
        "rotation_disagreement": "SO3_GEODESIC",
        "ground_truth": "NONE",
        "terminology": "PAIRWISE_DISAGREEMENT",
        "calibration_status": calibration_state,
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(output_dir / "normalized_motion.csv", NORMALIZED_MOTION_FIELDS, normalized_rows)
    _write_csv(output_dir / "pairwise_samples.csv", PAIRWISE_SAMPLE_FIELDS, pair_sample_rows)
    _write_csv(output_dir / "pairwise_summary.csv", PAIRWISE_SUMMARY_FIELDS, pair_summary_rows)
    _write_csv(output_dir / "onset_thresholds.csv", ONSET_FIELDS, onset_rows)
    return output_dir
