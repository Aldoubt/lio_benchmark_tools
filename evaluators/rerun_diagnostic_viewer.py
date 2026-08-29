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

from plot_comparison_dashboard import LABELS, load_trajectory


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
        records = np.fromfile(stream, dtype=np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4")]), count=count)
    if len(records) != count:
        raise ValueError(f"PLY payload is truncated: expected {count}, got {len(records)}")
    return np.column_stack([records[name].astype(np.float64) for name in ("x", "y", "z", "intensity")])


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
    return before if abs(float(before["bag_time_s"]) - bag_time_s) <= abs(float(after["bag_time_s"]) - bag_time_s) else after


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


def initial_yaw_translation_transform(
    baseline_start: np.ndarray,
    baseline_yaw_rad: float,
    candidate_start: np.ndarray,
    candidate_yaw_rad: float,
) -> tuple[np.ndarray, np.ndarray]:
    yaw_delta = float(baseline_yaw_rad) - float(candidate_yaw_rad)
    c, s = math.cos(yaw_delta), math.sin(yaw_delta)
    rotation = np.asarray([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    translation = np.asarray(baseline_start, dtype=np.float64) - rotation @ np.asarray(candidate_start, dtype=np.float64)
    return rotation, translation


def apply_alignment(points: np.ndarray, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    values = np.asarray(points, dtype=np.float64)
    return (rotation @ values.T).T + np.asarray(translation, dtype=np.float64)


def resolve_algorithms(run: Path, requested: str | None) -> list[str]:
    payload = load_json(Path(run) / "metrics" / "diagnostic_timeline.json", {}) or {}
    available = [str(item) for item in payload.get("algorithm_order") or []]
    if not available:
        raise FileNotFoundError("metrics/diagnostic_timeline.json is missing algorithm_order; run lio-benchmark diagnostics first")
    if requested is None:
        return available
    selected = [item.strip() for item in requested.split(",") if item.strip()]
    unknown = sorted(set(selected) - set(available))
    if unknown:
        raise ValueError(f"unknown algorithms: {unknown}")
    return selected


def _alignment_for_trajectories(run: Path, algorithms: list[str], baseline: str) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], np.ndarray]:
    trajectories = {
        algorithm: load_trajectory(Path(run) / "standardized" / "trajectories" / f"{algorithm}.csv")
        for algorithm in algorithms
    }
    if baseline not in trajectories:
        trajectories[baseline] = load_trajectory(Path(run) / "standardized" / "trajectories" / f"{baseline}.csv")
    base = trajectories[baseline]
    base_start = np.asarray(base["positions"][0], dtype=np.float64)
    base_yaw = float(base["yaw_rad"][0])
    transforms: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for algorithm, trajectory in trajectories.items():
        if algorithm == baseline:
            transforms[algorithm] = (np.eye(3), np.zeros(3))
        else:
            transforms[algorithm] = initial_yaw_translation_transform(
                base_start,
                base_yaw,
                np.asarray(trajectory["positions"][0], dtype=np.float64),
                float(trajectory["yaw_rad"][0]),
            )
    return transforms, base_start


def _timeline_positions(run: Path, algorithm: str) -> tuple[np.ndarray, np.ndarray]:
    rows = load_csv(Path(run) / "metrics" / "diagnostic_timeline" / f"{algorithm}.csv")
    times = np.asarray([float(row["bag_time_s"]) for row in rows], dtype=np.float64)
    positions = np.asarray([[float(row["x_m"]), float(row["y_m"]), float(row["z_m"])] for row in rows], dtype=np.float64)
    return times, positions


def _load_frame_index(run: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = load_json(Path(run) / "metrics" / "pointcloud_frame_index.json", {}) or {}
    frames = list(payload.get("frames") or [])
    return payload, frames


def _read_indexed_lidar_points(
    sqlite_db: Path,
    topic: str,
    topic_type: str,
    frames: Iterable[dict[str, Any]],
    *,
    point_step: int,
) -> list[tuple[float, np.ndarray]]:
    """Deserialize only selected indexed LiDAR messages; no bag replay is used."""
    if point_step < 1:
        raise ValueError("point_step must be >= 1")
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    message_class = get_message(topic_type)
    connection = sqlite3.connect(f"file:{Path(sqlite_db)}?mode=ro", uri=True)
    try:
        topic_row = connection.execute("SELECT id FROM topics WHERE name = ?", (topic,)).fetchone()
        if topic_row is None:
            raise ValueError(f"bag missing LiDAR topic {topic}")
        result: list[tuple[float, np.ndarray]] = []
        for frame in frames:
            row = connection.execute("SELECT data FROM messages WHERE id = ? AND topic_id = ?", (int(frame["message_id"]), int(topic_row[0]))).fetchone()
            if row is None:
                continue
            message = deserialize_message(row[0], message_class)
            if hasattr(message, "points"):
                selected = message.points[::point_step]
                xyz = np.asarray([[point.x, point.y, point.z] for point in selected], dtype=np.float64)
            elif hasattr(message, "fields"):
                # Keep the MVP focused on the greenhouse Livox CustomMsg path.
                raise ValueError("PointCloud2 on-demand rendering is not implemented in the Rerun MVP yet")
            else:
                raise ValueError(f"unsupported LiDAR message type: {type(message)!r}")
            valid = np.isfinite(xyz).all(axis=1)
            result.append((float(frame["bag_time_s"]), xyz[valid]))
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


def _send_blueprint(rr: Any, rrb: Any) -> None:
    blueprint = rrb.Blueprint(
        rrb.Vertical(
            rrb.Horizontal(
                rrb.Spatial3DView(name="Map + trajectories", origin="/world"),
                rrb.Vertical(
                    rrb.TimeSeriesView(name="CPU", origin="/metrics/cpu"),
                    rrb.TimeSeriesView(name="RSS", origin="/metrics/rss"),
                    rrb.TimeSeriesView(name="Motion anomalies", origin="/metrics/motion"),
                    row_shares=[1, 1, 1],
                ),
                column_shares=[2, 1],
            ),
            rrb.Horizontal(
                rrb.Spatial3DView(name="Current raw LiDAR", origin="/sensor"),
                rrb.TextLogView(name="Anomaly windows", origin="/events"),
                column_shares=[2, 1],
            ),
            row_shares=[3, 2],
        ),
        collapse_panels=True,
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
    save: Path | None,
    spawn: bool,
) -> dict[str, Any]:
    try:
        import rerun as rr
        import rerun.blueprint as rrb
    except ImportError as exc:
        raise RuntimeError("Rerun SDK is not installed. Install the tested viewer dependency with: python3 -m pip install 'rerun-sdk==0.36.3'") from exc

    run = Path(run).resolve()
    timeline = load_json(run / "metrics" / "diagnostic_timeline.json", {}) or {}
    windows = list(timeline.get("anomaly_windows") or [])
    transforms, origin = _alignment_for_trajectories(run, algorithms, baseline)

    rr.init("lio_benchmark_offline_diagnostic_viewer", spawn=spawn and save is None)
    if save is not None:
        save = Path(save).expanduser().resolve()
        save.parent.mkdir(parents=True, exist_ok=True)
        rr.save(str(save))
    _send_blueprint(rr, rrb)

    # Full aligned trajectories are static context; current positions below are temporal.
    for algorithm in algorithms:
        trajectory = load_trajectory(run / "standardized" / "trajectories" / f"{algorithm}.csv")
        rotation, translation = transforms[algorithm]
        aligned = apply_alignment(trajectory["positions"], rotation, translation) - origin
        rr.log(
            f"world/trajectories/{algorithm}",
            rr.LineStrips3D([aligned], colors=COLOR_RGB.get(algorithm, [180, 180, 180]), radii=0.025),
            static=True,
        )

        times, positions = _timeline_positions(run, algorithm)
        aligned_positions = apply_alignment(positions, rotation, translation) - origin
        for bag_time, position in zip(times, aligned_positions):
            rr.set_time("bag_time", duration=float(bag_time))
            rr.log(
                f"world/current/{algorithm}",
                rr.Points3D([position], colors=COLOR_RGB.get(algorithm, [180, 180, 180]), radii=0.18, labels=[LABELS.get(algorithm, algorithm)]),
            )

    if with_maps:
        map_dir = run / "figures" / "fast_livo2_baseline_maps"
        for algorithm in algorithms:
            path = map_dir / f"{algorithm}_map.ply"
            if not path.is_file():
                continue
            cloud = load_binary_little_endian_ply(path)
            shown = cloud[::max(1, int(map_point_step)), :3]
            rr.log(
                f"world/maps/{algorithm}",
                rr.Points3D(shown, colors=COLOR_RGB.get(algorithm, [160, 160, 160]), radii=0.015),
                static=True,
            )

    # Use the already synchronized 10 Hz rows for motion diagnostics and the
    # strict clock-aligned resource CSVs for actual resource sample timing.
    for algorithm in algorithms:
        timeline_rows = load_csv(run / "metrics" / "diagnostic_timeline" / f"{algorithm}.csv")
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
                for key, root in (("cpu_percent", "cpu"), ("rss_mib", "rss"), ("threads", "threads")):
                    value = _series_value(row, key)
                    if value is not None:
                        rr.log(f"metrics/{root}/{algorithm}", rr.Scalars(value))

    selected_windows = [item for item in windows if item.get("algorithm") in algorithms]
    for window in selected_windows:
        start = float(window["start_bag_time_s"])
        rr.set_time("bag_time", duration=start)
        rr.log(
            "events/anomaly_windows",
            rr.TextLog(
                f"{window['window_id']} | {LABELS.get(window['algorithm'], window['algorithm'])} | "
                f"{window['start_bag_time_s']:.2f}-{window['end_bag_time_s']:.2f}s | "
                f"types={','.join(window['types'])} | severity={window['severity']:.2f}"
            ),
        )
        rr.log(f"metrics/motion/anomaly_severity/{window['algorithm']}", rr.Scalars(float(window["severity"])))

    pointcloud_frames_logged = 0
    if pointcloud_mode != "none":
        index_payload, frames = _load_frame_index(run)
        if not frames:
            raise FileNotFoundError("pointcloud_frame_index.json is unavailable; run diagnostics --with-pointcloud-index first")
        selected_frames = select_pointcloud_frames(
            frames,
            selected_windows,
            period_s=pointcloud_period_s if pointcloud_mode == "sampled" else 0.0,
            include_anomalies=True,
        )
        scans = _read_indexed_lidar_points(
            Path(index_payload["sqlite_db"]),
            str(index_payload["lidar_topic"]),
            str(index_payload["lidar_type"]),
            selected_frames,
            point_step=point_step,
        )
        for bag_time, points in scans:
            rr.set_time("bag_time", duration=bag_time)
            rr.log("sensor/raw_lidar", rr.Points3D(points, radii=0.025))
        pointcloud_frames_logged = len(scans)

    return {
        "run": str(run),
        "algorithms": algorithms,
        "baseline": baseline,
        "anomaly_windows": len(selected_windows),
        "pointcloud_mode": pointcloud_mode,
        "pointcloud_frames_logged": pointcloud_frames_logged,
        "saved_rrd": str(save) if save is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the offline LIO benchmark diagnostic viewer")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--algorithms", help="comma-separated algorithm keys; default: all algorithms in diagnostic_timeline.json")
    parser.add_argument("--no-maps", action="store_true", help="skip reconstructed PLY maps")
    parser.add_argument("--map-point-step", type=int, default=4, help="display every Nth PLY point")
    parser.add_argument("--pointcloud-mode", choices=("none", "anomaly", "sampled"), default="anomaly")
    parser.add_argument("--pointcloud-period", type=float, default=1.0, help="seconds between raw scans in sampled mode")
    parser.add_argument("--point-step", type=int, default=20, help="display every Nth raw LiDAR point")
    parser.add_argument("--save", type=Path, help="write an .rrd recording instead of spawning a viewer")
    parser.add_argument("--no-spawn", action="store_true", help="do not spawn the native viewer")
    args = parser.parse_args()
    if args.map_point_step < 1 or args.point_step < 1 or args.pointcloud_period <= 0:
        raise ValueError("map/point steps must be >=1 and pointcloud period must be >0")

    run = args.run.resolve()
    algorithms = resolve_algorithms(run, args.algorithms)
    if args.baseline not in algorithms:
        algorithms = [args.baseline, *algorithms]
    result = log_recording(
        run,
        algorithms,
        baseline=args.baseline,
        with_maps=not args.no_maps,
        map_point_step=args.map_point_step,
        pointcloud_mode=args.pointcloud_mode,
        pointcloud_period_s=args.pointcloud_period,
        point_step=args.point_step,
        save=args.save,
        spawn=not args.no_spawn,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
