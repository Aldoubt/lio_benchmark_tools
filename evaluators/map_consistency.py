#!/usr/bin/env python3
"""Pure quantitative helpers for reconstructed-map consistency diagnostics.

All candidate maps are assumed to already be expressed in the selected
baseline frame. These metrics quantify consistency with that baseline; without
independent ground truth they are diagnostic and are not absolute map accuracy.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.spatial import cKDTree


ROBUST_LOW_PERCENTILE = 1.0
ROBUST_HIGH_PERCENTILE = 99.0
MAX_NN_POINTS = 50_000
MAP_Z_SPAN_RATIO_LIMIT = 2.0
MAP_VOXEL_IOU_MIN = 0.10
MAP_SYMMETRIC_NN_P95_MAX_M = 2.0


def _finite_xyz(cloud: np.ndarray) -> np.ndarray:
    values = np.asarray(cloud, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] < 3:
        raise ValueError("map cloud must have shape Nx3 or wider")
    xyz = values[:, :3]
    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    if not len(xyz):
        raise ValueError("map cloud contains no finite XYZ points")
    return xyz


def robust_extent_xyz(
    cloud: np.ndarray,
    low_percentile: float = ROBUST_LOW_PERCENTILE,
    high_percentile: float = ROBUST_HIGH_PERCENTILE,
) -> np.ndarray:
    """Return per-axis P(high)-P(low) extent, robust to isolated outliers."""
    if not 0.0 <= low_percentile < high_percentile <= 100.0:
        raise ValueError("percentiles must satisfy 0 <= low < high <= 100")
    xyz = _finite_xyz(cloud)
    low = np.percentile(xyz, low_percentile, axis=0)
    high = np.percentile(xyz, high_percentile, axis=0)
    return np.asarray(high - low, dtype=np.float64)


def _voxel_keys(cloud: np.ndarray, voxel_m: float) -> np.ndarray:
    if voxel_m <= 0:
        raise ValueError("voxel_m must be > 0")
    xyz = _finite_xyz(cloud)
    keys = np.floor(xyz / float(voxel_m)).astype(np.int64)
    return np.unique(keys, axis=0)


def _row_view(keys: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(keys)
    dtype = np.dtype((np.void, contiguous.dtype.itemsize * contiguous.shape[1]))
    return contiguous.view(dtype).reshape(-1)


def voxel_iou(reference: np.ndarray, candidate: np.ndarray, voxel_m: float) -> float:
    """Return occupancy IoU after quantizing both maps into the same voxel grid."""
    reference_keys = _voxel_keys(reference, voxel_m)
    candidate_keys = _voxel_keys(candidate, voxel_m)
    reference_rows = _row_view(reference_keys)
    candidate_rows = _row_view(candidate_keys)
    intersection = int(np.intersect1d(reference_rows, candidate_rows).size)
    union = int(len(reference_rows) + len(candidate_rows) - intersection)
    return float(intersection / union) if union else 1.0


def _deterministic_sample(xyz: np.ndarray, max_points: int) -> np.ndarray:
    if max_points < 1:
        raise ValueError("max_points must be >= 1")
    if len(xyz) <= max_points:
        return xyz
    indices = np.linspace(0, len(xyz) - 1, max_points, dtype=np.int64)
    return xyz[indices]


def symmetric_nn_metrics(
    reference: np.ndarray,
    candidate: np.ndarray,
    max_points: int = MAX_NN_POINTS,
) -> dict[str, Any]:
    """Return symmetric nearest-neighbour distances on bounded deterministic samples."""
    reference_xyz = _deterministic_sample(_finite_xyz(reference), max_points)
    candidate_xyz = _deterministic_sample(_finite_xyz(candidate), max_points)

    reference_tree = cKDTree(reference_xyz)
    candidate_tree = cKDTree(candidate_xyz)
    candidate_to_reference = reference_tree.query(candidate_xyz, k=1, workers=-1)[0]
    reference_to_candidate = candidate_tree.query(reference_xyz, k=1, workers=-1)[0]
    distances = np.concatenate((candidate_to_reference, reference_to_candidate))
    return {
        "mean_m": float(np.mean(distances)),
        "rmse_m": float(np.sqrt(np.mean(np.square(distances)))),
        "p95_m": float(np.percentile(distances, 95)),
        "max_m": float(np.max(distances)),
        "samples_reference": int(len(reference_xyz)),
        "samples_candidate": int(len(candidate_xyz)),
    }


def map_health_flags(
    candidate_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
) -> list[str]:
    """Apply conservative baseline-relative map-health diagnostics."""
    flags: list[str] = []
    candidate_extent = candidate_metrics.get("robust_extent_xyz_m") or []
    baseline_extent = baseline_metrics.get("robust_extent_xyz_m") or []
    if len(candidate_extent) >= 3 and len(baseline_extent) >= 3:
        baseline_z = float(baseline_extent[2])
        candidate_z = float(candidate_extent[2])
        if baseline_z > 1e-9 and candidate_z > MAP_Z_SPAN_RATIO_LIMIT * baseline_z:
            flags.append("excessive_robust_z_span")

    iou = candidate_metrics.get("baseline_voxel_iou")
    if iou is not None and float(iou) < MAP_VOXEL_IOU_MIN:
        flags.append("low_baseline_voxel_iou")

    nn_p95 = candidate_metrics.get("symmetric_nn_p95_m")
    if nn_p95 is not None and float(nn_p95) > MAP_SYMMETRIC_NN_P95_MAX_M:
        flags.append("high_symmetric_nn_p95")
    return flags
