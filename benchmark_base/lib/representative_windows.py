#!/usr/bin/env python3
"""Estimator-independent representative-window selection contracts.

This module is deliberately ROS-independent. Target-machine bag readers turn
raw LiDAR/IMU messages into :class:`WindowFeature` records; this module only
validates, ranks, and selects those records deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence

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
class WindowFeature:
    start_offset_s: float
    duration_s: float
    lidar_scan_count: int
    imu_sample_count: int
    gyro_rms_rad_s: float
    gyro_p95_rad_s: float
    accel_dynamic_rms_m_s2: float
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


def _validate_feature(value: WindowFeature) -> None:
    numeric = (
        value.start_offset_s,
        value.duration_s,
        value.gyro_rms_rad_s,
        value.gyro_p95_rad_s,
        value.accel_dynamic_rms_m_s2,
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
        [item.accel_dynamic_rms_m_s2 for item in candidates], high_is_good=False
    )
    scored = [
        (
            0.60 * scene + 0.30 * gyro + 0.10 * accel,
            feature,
        )
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
    """Select the four frozen Representative Window V1 classes.

    The input records are assumed to have been computed exclusively from raw
    LiDAR/IMU evidence. Selection order and non-overlap are fixed by the V1
    scientific contract.
    """
    records = sorted(features, key=lambda item: item.start_offset_s)
    if not records:
        raise RepresentativeWindowError("representative-window feature set is empty")
    for record in records:
        _validate_feature(record)

    initial = [
        record
        for record in records
        if abs(record.start_offset_s) <= 1e-9 and record.valid
    ]
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
