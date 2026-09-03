#!/usr/bin/env python3
"""Rerun-based offline viewer for one LIO benchmark run.

The viewer consumes frozen post-process artifacts. It does not recompute benchmark
metrics. All trajectory/map comparisons remain baseline-relative diagnostics when
independent ground truth is unavailable.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from plot_comparison_dashboard import LABELS
from viewer_i18n import SUPPORTED_LANGUAGES, tr, translate_anomaly_types
from viewer_projection import (
    IndexedLidarScan,
    TrajectoryModel,
    initial_yaw_translation_alignment,
    load_standardized_trajectory,
    pose_at,
    project_points_to_display_world,
)


COLOR_RGB = {
    "kiss_icp": [127, 140, 141],
    "mola_lo": [155, 89, 182],
    "mola_lio": [142, 68, 173],
    "fast_livo2": [230, 126, 34],
    "point_lio": [41, 128, 185],
    "dlio": [192, 57, 43],
    "glim_odometry": [39, 174, 96],
    "glim_full_slam": [22, 160, 133],
    "lio_sam_no_loop": [52, 73, 94],
    "lio_sam_loop": [44, 62, 80],
}
POINT_LOD_NAMES = ("dense", "medium", "sparse")
DEFAULT_POINT_LODS = "10,20,80"


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def load_binary_little_endian_ply(path: Path) -> np.ndarray:
    """Read the exact x/y/z/intensity binary PLY emitted by this benchmark."""
    path = Path(path)
    with path.open("rb") as stream:
        header_lines: list[str] = []
        while True:
            raw = stream.readline()
            if not raw:
                raise ValueError(f"PLY header is incomplete: {path}")
            line = raw.decode("ascii").strip()
            header_lines.append(line)
            if line == "end_header":
                break
        if "format binary_little_endian 1.0" not in header_lines:
            raise ValueError(f"unsupported PLY format: {path}")
        vertex_line = next((line for line in header_lines if line.startswith("element vertex ")), None)
        if vertex_line is None:
            raise ValueError(f"PLY has no vertex count: {path}")
        count = int(vertex_line.split()[-1])
        properties = [line for line in header_lines if line.startswith("property ")]
        expected = [
            "property float x",
            "property float y",
            "property float z",
            "property float intensity",
        ]
        if properties != expected:
            raise ValueError(f"unsupported PLY vertex schema in {path}: {properties}")
        records = np.fromfile(
            stream,
            dtype=np.dtype(
                [("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4")]
            ),
            count=count,
        )
    if len(records) != count:
        raise ValueError(f"PLY payload is truncated: expected {count}, got {len(records)}")
    return np.column_stack(
        [records[name].astype(np.float64) for name in ("x", "y", "z", "intensity")]
    )


def nearest_frame(frames: list[dict[str, Any]], bag_time_s: float) -> dict[str, Any]:
    if not frames:
        raise ValueError("pointcloud frame index is empty")
    times = [float(item["bag_time_s"]) for item in frames]
    index = bisect.bisect_left(times, float(bag_time_s))
    if index <= 0:
        return frames[0]
    if index >= len(frames):
        return frames[-1]
    before, after = frames[index - 1], frames[index]
    return (
        before
        if abs(float(before["bag_time_s"]) - bag_time_s)
        <= abs(float(after["bag_time_s"]) - bag_time_s)
        else after
    )


def select_pointcloud_frames(
    frames: list[dict[str, Any]],
    anomaly_windows: list[dict[str, Any]],
    *,
    period_s: float,
    include_anomalies: bool,
) -> list[dict[str, Any]]:
    """Choose a bounded set of indexed frames for the offline recording."""
    if not frames:
        return []
    selected: dict[int, dict[str, Any]] = {}
    if period_s > 0:
        start = float(frames[0]["bag_time_s"])
        end = float(frames[-1]["bag_time_s"])
        target = start
        while target <= end + 1e-9:
            item = nearest_frame(frames, target)
            selected[int(item["message_id"])] = item
            target += period_s
        item = nearest_frame(frames, end)
        selected[int(item["message_id"])] = item
    if include_anomalies:
        for window in anomaly_windows:
            start = float(window["start_bag_time_s"])
            end = float(window["end_bag_time_s"])
            for target in {start, 0.5 * (start + end), end}:
                item = nearest_frame(frames, target)
                selected[int(item["message_id"])] = item
    return sorted(selected.values(), key=lambda item: float(item["bag_time_s"]))


def parse_point_lods(value: str) -> dict[str, int]:
    """Parse dense,medium,sparse point strides from a compact CLI value."""
    try:
        steps = [int(item.strip()) for item in str(value).split(",")]
    except ValueError as exc:
        raise ValueError("--point-lods must contain three integer strides") from exc
    if len(steps) != 3 or any(step < 1 for step in steps):
        raise ValueError("--point-lods must contain three positive strides")
    if not (steps[0] < steps[1] < steps[2]):
        raise ValueError("--point-lods must be strictly increasing: dense,medium,sparse")
    if any(step % steps[0] != 0 for step in steps[1:]):
        raise ValueError("medium/sparse point LOD strides must be multiples of dense stride")
    return dict(zip(POINT_LOD_NAMES, steps))


def point_lod_clouds(
    dense_points: np.ndarray,
    lod_steps: dict[str, int],
) -> dict[str, np.ndarray]:
    """Derive coarser LODs from one already-deserialized dense cloud."""
    points = np.asarray(dense_points, dtype=np.float64)
    dense_step = int(lod_steps["dense"])
    output: dict[str, np.ndarray] = {}
    for name in POINT_LOD_NAMES:
        step = int(lod_steps[name])
        if step < dense_step or step % dense_step != 0:
            raise ValueError("point LOD strides must be increasing multiples of dense stride")
        output[name] = points[:: max(1, step // dense_step)]
    return output


def algorithm_entity_paths(algorithm: str) -> dict[str, str]:
    root = f"world/algorithms/{algorithm}"
    return {
        "root": root,
        "trajectory": f"{root}/trajectory",
        "current": f"{root}/current",
        "map": f"{root}/map",
    }


def world_entity_paths(algorithm: str) -> dict[str, str]:
    root = f"world_lidar/{algorithm}"
    return {name: f"{root}/{name}" for name in POINT_LOD_NAMES}


def initial_yaw_translation_transform(
    baseline_start: np.ndarray,
    baseline_yaw_rad: float,
    candidate_start: np.ndarray,
    candidate_yaw_rad: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Legacy pure helper retained for focused viewer tests/API compatibility."""
    yaw_delta = float(baseline_yaw_rad) - float(candidate_yaw_rad)
    c, s = math.cos(yaw_delta), math.sin(yaw_delta)
    rotation = np.asarray(
        [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    translation = np.asarray(baseline_start, dtype=np.float64) - rotation @ np.asarray(
        candidate_start, dtype=np.float64
    )
    return rotation, translation


def apply_alignment(
    points: np.ndarray,
    rotation: np.ndarray,
    translation: np.ndarray,
) -> np.ndarray:
    values = np.asarray(points, dtype=np.float64)
    return (rotation @ values.T).T + np.asarray(translation, dtype=np.float64)


def resolve_algorithms(run: Path, requested: str | None) -> list[str]:
    payload = load_json(Path(run) / "metrics" / "diagnostic_timeline.json", {}) or {}
    available = [str(item) for item in payload.get("algorithm_order") or []]
    if not available:
        raise FileNotFoundError(
            "metrics/diagnostic_timeline.json is missing algorithm_order; run lio-benchmark diagnostics first"
        )
    if requested is None:
        return available
    selected = [item.strip() for item in requested.split(",") if item.strip()]
    unknown = sorted(set(selected) - set(available))
    if unknown:
        raise ValueError(f"unknown algorithms: {unknown}")
    return selected


def _projection_context(
    run: Path,
    algorithms: list[str],
    baseline: str,
) -> tuple[
    dict[str, TrajectoryModel],
    dict[str, tuple[np.ndarray, np.ndarray]],
    np.ndarray,
]:
    trajectories = {
        algorithm: load_standardized_trajectory(
            Path(run) / "standardized" / "trajectories" / f"{algorithm}.csv"
        )
        for algorithm in algorithms
    }
    if baseline not in trajectories:
        trajectories[baseline] = load_standardized_trajectory(
            Path(run) / "standardized" / "trajectories" / f"{baseline}.csv"
        )
    base = trajectories[baseline]
    alignments: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for algorithm, trajectory in trajectories.items():
        if algorithm == baseline:
            alignments[algorithm] = (np.eye(3), np.zeros(3))
        else:
            rotation, translation, _ = initial_yaw_translation_alignment(base, trajectory)
            alignments[algorithm] = (rotation, translation)
    common_start = max(float(trajectory.timestamp_s[0]) for trajectory in trajectories.values())
    origin_positions, _, valid = pose_at(base, np.asarray([common_start]))
    if not valid[0]:
        raise ValueError("baseline does not cover common viewer display origin")
    return trajectories, alignments, origin_positions[0]


def _timeline_positions(run: Path, algorithm: str) -> tuple[np.ndarray, np.ndarray]:
    rows = load_csv(
        Path(run) / "metrics" / "diagnostic_timeline" / f"{algorithm}.csv"
    )
    times = np.asarray([float(row["bag_time_s"]) for row in rows], dtype=np.float64)
    positions = np.asarray(
        [[float(row["x_m"]), float(row["y_m"]), float(row["z_m"])] for row in rows],
        dtype=np.float64,
    )
    return times, positions


def _load_frame_index(run: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = load_json(Path(run) / "metrics" / "pointcloud_frame_index.json", {}) or {}
    frames = list(payload.get("frames") or [])
    return payload, frames


def scan_from_livox_message(
    message: object,
    frame: dict[str, object],
    *,
    dense_step: int,
    minimum_range_m: float = 0.0,
    maximum_range_m: float = float("inf"),
) -> IndexedLidarScan:
    if dense_step < 1:
        raise ValueError("dense_step must be >= 1")
    if minimum_range_m < 0 or maximum_range_m <= minimum_range_m:
        raise ValueError("invalid LiDAR range limits")
    stamp = getattr(getattr(message, "header"), "stamp")
    header_time = float(stamp.sec) + float(stamp.nanosec) * 1e-9
    selected = getattr(message, "points")[::dense_step]
    xyz = np.asarray([[p.x, p.y, p.z] for p in selected], dtype=np.float64)
    point_times = header_time + np.asarray(
        [p.offset_time for p in selected], dtype=np.float64
    ) * 1e-9
    intensity = np.asarray(
        [getattr(p, "reflectivity", 0.0) for p in selected], dtype=np.float64
    )
    ranges = np.linalg.norm(xyz, axis=1)
    valid = (
        np.isfinite(xyz).all(axis=1)
        & np.isfinite(point_times)
        & np.isfinite(intensity)
        & (ranges >= float(minimum_range_m))
        & (ranges <= float(maximum_range_m))
    )
    return IndexedLidarScan(
        bag_time_s=float(frame["bag_time_s"]),
        header_timestamp_s=header_time,
        points_xyz=xyz[valid],
        point_times_s=point_times[valid],
        intensity=intensity[valid],
    )


def _read_indexed_lidar_scans(
    sqlite_db: Path,
    topic: str,
    topic_type: str,
    frames: Iterable[dict[str, Any]],
    *,
    dense_step: int,
    minimum_range_m: float,
    maximum_range_m: float,
) -> list[IndexedLidarScan]:
    """Deserialize every selected source message once; never replay the bag."""
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    message_class = get_message(topic_type)
    connection = sqlite3.connect(f"file:{Path(sqlite_db)}?mode=ro", uri=True)
    try:
        topic_row = connection.execute(
            "SELECT id FROM topics WHERE name = ?", (topic,)
        ).fetchone()
        if topic_row is None:
            raise ValueError(f"bag missing LiDAR topic {topic}")
        result: list[IndexedLidarScan] = []
        for frame in frames:
            row = connection.execute(
                "SELECT data FROM messages WHERE id = ? AND topic_id = ?",
                (int(frame["message_id"]), int(topic_row[0])),
            ).fetchone()
            if row is None:
                continue
            message = deserialize_message(row[0], message_class)
            if hasattr(message, "points"):
                result.append(
                    scan_from_livox_message(
                        message,
                        frame,
                        dense_step=dense_step,
                        minimum_range_m=minimum_range_m,
                        maximum_range_m=maximum_range_m,
                    )
                )
            elif hasattr(message, "fields"):
                raise ValueError(
                    "PointCloud2 on-demand rendering is not implemented in the Rerun MVP yet"
                )
            else:
                raise ValueError(f"unsupported LiDAR message type: {type(message)!r}")
        return result
    finally:
        connection.close()


def _series_value(row: dict[str, str], key: str) -> float | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def send_blueprint(
    rr: Any,
    rrb: Any,
    *,
    algorithms: list[str],
    visible_algorithms: set[str] | None,
    world_algorithm: str,
    point_lod: str,
    language: str,
) -> None:
    visible = set(algorithms if visible_algorithms is None else visible_algorithms)
    sensor_overrides = {
        f"/sensor/raw_lidar/{lod}": rrb.EntityBehavior(visible=lod == point_lod)
        for lod in POINT_LOD_NAMES
    }
    world_overrides: dict[str, Any] = {}
    map_overrides: dict[str, Any] = {}
    for algorithm in algorithms:
        map_overrides[f"/world/algorithms/{algorithm}"] = rrb.EntityBehavior(
            visible=algorithm in visible
        )
        for lod, path in world_entity_paths(algorithm).items():
            world_overrides[f"/{path}"] = rrb.EntityBehavior(
                visible=algorithm == world_algorithm and lod == point_lod
            )

    sensor_view = rrb.Spatial3DView(
        name=tr(language, "view.raw_lidar"),
        origin="/sensor",
        overrides=sensor_overrides,
    )
    world_view = rrb.Spatial3DView(
        name=tr(language, "view.world_lidar"),
        origin="/world_lidar",
        overrides=world_overrides,
    )
    blueprint = rrb.Blueprint(
        rrb.Vertical(
            rrb.Horizontal(
                rrb.Spatial3DView(
                    name=tr(language, "view.map_trajectories"),
                    origin="/world",
                    overrides=map_overrides,
                ),
                rrb.Vertical(
                    rrb.TimeSeriesView(name=tr(language, "view.cpu"), origin="/metrics/cpu"),
                    rrb.TimeSeriesView(name=tr(language, "view.rss"), origin="/metrics/rss"),
                    rrb.TimeSeriesView(name=tr(language, "view.motion"), origin="/metrics/motion"),
                    row_shares=[1, 1, 1],
                ),
                column_shares=[2, 1],
            ),
            rrb.Horizontal(
                sensor_view,
                world_view,
                rrb.TextLogView(name=tr(language, "view.anomaly_windows"), origin="/events"),
                column_shares=[1, 1, 1],
            ),
            row_shares=[3, 2],
        ),
        collapse_panels=False,
    )
    rr.send_blueprint(blueprint)


def log_recording(
    run: Path,
    algorithms: list[str],
    *,
    baseline: str,
    with_maps: bool,
    map_point_step: int,
    pointcloud_mode: str,
    pointcloud_period_s: float,
    point_step: int,
    point_lods: dict[str, int],
    world_pointcloud_mode: str,
    world_algorithm: str | None,
    language: str,
    save: Path | None,
    spawn: bool,
    initialize: bool = True,
    send_blueprint_layout: bool = True,
) -> dict[str, Any]:
    try:
        import rerun as rr
        import rerun.blueprint as rrb
    except ImportError as exc:
        raise RuntimeError(
            "Rerun SDK is not installed. Install the tested viewer dependency with: "
            "python3 -m pip install 'rerun-sdk==0.36.3'"
        ) from exc

    run = Path(run).resolve()
    world_algorithm = world_algorithm or baseline
    if world_algorithm not in algorithms:
        raise ValueError(f"world algorithm must be selected for the viewer: {world_algorithm}")
    timeline = load_json(run / "metrics" / "diagnostic_timeline.json", {}) or {}
    windows = list(timeline.get("anomaly_windows") or [])
    selected_windows = [item for item in windows if item.get("algorithm") in algorithms]
    trajectories, alignments, origin = _projection_context(run, algorithms, baseline)

    if initialize:
        rr.init("lio_benchmark_offline_diagnostic_viewer", spawn=spawn and save is None)
    if save is not None:
        save = Path(save).expanduser().resolve()
        save.parent.mkdir(parents=True, exist_ok=True)
        rr.save(str(save))
    if send_blueprint_layout:
        send_blueprint(
            rr,
            rrb,
            algorithms=algorithms,
            visible_algorithms=set(algorithms),
            world_algorithm=world_algorithm,
            point_lod="medium",
            language=language,
        )

    for algorithm in algorithms:
        paths = algorithm_entity_paths(algorithm)
        trajectory = trajectories[algorithm]
        rotation, translation = alignments[algorithm]
        aligned = apply_alignment(trajectory.positions, rotation, translation) - origin
        rr.log(
            paths["trajectory"],
            rr.LineStrips3D(
                [aligned],
                colors=COLOR_RGB.get(algorithm, [180, 180, 180]),
                radii=0.025,
            ),
            static=True,
        )
        times, positions = _timeline_positions(run, algorithm)
        aligned_positions = apply_alignment(positions, rotation, translation) - origin
        for bag_time, position in zip(times, aligned_positions):
            rr.set_time("bag_time", duration=float(bag_time))
            rr.log(
                paths["current"],
                rr.Points3D(
                    [position],
                    colors=COLOR_RGB.get(algorithm, [180, 180, 180]),
                    radii=0.18,
                    labels=[LABELS.get(algorithm, algorithm)],
                ),
            )

    if with_maps:
        map_dir = run / "figures" / "fast_livo2_baseline_maps"
        for algorithm in algorithms:
            path = map_dir / f"{algorithm}_map.ply"
            if not path.is_file():
                continue
            cloud = load_binary_little_endian_ply(path)
            shown = cloud[:: max(1, int(map_point_step)), :3]
            rr.log(
                algorithm_entity_paths(algorithm)["map"],
                rr.Points3D(
                    shown,
                    colors=COLOR_RGB.get(algorithm, [160, 160, 160]),
                    radii=0.015,
                ),
                static=True,
            )

    for algorithm in algorithms:
        timeline_rows = load_csv(
            run / "metrics" / "diagnostic_timeline" / f"{algorithm}.csv"
        )
        for row in timeline_rows:
            bag_time = _series_value(row, "bag_time_s")
            if bag_time is None:
                continue
            rr.set_time("bag_time", duration=bag_time)
            delta_position = _series_value(row, "delta_position_m")
            delta_yaw = _series_value(row, "delta_yaw_deg")
            speed = _series_value(row, "speed_mps")
            if delta_position is not None:
                rr.log(f"metrics/motion/{algorithm}/delta_position_m", rr.Scalars(delta_position))
            if delta_yaw is not None:
                rr.log(f"metrics/motion/{algorithm}/delta_yaw_deg", rr.Scalars(delta_yaw))
            if speed is not None:
                rr.log(f"metrics/motion/{algorithm}/speed_mps", rr.Scalars(speed))

        resource_path = run / "metrics" / "diagnostic_timeline" / "resources" / f"{algorithm}.csv"
        if resource_path.is_file():
            for row in load_csv(resource_path):
                bag_time = _series_value(row, "bag_time_s")
                if bag_time is None:
                    continue
                rr.set_time("bag_time", duration=bag_time)
                for key, root in (
                    ("cpu_percent", "cpu"),
                    ("rss_mib", "rss"),
                    ("threads", "threads"),
                ):
                    value = _series_value(row, key)
                    if value is not None:
                        rr.log(f"metrics/{root}/{algorithm}", rr.Scalars(value))

    for window in selected_windows:
        start = float(window["start_bag_time_s"])
        rr.set_time("bag_time", duration=start)
        types_display = ",".join(translate_anomaly_types(language, list(window["types"])))
        rr.log(
            "events/anomaly_windows",
            rr.TextLog(
                f"{window['window_id']} | {LABELS.get(window['algorithm'], window['algorithm'])} | "
                f"{window['start_bag_time_s']:.2f}-{window['end_bag_time_s']:.2f}s | "
                f"types={types_display} | severity={window['severity']:.2f}"
            ),
        )
        rr.log(
            f"metrics/motion/anomaly_severity/{window['algorithm']}",
            rr.Scalars(float(window["severity"])),
        )

    pointcloud_frames_logged = 0
    world_pointcloud_frames_logged = 0
    if pointcloud_mode != "none" or world_pointcloud_mode != "none":
        index_payload, frames = _load_frame_index(run)
        if not frames:
            raise FileNotFoundError(
                "pointcloud_frame_index.json is unavailable; run diagnostics --with-pointcloud-index first"
            )
        raw_frames = (
            select_pointcloud_frames(
                frames,
                selected_windows,
                period_s=pointcloud_period_s if pointcloud_mode == "sampled" else 0.0,
                include_anomalies=True,
            )
            if pointcloud_mode != "none"
            else []
        )
        world_frames = (
            select_pointcloud_frames(
                frames,
                selected_windows,
                period_s=pointcloud_period_s if world_pointcloud_mode == "sampled" else 0.0,
                include_anomalies=True,
            )
            if world_pointcloud_mode != "none"
            else []
        )
        union = {
            int(frame["message_id"]): frame for frame in [*raw_frames, *world_frames]
        }
        union_frames = sorted(union.values(), key=lambda item: float(item["bag_time_s"]))
        dense_step = int(point_lods["dense"])
        manifest = load_json(run / "manifest.json", {}) or {}
        evaluation = manifest.get("evaluation") or {}
        minimum_range_m = float(evaluation.get("minimum_range_m", 0.5))
        maximum_range_m = float(evaluation.get("maximum_range_m", 100.0))
        scans = _read_indexed_lidar_scans(
            Path(index_payload["sqlite_db"]),
            str(index_payload["lidar_topic"]),
            str(index_payload["lidar_type"]),
            union_frames,
            dense_step=dense_step,
            minimum_range_m=minimum_range_m,
            maximum_range_m=maximum_range_m,
        )
        raw_times = {float(frame["bag_time_s"]) for frame in raw_frames}
        world_times = {float(frame["bag_time_s"]) for frame in world_frames}

        calibration = (manifest.get("calibration") or {}).get("lidar_to_imu") or {}
        extrinsic_rotation = np.asarray(
            calibration.get("rotation", np.eye(3)), dtype=np.float64
        ).reshape(3, 3)
        extrinsic_translation = np.asarray(
            calibration.get("translation", np.zeros(3)), dtype=np.float64
        ).reshape(3)
        max_gap_s = evaluation.get("max_pose_interpolation_gap_s")
        max_gap_s = float(max_gap_s) if max_gap_s is not None else None

        for scan in scans:
            rr.set_time("bag_time", duration=scan.bag_time_s)
            if scan.bag_time_s in raw_times:
                for lod_name, points in point_lod_clouds(scan.points_xyz, point_lods).items():
                    rr.log(f"sensor/raw_lidar/{lod_name}", rr.Points3D(points, radii=0.025))
                pointcloud_frames_logged += 1

            if scan.bag_time_s in world_times:
                for algorithm in algorithms:
                    alignment_rotation, alignment_translation = alignments[algorithm]
                    projected, valid = project_points_to_display_world(
                        scan.points_xyz,
                        scan.point_times_s,
                        trajectories[algorithm],
                        extrinsic_rotation,
                        extrinsic_translation,
                        alignment_rotation,
                        alignment_translation,
                        origin,
                        max_gap_s,
                    )
                    if not np.any(valid):
                        rr.log(
                            "events/viewer_status",
                            rr.TextLog(
                                f"{LABELS.get(algorithm, algorithm)} | {tr(language, 'status.pose_unavailable')}"
                            ),
                        )
                        continue
                    valid_points = projected[valid]
                    for lod_name, points in point_lod_clouds(valid_points, point_lods).items():
                        rr.log(
                            world_entity_paths(algorithm)[lod_name],
                            rr.Points3D(
                                points,
                                colors=COLOR_RGB.get(algorithm, [180, 180, 180]),
                                radii=0.025,
                            ),
                        )
                world_pointcloud_frames_logged += 1

    return {
        "run": str(run),
        "algorithms": algorithms,
        "baseline": baseline,
        "language": language,
        "anomaly_windows": len(selected_windows),
        "pointcloud_mode": pointcloud_mode,
        "pointcloud_frames_logged": pointcloud_frames_logged,
        "pointcloud_lods": point_lods,
        "world_pointcloud_mode": world_pointcloud_mode,
        "world_algorithm": world_algorithm,
        "world_pointcloud_frames_logged": world_pointcloud_frames_logged,
        "legacy_point_step": int(point_step),
        "saved_rrd": str(save) if save is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Open the offline LIO benchmark diagnostic viewer"
    )
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument(
        "--algorithms",
        help="comma-separated algorithm keys; default: all algorithms in diagnostic_timeline.json",
    )
    parser.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default="zh-CN")
    parser.add_argument("--no-maps", action="store_true", help="skip reconstructed PLY maps")
    parser.add_argument("--map-point-step", type=int, default=4, help="display every Nth PLY point")
    parser.add_argument("--pointcloud-mode", choices=("none", "anomaly", "sampled"), default="anomaly")
    parser.add_argument("--pointcloud-period", type=float, default=1.0, help="seconds between raw scans in sampled mode")
    parser.add_argument("--point-step", type=int, default=20, help="legacy single-density stride retained for CLI compatibility")
    parser.add_argument("--point-lods", default=DEFAULT_POINT_LODS, help="dense,medium,sparse raw LiDAR strides; default: 10,20,80")
    parser.add_argument("--world-pointcloud-mode", choices=("none", "anomaly", "sampled"), default="anomaly")
    parser.add_argument("--world-algorithm", help="world LiDAR algorithm visible by default; default: baseline")
    parser.add_argument("--save", type=Path, help="write an .rrd recording instead of spawning a viewer")
    parser.add_argument("--no-spawn", action="store_true", help="do not spawn the native viewer")
    args = parser.parse_args()
    if args.map_point_step < 1 or args.point_step < 1 or args.pointcloud_period <= 0:
        raise ValueError("map/point steps must be >=1 and pointcloud period must be >0")
    point_lods = parse_point_lods(args.point_lods)

    run = args.run.resolve()
    algorithms = resolve_algorithms(run, args.algorithms)
    if args.baseline not in algorithms:
        algorithms = [args.baseline, *algorithms]
    world_algorithm = args.world_algorithm or args.baseline
    if world_algorithm not in algorithms:
        raise ValueError(f"world algorithm must be in selected algorithms: {world_algorithm}")
    result = log_recording(
        run,
        algorithms,
        baseline=args.baseline,
        with_maps=not args.no_maps,
        map_point_step=args.map_point_step,
        pointcloud_mode=args.pointcloud_mode,
        pointcloud_period_s=args.pointcloud_period,
        point_step=args.point_step,
        point_lods=point_lods,
        world_pointcloud_mode=args.world_pointcloud_mode,
        world_algorithm=world_algorithm,
        language=args.lang,
        save=args.save,
        spawn=not args.no_spawn,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
