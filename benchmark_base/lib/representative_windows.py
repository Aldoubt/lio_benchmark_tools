#!/usr/bin/env python3
"""Estimator-independent representative-window selection contracts.

This module is deliberately ROS-independent. Target-machine bag readers turn
raw LiDAR/IMU messages into compact raw-sensor features; this module aggregates,
validates, ranks, and selects those records deterministically.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import math
from typing import Any, Iterable, Sequence

import numpy as np


SCHEMA_VERSION = 1
WINDOW_DURATION_S = 45.0
WINDOW_STRIDE_S = 5.0
POST_INITIALIZATION_GUARD_S = 15.0
MIN_LIDAR_SCANS_PER_WINDOW = 100
MIN_IMU_SAMPLES_PER_WINDOW = 500
LIDAR_POINT_STEP = 20
LIDAR_NEAR_RANGE_M = 0.5
RANGE_HISTOGRAM_MAX_M = 30.0
RANGE_HISTOGRAM_BINS = 32

SELECTION_LABELS = (
    "initialization",
    "high_angular_motion",
    "geometric_degeneracy_candidate",
    "steady_translation_candidate",
)


class RepresentativeWindowError(ValueError):
    """Raised when the frozen representative-window contract cannot be met."""


@dataclass(frozen=True)
class LidarScanFeature:
    timestamp_s: float
    range_histogram: np.ndarray
    geometric_degeneracy_score: float


@dataclass(frozen=True)
class ImuFeatureSample:
    timestamp_s: float
    angular_speed_rad_s: float
    acceleration_norm_native: float


@dataclass(frozen=True)
class WindowFeature:
    start_offset_s: float
    duration_s: float
    lidar_scan_count: int
    imu_sample_count: int
    gyro_rms_rad_s: float
    gyro_p95_rad_s: float
    accel_dynamic_rms_native: float
    scene_change_mean: float
    geometric_degeneracy_median: float
    geometric_degeneracy_p90: float
    valid: bool

    @property
    def end_offset_s(self) -> float:
        return self.start_offset_s + self.duration_s


@dataclass(frozen=True)
class SelectedWindow:
    label: str
    start_offset_s: float
    duration_s: float
    score: float | None
    feature: WindowFeature

    @property
    def end_offset_s(self) -> float:
        return self.start_offset_s + self.duration_s


def _finite_vector(values: np.ndarray) -> np.ndarray:
    return values[np.all(np.isfinite(values), axis=1)]


def lidar_scan_feature(timestamp_s: float, xyz: np.ndarray) -> LidarScanFeature:
    """Build the frozen raw-geometry signature for one LiDAR scan."""
    timestamp = float(timestamp_s)
    points = np.asarray(xyz, dtype=np.float64)
    if not math.isfinite(timestamp):
        raise RepresentativeWindowError("LiDAR feature timestamp must be finite")
    if points.ndim != 2 or points.shape[1] < 3:
        raise RepresentativeWindowError("LiDAR feature points must be an Nx3 array")
    points = _finite_vector(points[:, :3])
    if len(points) < 3:
        raise RepresentativeWindowError("LiDAR feature requires at least three finite points")

    ranges = np.linalg.norm(points, axis=1)
    in_histogram = ranges[
        (ranges >= LIDAR_NEAR_RANGE_M) & (ranges <= RANGE_HISTOGRAM_MAX_M)
    ]
    counts, _ = np.histogram(
        in_histogram,
        bins=RANGE_HISTOGRAM_BINS,
        range=(LIDAR_NEAR_RANGE_M, RANGE_HISTOGRAM_MAX_M),
    )
    histogram = counts.astype(np.float64)
    total = float(np.sum(histogram))
    if total <= 0.0:
        raise RepresentativeWindowError("LiDAR feature has no points in histogram range")
    histogram /= total

    centered = points - np.mean(points, axis=0)
    covariance = (centered.T @ centered) / float(len(points))
    eigenvalues = np.linalg.eigvalsh(covariance)
    eigenvalues = np.maximum(eigenvalues, 0.0)[::-1]
    eigen_sum = float(np.sum(eigenvalues))
    if eigen_sum <= np.finfo(np.float64).eps:
        degeneracy = 1.0
    else:
        probabilities = eigenvalues / eigen_sum
        positive = probabilities[probabilities > 0.0]
        entropy = -float(np.sum(positive * np.log(positive))) / math.log(3.0)
        degeneracy = min(1.0, max(0.0, 1.0 - entropy))

    histogram.setflags(write=False)
    return LidarScanFeature(timestamp, histogram, degeneracy)


def _window_grid(analysis_end_s: float) -> tuple[float, ...]:
    end = float(analysis_end_s)
    if not math.isfinite(end) or end < WINDOW_DURATION_S:
        raise RepresentativeWindowError(
            f"raw sensor interval must cover at least {WINDOW_DURATION_S} s"
        )
    maximum_start = end - WINDOW_DURATION_S
    count = int(math.floor(maximum_start / WINDOW_STRIDE_S + 1e-12))
    return tuple(index * WINDOW_STRIDE_S for index in range(count + 1))


def build_window_features(
    lidar_samples: Sequence[LidarScanFeature],
    imu_samples: Sequence[ImuFeatureSample],
    *,
    analysis_end_s: float,
) -> tuple[WindowFeature, ...]:
    """Aggregate raw sensor features on the frozen 45 s / 5 s candidate grid."""
    lidar = tuple(sorted(lidar_samples, key=lambda item: item.timestamp_s))
    imu = tuple(sorted(imu_samples, key=lambda item: item.timestamp_s))
    if not lidar or not imu:
        raise RepresentativeWindowError("raw LiDAR and IMU feature streams are required")
    if any(not math.isfinite(item.timestamp_s) for item in lidar):
        raise RepresentativeWindowError("LiDAR feature timestamps must be finite")
    if any(
        not math.isfinite(value)
        for item in imu
        for value in (item.timestamp_s, item.angular_speed_rad_s, item.acceleration_norm_native)
    ):
        raise RepresentativeWindowError("IMU feature samples must be finite")

    records: list[WindowFeature] = []
    for start in _window_grid(analysis_end_s):
        end = start + WINDOW_DURATION_S
        lidar_window = [item for item in lidar if start <= item.timestamp_s < end]
        imu_window = [item for item in imu if start <= item.timestamp_s < end]

        gyro = np.asarray([item.angular_speed_rad_s for item in imu_window], dtype=np.float64)
        acceleration = np.asarray(
            [item.acceleration_norm_native for item in imu_window], dtype=np.float64
        )
        degeneracy = np.asarray(
            [item.geometric_degeneracy_score for item in lidar_window], dtype=np.float64
        )
        scene_change = np.asarray(
            [
                0.5
                * float(
                    np.sum(
                        np.abs(
                            right.range_histogram - left.range_histogram
                        )
                    )
                )
                for left, right in zip(lidar_window, lidar_window[1:])
            ],
            dtype=np.float64,
        )

        gyro_rms = float(np.sqrt(np.mean(np.square(gyro)))) if len(gyro) else 0.0
        gyro_p95 = float(np.percentile(gyro, 95.0)) if len(gyro) else 0.0
        if len(acceleration):
            acceleration_median = float(np.median(acceleration))
            accel_dynamic = float(
                np.sqrt(np.mean(np.square(acceleration - acceleration_median)))
            )
        else:
            accel_dynamic = 0.0
        scene_mean = float(np.mean(scene_change)) if len(scene_change) else 0.0
        degeneracy_median = float(np.median(degeneracy)) if len(degeneracy) else 0.0
        degeneracy_p90 = float(np.percentile(degeneracy, 90.0)) if len(degeneracy) else 0.0
        valid = (
            len(lidar_window) >= MIN_LIDAR_SCANS_PER_WINDOW
            and len(imu_window) >= MIN_IMU_SAMPLES_PER_WINDOW
            and len(scene_change) > 0
            and len(degeneracy) > 0
        )
        records.append(
            WindowFeature(
                start_offset_s=start,
                duration_s=WINDOW_DURATION_S,
                lidar_scan_count=len(lidar_window),
                imu_sample_count=len(imu_window),
                gyro_rms_rad_s=gyro_rms,
                gyro_p95_rad_s=gyro_p95,
                accel_dynamic_rms_native=accel_dynamic,
                scene_change_mean=scene_mean,
                geometric_degeneracy_median=degeneracy_median,
                geometric_degeneracy_p90=degeneracy_p90,
                valid=valid,
            )
        )
    return tuple(records)


def validate_selector_manifest(manifest: dict[str, Any]) -> None:
    """Require a schema-v2 full-bag selector run with source refs preserved."""
    if int(manifest.get("schema_version", 0)) != 2:
        raise RepresentativeWindowError("representative-window selector requires schema-v2 run")
    if not str(manifest.get("dataset_ref", "")).strip():
        raise RepresentativeWindowError("selector run is missing dataset_ref")
    algorithm_refs = manifest.get("algorithm_refs")
    if not isinstance(algorithm_refs, list) or not algorithm_refs:
        raise RepresentativeWindowError("selector run is missing algorithm_refs")
    replay = manifest.get("replay")
    if not isinstance(replay, dict):
        raise RepresentativeWindowError("selector run requires frozen full-bag replay")
    rate = float(replay.get("rate", 1.0))
    start = float(replay.get("start_offset_s", 0.0))
    duration = replay.get("duration_s")
    if abs(rate - 1.0) > 1e-12 or abs(start) > 1e-12 or duration is not None:
        raise RepresentativeWindowError(
            "representative-window selector requires full-bag replay: rate=1, start=0, duration=null"
        )


def build_child_experiment_config(
    manifest: dict[str, Any], selected: SelectedWindow
) -> dict[str, Any]:
    """Create a normal V2 child config that only changes name/replay interval."""
    validate_selector_manifest(manifest)
    if selected.label not in SELECTION_LABELS:
        raise RepresentativeWindowError(f"unknown representative-window label: {selected.label}")
    config: dict[str, Any] = {
        "schema_version": 2,
        "name": f"{manifest.get('name', 'representative_window')}__{selected.label}",
        "workspace": str(manifest["workspace"]),
        "output_root": str(manifest["output_root"]),
        "dataset": str(manifest["dataset_ref"]),
        "algorithms": copy.deepcopy(manifest["algorithm_refs"]),
        "replay": {
            "rate": 1.0,
            "start_offset_s": float(selected.start_offset_s),
            "duration_s": WINDOW_DURATION_S,
        },
    }
    for key in ("execution_overrides", "runtime_overlays", "standardization"):
        if key in manifest:
            config[key] = copy.deepcopy(manifest[key])
    return config


def _validate_feature(value: WindowFeature) -> None:
    numeric = (
        value.start_offset_s,
        value.duration_s,
        value.gyro_rms_rad_s,
        value.gyro_p95_rad_s,
        value.accel_dynamic_rms_native,
        value.scene_change_mean,
        value.geometric_degeneracy_median,
        value.geometric_degeneracy_p90,
    )
    if any(not math.isfinite(item) for item in numeric):
        raise RepresentativeWindowError("window features must be finite")
    if value.start_offset_s < 0.0:
        raise RepresentativeWindowError("window start offsets must be non-negative")
    if abs(value.duration_s - WINDOW_DURATION_S) > 1e-9:
        raise RepresentativeWindowError(
            f"Representative Window V1 duration must be {WINDOW_DURATION_S} s"
        )
    if value.lidar_scan_count < 0 or value.imu_sample_count < 0:
        raise RepresentativeWindowError("window sample counts must be non-negative")


def _overlap(left: WindowFeature | SelectedWindow, right: WindowFeature | SelectedWindow) -> bool:
    return max(left.start_offset_s, right.start_offset_s) < min(
        left.end_offset_s, right.end_offset_s
    ) - 1e-12


def _available(
    features: Iterable[WindowFeature], selected: Sequence[SelectedWindow]
) -> list[WindowFeature]:
    return [
        feature
        for feature in features
        if feature.valid and not any(_overlap(feature, chosen) for chosen in selected)
    ]


def _rank01(values: Sequence[float], *, high_is_good: bool) -> list[float]:
    """Return deterministic [0,1] ranks; equal values receive equal ranks."""
    if not values:
        return []
    if len(values) == 1:
        return [1.0]
    unique = sorted(set(float(value) for value in values))
    if len(unique) == 1:
        return [1.0 for _ in values]
    denominator = float(len(unique) - 1)
    rank_by_value = {value: index / denominator for index, value in enumerate(unique)}
    if high_is_good:
        return [rank_by_value[float(value)] for value in values]
    return [1.0 - rank_by_value[float(value)] for value in values]


def _choose_high_angular(candidates: Sequence[WindowFeature]) -> SelectedWindow:
    if not candidates:
        raise RepresentativeWindowError("cannot select high_angular_motion window")
    feature = min(candidates, key=lambda item: (-item.gyro_p95_rad_s, item.start_offset_s))
    return SelectedWindow(
        label="high_angular_motion",
        start_offset_s=feature.start_offset_s,
        duration_s=feature.duration_s,
        score=feature.gyro_p95_rad_s,
        feature=feature,
    )


def _choose_geometric(candidates: Sequence[WindowFeature]) -> SelectedWindow:
    if not candidates:
        raise RepresentativeWindowError("cannot select geometric_degeneracy_candidate window")
    scene_values = np.asarray([item.scene_change_mean for item in candidates], dtype=np.float64)
    lower_quartile = float(np.quantile(scene_values, 0.25))
    moving = [item for item in candidates if item.scene_change_mean + 1e-15 >= lower_quartile]
    pool = moving or list(candidates)
    feature = min(
        pool,
        key=lambda item: (
            -item.geometric_degeneracy_median,
            -item.scene_change_mean,
            item.start_offset_s,
        ),
    )
    return SelectedWindow(
        label="geometric_degeneracy_candidate",
        start_offset_s=feature.start_offset_s,
        duration_s=feature.duration_s,
        score=feature.geometric_degeneracy_median,
        feature=feature,
    )


def _choose_steady(candidates: Sequence[WindowFeature]) -> SelectedWindow:
    if not candidates:
        raise RepresentativeWindowError("cannot select steady_translation_candidate window")
    scene_rank = _rank01([item.scene_change_mean for item in candidates], high_is_good=True)
    gyro_rank = _rank01([item.gyro_rms_rad_s for item in candidates], high_is_good=False)
    accel_rank = _rank01(
        [item.accel_dynamic_rms_native for item in candidates], high_is_good=False
    )
    scored = [
        (0.60 * scene + 0.30 * gyro + 0.10 * accel, feature)
        for feature, scene, gyro, accel in zip(candidates, scene_rank, gyro_rank, accel_rank)
    ]
    score, feature = min(scored, key=lambda item: (-item[0], item[1].start_offset_s))
    return SelectedWindow(
        label="steady_translation_candidate",
        start_offset_s=feature.start_offset_s,
        duration_s=feature.duration_s,
        score=float(score),
        feature=feature,
    )


def select_from_window_features(features: Sequence[WindowFeature]) -> tuple[SelectedWindow, ...]:
    """Select the four frozen Representative Window V1 classes."""
    records = sorted(features, key=lambda item: item.start_offset_s)
    if not records:
        raise RepresentativeWindowError("representative-window feature set is empty")
    for record in records:
        _validate_feature(record)

    initial = [record for record in records if abs(record.start_offset_s) <= 1e-9 and record.valid]
    if len(initial) != 1:
        raise RepresentativeWindowError(
            "Representative Window V1 requires one valid initialization window at 0.0 s"
        )
    initialization = SelectedWindow(
        label="initialization",
        start_offset_s=0.0,
        duration_s=WINDOW_DURATION_S,
        score=None,
        feature=initial[0],
    )
    selected: list[SelectedWindow] = [initialization]

    post_start = WINDOW_DURATION_S + POST_INITIALIZATION_GUARD_S
    post_candidates = [
        record
        for record in records
        if record.start_offset_s + 1e-9 >= post_start and record.valid
    ]

    try:
        high = _choose_high_angular(_available(post_candidates, selected))
        selected.append(high)
        geometric = _choose_geometric(_available(post_candidates, selected))
        selected.append(geometric)
        steady = _choose_steady(_available(post_candidates, selected))
        selected.append(steady)
    except RepresentativeWindowError as exc:
        raise RepresentativeWindowError(
            "Representative Window V1 requires four pairwise non-overlapping windows"
        ) from exc

    if len(selected) != 4 or any(
        _overlap(left, right)
        for index, left in enumerate(selected)
        for right in selected[index + 1 :]
    ):
        raise RepresentativeWindowError(
            "Representative Window V1 requires four pairwise non-overlapping windows"
        )
    return tuple(selected)
