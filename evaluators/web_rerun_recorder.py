#!/usr/bin/env python3
"""Low-memory Rerun recorder used by the browser WebViewer.

The native viewer keeps its existing row-oriented implementation. The web path
uses Rerun's columnar API for dense 10 Hz pose/metric/resource series so the
browser does not receive tens of thousands of tiny chunks.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from plot_comparison_dashboard import LABELS
from rerun_diagnostic_viewer import (
    COLOR_RGB,
    _load_frame_index,
    _projection_context,
    _read_indexed_lidar_scans,
    _series_value,
    _timeline_positions,
    algorithm_entity_paths,
    apply_alignment,
    load_binary_little_endian_ply,
    load_csv,
    load_json,
    point_lod_clouds,
    select_pointcloud_frames,
    world_entity_paths,
)
from viewer_i18n import tr, translate_anomaly_types
from viewer_projection import project_points_to_display_world


_WEB_PROFILE_LAYERS = {
    "empty": frozenset(),
    "trajectory": frozenset({"trajectory"}),
    "scalar": frozenset({"trajectory", "scalar"}),
    "pose": frozenset({"trajectory", "scalar", "pose"}),
    "full": frozenset({"trajectory", "scalar", "pose", "anomaly", "heavy"}),
}


def web_profile_layers(profile: str) -> frozenset[str]:
    """Return the cumulative data layers enabled by one Web diagnostic profile."""
    try:
        return _WEB_PROFILE_LAYERS[str(profile)]
    except KeyError as exc:
        raise ValueError(f"unknown web recording profile: {profile}") from exc


def _finite_scalar_rows(
    times: np.ndarray,
    values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    time_values = np.asarray(times, dtype=np.float64).reshape(-1)
    scalar_values = np.asarray(values, dtype=np.float64).reshape(-1)
    if len(time_values) != len(scalar_values):
        raise ValueError("time/scalar column lengths differ")
    valid = np.isfinite(time_values) & np.isfinite(scalar_values)
    return time_values[valid], scalar_values[valid]


def send_scalar_series_columns(
    rr: Any,
    entity_path: str,
    times: np.ndarray,
    values: np.ndarray,
) -> int:
    """Send one scalar time-series as one columnar Rerun operation."""
    time_values, scalar_values = _finite_scalar_rows(times, values)
    if len(time_values) == 0:
        return 0
    rr.send_columns(
        entity_path,
        indexes=[rr.TimeColumn("bag_time", duration=time_values)],
        columns=rr.Scalars.columns(scalars=scalar_values),
    )
    return int(len(time_values))


def send_point_series_columns(
    rr: Any,
    entity_path: str,
    times: np.ndarray,
    positions: np.ndarray,
    *,
    color_rgb: list[int],
    radius: float,
    label: str,
) -> int:
    """Send one single-point-per-timestamp series in a single columnar operation."""
    time_values = np.asarray(times, dtype=np.float64).reshape(-1)
    position_values = np.asarray(positions, dtype=np.float64)
    if position_values.ndim != 2 or position_values.shape[1] != 3:
        raise ValueError("positions must have shape (N, 3)")
    if len(time_values) != len(position_values):
        raise ValueError("time/position column lengths differ")
    valid = np.isfinite(time_values) & np.isfinite(position_values).all(axis=1)
    time_values = time_values[valid]
    position_values = position_values[valid]
    if len(time_values) == 0:
        return 0
    count = int(len(time_values))
    rr.send_columns(
        entity_path,
        indexes=[rr.TimeColumn("bag_time", duration=time_values)],
        columns=rr.Points3D.columns(
            positions=position_values,
            colors=[list(color_rgb)] * count,
            radii=[float(radius)] * count,
            labels=[str(label)] * count,
        ),
    )
    return count


def _timeline_series(rows: list[dict[str, str]], key: str) -> tuple[np.ndarray, np.ndarray]:
    times: list[float] = []
    values: list[float] = []
    for row in rows:
        bag_time = _series_value(row, "bag_time_s")
        value = _series_value(row, key)
        if bag_time is None or value is None:
            continue
        times.append(bag_time)
        values.append(value)
    return np.asarray(times, dtype=np.float64), np.asarray(values, dtype=np.float64)


def log_recording_web_safe(
    rr: Any,
    run: Path,
    algorithms: list[str],
    *,
    baseline: str,
    with_maps: bool,
    map_point_step: int,
    pointcloud_mode: str,
    pointcloud_period_s: float,
    point_lods: dict[str, int],
    world_pointcloud_mode: str,
    world_algorithm: str | None,
    language: str,
) -> dict[str, Any]:
    """Populate the WebViewer recording with columnar high-rate series.

    Static trajectories/maps and the bounded anomaly-near LiDAR frames remain
    row-oriented because they are only a handful of chunks. Dense 10 Hz series
    use ``send_columns`` exclusively.
    """
    run = Path(run).resolve()
    world_algorithm = world_algorithm or baseline
    if world_algorithm not in algorithms:
        raise ValueError(f"world algorithm must be selected for the viewer: {world_algorithm}")

    timeline = load_json(run / "metrics" / "diagnostic_timeline.json", {}) or {}
    windows = list(timeline.get("anomaly_windows") or [])
    selected_windows = [item for item in windows if item.get("algorithm") in algorithms]
    trajectories, alignments, origin = _projection_context(run, algorithms, baseline)

    columnar_rows = 0
    columnar_chunks = 0

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
        sent = send_point_series_columns(
            rr,
            paths["current"],
            times,
            aligned_positions,
            color_rgb=COLOR_RGB.get(algorithm, [180, 180, 180]),
            radius=0.18,
            label=LABELS.get(algorithm, algorithm),
        )
        if sent:
            columnar_rows += sent
            columnar_chunks += 1

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
        for key, suffix in (
            ("delta_position_m", "delta_position_m"),
            ("delta_yaw_deg", "delta_yaw_deg"),
            ("speed_mps", "speed_mps"),
        ):
            times, values = _timeline_series(timeline_rows, key)
            sent = send_scalar_series_columns(
                rr,
                f"metrics/motion/{algorithm}/{suffix}",
                times,
                values,
            )
            if sent:
                columnar_rows += sent
                columnar_chunks += 1

        resource_path = run / "metrics" / "diagnostic_timeline" / "resources" / f"{algorithm}.csv"
        if resource_path.is_file():
            resource_rows = load_csv(resource_path)
            for key, root in (
                ("cpu_percent", "cpu"),
                ("rss_mib", "rss"),
                ("threads", "threads"),
            ):
                times, values = _timeline_series(resource_rows, key)
                sent = send_scalar_series_columns(
                    rr,
                    f"metrics/{root}/{algorithm}",
                    times,
                    values,
                )
                if sent:
                    columnar_rows += sent
                    columnar_chunks += 1

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
                                f"{LABELS.get(algorithm, algorithm)} | "
                                f"{tr(language, 'status.pose_unavailable')}"
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
        "columnar_rows": columnar_rows,
        "columnar_chunks": columnar_chunks,
        "recording_profile": "web-safe-columnar",
    }
