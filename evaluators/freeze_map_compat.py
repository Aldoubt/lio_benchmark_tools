from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from viewer_projection import (
    initial_yaw_translation_alignment,
    load_standardized_trajectory,
    pose_at,
)
from visualize_baseline_maps import read_scans, reconstruct_map, write_ply


DEFAULT_SCAN_STEP = 5
DEFAULT_POINT_STEP = 20
DEFAULT_VOXEL_M = 0.12


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _resolve_bag(source: Path, declared: str) -> Path:
    candidate = Path(str(declared)).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    # Frozen compatibility sources retain the historical manifest verbatim.
    # Relative dataset paths therefore remain relative to the original run,
    # not to <frozen>/source. Resolve that provenance path without mutating it.
    freeze_manifest = source.parent / "freeze_manifest.json"
    if source.name == "source" and freeze_manifest.is_file():
        payload = _load_json(freeze_manifest)
        source_run = payload.get("source_run") or {}
        original = source_run.get("path") if isinstance(source_run, dict) else None
        if original:
            return (Path(str(original)).expanduser().resolve() / candidate).resolve()
    return (source / candidate).resolve()


def build_compat_maps(
    source: Path,
    *,
    algorithms: list[str],
    baseline: str,
    scan_step: int = DEFAULT_SCAN_STEP,
    point_step: int = DEFAULT_POINT_STEP,
    voxel_m: float = DEFAULT_VOXEL_M,
) -> dict[str, Any]:
    """Derive baseline-aligned PLY maps below ``<frozen>/source``.

    The source rosbag2 database is opened read-only by ``read_scans``. Only
    compact reconstructed PLYs are written to the frozen compatibility copy.
    """
    source = Path(source).resolve()
    if baseline not in algorithms:
        raise ValueError(f"baseline is not selected for map compatibility: {baseline}")
    if scan_step < 1 or point_step < 1 or voxel_m <= 0:
        raise ValueError("invalid frozen map reconstruction sampling parameters")

    manifest = _load_json(source / "manifest.json")
    dataset = manifest.get("dataset") or {}
    if not isinstance(dataset, dict):
        raise ValueError("manifest dataset must be an object")
    bag_dir = dataset.get("bag_dir")
    lidar_topic = str(dataset.get("lidar_topic") or "")
    if not bag_dir or not lidar_topic:
        raise ValueError("manifest dataset.bag_dir/lidar_topic are required for map reconstruction")
    bag = _resolve_bag(source, str(bag_dir))
    if not bag.is_dir():
        raise FileNotFoundError(f"dataset bag directory is unavailable: {bag}")

    trajectories = {
        algorithm: load_standardized_trajectory(
            source / "standardized" / "trajectories" / f"{algorithm}.csv"
        )
        for algorithm in algorithms
    }
    baseline_trajectory = trajectories[baseline]
    alignments: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for algorithm, trajectory in trajectories.items():
        if algorithm == baseline:
            alignments[algorithm] = (np.eye(3), np.zeros(3))
        else:
            rotation, translation, _ = initial_yaw_translation_alignment(
                baseline_trajectory, trajectory
            )
            alignments[algorithm] = (rotation, translation)

    input_stop_time = max(
        float(trajectory.timestamp_s[-1]) for trajectory in trajectories.values()
    ) + 0.2
    evaluation = manifest.get("evaluation") or {}
    if not isinstance(evaluation, dict):
        evaluation = {}
    points, times, intensities = read_scans(
        bag,
        lidar_topic,
        scan_step,
        point_step,
        input_stop_time,
        float(evaluation.get("minimum_range_m", 0.5)),
        float(evaluation.get("maximum_range_m", 100.0)),
    )

    calibration = (manifest.get("calibration") or {}).get("lidar_to_imu") or {}
    extrinsic_rotation = np.asarray(
        calibration.get("rotation", np.eye(3)), dtype=np.float64
    ).reshape(3, 3)
    extrinsic_translation = np.asarray(
        calibration.get("translation", np.zeros(3)), dtype=np.float64
    ).reshape(3)

    common_start = max(
        float(trajectory.timestamp_s[0]) for trajectory in trajectories.values()
    )
    origin_positions, _, origin_valid = pose_at(
        baseline_trajectory, np.asarray([common_start])
    )
    if not origin_valid[0]:
        raise ValueError("baseline does not cover common frozen map display origin")
    origin = origin_positions[0]

    output = source / "figures" / "fast_livo2_baseline_maps"
    output.mkdir(parents=True, exist_ok=True)
    artifacts: list[str] = []
    metadata: dict[str, Any] = {}
    for algorithm in algorithms:
        path = output / f"{algorithm}_map.ply"
        if path.is_file():
            metadata[algorithm] = {
                "derived": False,
                "path": path.relative_to(source).as_posix(),
            }
            continue
        cloud = reconstruct_map(
            points,
            times,
            intensities,
            trajectories[algorithm],
            alignments[algorithm],
            extrinsic_rotation,
            extrinsic_translation,
            origin,
            voxel_m,
        )
        if len(cloud) == 0:
            metadata[algorithm] = {"derived": False, "reason": "empty_reconstructed_map"}
            continue
        write_ply(path, cloud)
        relative = path.relative_to(source).as_posix()
        artifacts.append(relative)
        metadata[algorithm] = {
            "derived": True,
            "path": relative,
            "map_points": int(len(cloud)),
            "extent_xyz_m": np.ptp(cloud[:, :3], axis=0).tolist(),
        }

    return {
        "derived": bool(artifacts),
        "method": "baseline-aligned-read-only-bag-map-v1",
        "scan_step": int(scan_step),
        "point_step": int(point_step),
        "voxel_m": float(voxel_m),
        "bag": str(bag),
        "derived_algorithms": [
            algorithm for algorithm, item in metadata.items() if item.get("derived")
        ],
        "artifacts": artifacts,
        "maps": metadata,
    }
