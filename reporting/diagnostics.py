#!/usr/bin/env python3
"""Descriptive estimator-divergence diagnostics without ground-truth claims.

The functions in this module consume standardized trajectories. Pairwise values
are deliberately named disagreement rather than error/accuracy because no
reference trajectory is assumed.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable

import numpy as np

from benchmark_base.lib.display_alignment import (
    apply_display_transform_xyz,
    compute_display_alignment,
    normalize_display_alignment_mode,
)
from benchmark_base.lib.trajectory import PoseSample, Trajectory
from reporting.contracts import collect_summary


@dataclass(frozen=True)
class TrajectoryDiagnostics:
    samples: int
    duration_s: float
    path_length_m: float
    delta_x_m: float
    delta_y_m: float
    delta_z_m: float
    z_range_m: float
    roll_range_rad: float
    pitch_range_rad: float
    yaw_change_rad: float
    warmup_s: float


@dataclass(frozen=True)
class DisagreementSample:
    timestamp_s: float
    relative_time_s: float
    xy_m: float
    z_abs_m: float
    xyz_m: float


@dataclass(frozen=True)
class PairwiseDisagreement:
    alignment_mode: str
    warmup_s: float
    overlap_start_s: float
    overlap_end_s: float
    overlap_duration_s: float
    sample_period_s: float
    sample_count: int
    xy_rmse_m: float
    xy_median_m: float
    xy_max_m: float
    z_rmse_m: float
    z_median_m: float
    z_max_m: float
    xyz_rmse_m: float
    xyz_median_m: float
    xyz_max_m: float
    samples: tuple[DisagreementSample, ...]


@dataclass(frozen=True)
class AlgorithmDiagnosticRow:
    algorithm_id: str
    trajectory_status: str
    trajectory_samples: int | None
    duration_s: float | None
    path_length_m: float | None
    delta_x_m: float | None
    delta_y_m: float | None
    delta_z_m: float | None
    z_range_m: float | None
    roll_range_rad: float | None
    pitch_range_rad: float | None
    yaw_change_rad: float | None
    matched_scans: int | None
    unmatched_scans: int | None
    unified_map_points: int | None
    run_status: str
    calibration_status: str
    warmup_s: float


@dataclass(frozen=True)
class PairwiseDiagnosticRow:
    left_algorithm_id: str
    right_algorithm_id: str
    alignment_mode: str
    warmup_s: float
    overlap_duration_s: float
    sample_period_s: float
    sample_count: int
    xy_rmse_m: float
    xy_median_m: float
    xy_max_m: float
    z_rmse_m: float
    z_median_m: float
    z_max_m: float
    xyz_rmse_m: float
    xyz_median_m: float
    xyz_max_m: float


def _wrapped_delta(current: float, previous: float) -> float:
    return math.atan2(math.sin(current - previous), math.cos(current - previous))


def _cumulative_angle_change(values: Iterable[float]) -> float:
    angles = tuple(float(value) for value in values)
    if len(angles) < 2:
        return 0.0
    return sum(_wrapped_delta(current, previous) for previous, current in zip(angles, angles[1:]))


def _max_gap(trajectory: Trajectory) -> float:
    return max(b - a for a, b in zip(trajectory.timestamps, trajectory.timestamps[1:]))


def _trimmed_samples(trajectory: Trajectory, warmup_s: float) -> tuple[PoseSample, ...]:
    if warmup_s < 0.0 or not math.isfinite(warmup_s):
        raise ValueError("warmup_s must be a finite non-negative value")
    if warmup_s == 0.0:
        return trajectory.samples
    boundary = trajectory.timestamps[0] + warmup_s
    if boundary >= trajectory.timestamps[-1]:
        raise ValueError("warmup_s removes the usable trajectory interval")
    match = trajectory.interpolate_pose(boundary, tolerance_s=_max_gap(trajectory) + 1e-12)
    values = [match.pose]
    values.extend(sample for sample in trajectory.samples if sample.timestamp_s > boundary + 1e-12)
    if len(values) < 2:
        raise ValueError("warmup_s leaves fewer than two trajectory samples")
    return tuple(values)


def trajectory_diagnostics(trajectory: Trajectory, *, warmup_s: float = 0.0) -> TrajectoryDiagnostics:
    samples = _trimmed_samples(trajectory, warmup_s)
    path_length = 0.0
    for left, right in zip(samples, samples[1:]):
        path_length += math.sqrt(
            (right.x_m - left.x_m) ** 2
            + (right.y_m - left.y_m) ** 2
            + (right.z_m - left.z_m) ** 2
        )
    first, last = samples[0], samples[-1]
    z_values = [sample.z_m for sample in samples]
    roll_values = [sample.roll_rad for sample in samples]
    pitch_values = [sample.pitch_rad for sample in samples]
    yaw_values = [sample.yaw_rad for sample in samples]
    return TrajectoryDiagnostics(
        samples=len(samples),
        duration_s=last.timestamp_s - first.timestamp_s,
        path_length_m=path_length,
        delta_x_m=last.x_m - first.x_m,
        delta_y_m=last.y_m - first.y_m,
        delta_z_m=last.z_m - first.z_m,
        z_range_m=max(z_values) - min(z_values),
        roll_range_rad=max(roll_values) - min(roll_values),
        pitch_range_rad=max(pitch_values) - min(pitch_values),
        yaw_change_rad=_cumulative_angle_change(yaw_values),
        warmup_s=float(warmup_s),
    )


def _sample_times(start: float, end: float, period: float) -> tuple[float, ...]:
    if period <= 0.0 or not math.isfinite(period):
        raise ValueError("sample_period_s must be a finite positive value")
    count = int(math.floor((end - start) / period + 1e-12))
    values = [start + index * period for index in range(count + 1)]
    if not values or end - values[-1] > 1e-9:
        values.append(end)
    else:
        values[-1] = end if abs(values[-1] - end) <= 1e-9 else values[-1]
    return tuple(values)


def _aligned_xyz(pose: PoseSample, matrix: np.ndarray) -> tuple[float, float, float]:
    value = apply_display_transform_xyz(
        np.asarray([[pose.x_m, pose.y_m, pose.z_m]], dtype=np.float64), matrix
    )[0]
    return float(value[0]), float(value[1]), float(value[2])


def _rmse(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


def pairwise_disagreement(
    left: Trajectory,
    right: Trajectory,
    *,
    sample_period_s: float = 0.1,
    alignment_mode: str = "START_XY_YAW",
    warmup_s: float = 0.0,
) -> PairwiseDisagreement:
    canonical = normalize_display_alignment_mode(alignment_mode)
    if warmup_s < 0.0 or not math.isfinite(warmup_s):
        raise ValueError("warmup_s must be a finite non-negative value")

    overlap_start = max(left.timestamps[0] + warmup_s, right.timestamps[0] + warmup_s)
    overlap_end = min(left.timestamps[-1], right.timestamps[-1])
    if overlap_end <= overlap_start:
        raise ValueError("trajectories have no usable common time interval")

    left_matrix = compute_display_alignment(left.samples[0], canonical)
    right_matrix = compute_display_alignment(right.samples[0], canonical)
    left_tolerance = _max_gap(left) + 1e-12
    right_tolerance = _max_gap(right) + 1e-12

    rows: list[DisagreementSample] = []
    xy_values: list[float] = []
    z_values: list[float] = []
    xyz_values: list[float] = []
    for timestamp in _sample_times(overlap_start, overlap_end, sample_period_s):
        lpose = left.interpolate_pose(timestamp, tolerance_s=left_tolerance).pose
        rpose = right.interpolate_pose(timestamp, tolerance_s=right_tolerance).pose
        lx, ly, lz = _aligned_xyz(lpose, left_matrix)
        rx, ry, rz = _aligned_xyz(rpose, right_matrix)
        dx, dy, dz = lx - rx, ly - ry, lz - rz
        xy = math.hypot(dx, dy)
        z_abs = abs(dz)
        xyz = math.sqrt(dx * dx + dy * dy + dz * dz)
        xy_values.append(xy)
        z_values.append(z_abs)
        xyz_values.append(xyz)
        rows.append(
            DisagreementSample(
                timestamp_s=timestamp,
                relative_time_s=timestamp - overlap_start,
                xy_m=xy,
                z_abs_m=z_abs,
                xyz_m=xyz,
            )
        )

    if len(rows) < 2:
        raise ValueError("pairwise comparison produced fewer than two common samples")

    return PairwiseDisagreement(
        alignment_mode=canonical,
        warmup_s=float(warmup_s),
        overlap_start_s=overlap_start,
        overlap_end_s=overlap_end,
        overlap_duration_s=overlap_end - overlap_start,
        sample_period_s=float(sample_period_s),
        sample_count=len(rows),
        xy_rmse_m=_rmse(xy_values),
        xy_median_m=float(statistics.median(xy_values)),
        xy_max_m=max(xy_values),
        z_rmse_m=_rmse(z_values),
        z_median_m=float(statistics.median(z_values)),
        z_max_m=max(z_values),
        xyz_rmse_m=_rmse(xyz_values),
        xyz_median_m=float(statistics.median(xyz_values)),
        xyz_max_m=max(xyz_values),
        samples=tuple(rows),
    )


def _calibration_status(manifest: dict, algorithm_id: str) -> str:
    algorithm = manifest.get("algorithms", {}).get(algorithm_id, {})
    if isinstance(algorithm, dict):
        profile = algorithm.get("sensor_profile", {})
        if str(algorithm.get("extrinsic_convention", "")).upper() == "NONE":
            return "NOT_REQUIRED"
        if isinstance(profile, dict) and profile.get("imu") is False:
            return "NOT_REQUIRED"
    dataset = manifest.get("dataset", {})
    calibration = dataset.get("calibration", {}) if isinstance(dataset, dict) else {}
    if not isinstance(calibration, dict):
        return "UNKNOWN"
    return str(calibration.get("status", "UNKNOWN")).strip().upper() or "UNKNOWN"


def collect_run_diagnostics(
    run: str | Path,
    algorithm_ids: list[str],
    *,
    warmup_s: float = 0.0,
    alignment_mode: str = "START_XY_YAW",
    sample_period_s: float = 0.1,
) -> tuple[list[AlgorithmDiagnosticRow], list[PairwiseDiagnosticRow], dict[tuple[str, str], PairwiseDisagreement]]:
    run = Path(run)
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    canonical = normalize_display_alignment_mode(alignment_mode)
    trajectories: dict[str, Trajectory] = {}
    rows: list[AlgorithmDiagnosticRow] = []

    for algorithm_id in algorithm_ids:
        summary = collect_summary(run, algorithm_id)
        trajectory_path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
        diagnostic: TrajectoryDiagnostics | None = None
        trajectory_status = "MISSING"
        if trajectory_path.is_file():
            try:
                trajectory = Trajectory.from_csv(trajectory_path)
                diagnostic = trajectory_diagnostics(trajectory, warmup_s=warmup_s)
                trajectories[algorithm_id] = trajectory
                trajectory_status = "AVAILABLE"
            except Exception:
                trajectory_status = "INVALID"
        rows.append(
            AlgorithmDiagnosticRow(
                algorithm_id=algorithm_id,
                trajectory_status=trajectory_status,
                trajectory_samples=None if diagnostic is None else diagnostic.samples,
                duration_s=None if diagnostic is None else diagnostic.duration_s,
                path_length_m=None if diagnostic is None else diagnostic.path_length_m,
                delta_x_m=None if diagnostic is None else diagnostic.delta_x_m,
                delta_y_m=None if diagnostic is None else diagnostic.delta_y_m,
                delta_z_m=None if diagnostic is None else diagnostic.delta_z_m,
                z_range_m=None if diagnostic is None else diagnostic.z_range_m,
                roll_range_rad=None if diagnostic is None else diagnostic.roll_range_rad,
                pitch_range_rad=None if diagnostic is None else diagnostic.pitch_range_rad,
                yaw_change_rad=None if diagnostic is None else diagnostic.yaw_change_rad,
                matched_scans=summary.matched_scans,
                unmatched_scans=summary.unmatched_scans,
                unified_map_points=summary.map_points,
                run_status=summary.run_status,
                calibration_status=_calibration_status(manifest, algorithm_id),
                warmup_s=float(warmup_s),
            )
        )

    pair_rows: list[PairwiseDiagnosticRow] = []
    details: dict[tuple[str, str], PairwiseDisagreement] = {}
    for left_id, right_id in combinations(sorted(trajectories), 2):
        try:
            result = pairwise_disagreement(
                trajectories[left_id],
                trajectories[right_id],
                sample_period_s=sample_period_s,
                alignment_mode=canonical,
                warmup_s=warmup_s,
            )
        except ValueError:
            continue
        details[(left_id, right_id)] = result
        pair_rows.append(
            PairwiseDiagnosticRow(
                left_algorithm_id=left_id,
                right_algorithm_id=right_id,
                alignment_mode=result.alignment_mode,
                warmup_s=result.warmup_s,
                overlap_duration_s=result.overlap_duration_s,
                sample_period_s=result.sample_period_s,
                sample_count=result.sample_count,
                xy_rmse_m=result.xy_rmse_m,
                xy_median_m=result.xy_median_m,
                xy_max_m=result.xy_max_m,
                z_rmse_m=result.z_rmse_m,
                z_median_m=result.z_median_m,
                z_max_m=result.z_max_m,
                xyz_rmse_m=result.xyz_rmse_m,
                xyz_median_m=result.xyz_median_m,
                xyz_max_m=result.xyz_max_m,
            )
        )
    return rows, pair_rows, details


def _write_dataclass_csv(path: Path, rows: list[object], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_run_diagnostics(
    run: str | Path,
    algorithm_rows: list[AlgorithmDiagnosticRow],
    pair_rows: list[PairwiseDiagnosticRow],
) -> tuple[Path, Path]:
    metrics = Path(run) / "metrics"
    smoke = metrics / "smoke_diagnostics.csv"
    pairwise = metrics / "pairwise_disagreement.csv"
    _write_dataclass_csv(smoke, algorithm_rows, list(AlgorithmDiagnosticRow.__dataclass_fields__))
    _write_dataclass_csv(pairwise, pair_rows, list(PairwiseDiagnosticRow.__dataclass_fields__))
    return smoke, pairwise
