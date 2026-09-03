#!/usr/bin/env python3
"""Build a fixed-rate, bag-time diagnostic timeline for LIO benchmark runs.

This stage is intentionally post-processing only. It does not replay the
rosbag or launch any LIO algorithm. Standardized trajectories are resampled on
one bag-relative grid, anomaly events are grouped into review windows, and
resource samples are aligned through the existing clock-anchor evidence.

Without independent ground truth these quantities are diagnostic only.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from phase_analysis import _clock_anchors, _raw_directory, align_resource_samples
from plot_comparison_dashboard import LABELS, discover_algorithms, load_trajectory
from trajectory_discontinuity import (
    POSITION_JUMP_FLOOR_M,
    YAW_JUMP_FLOOR_DEG,
    resolve_time_origin,
    robust_jump_threshold,
)


METRIC_CLASS = "diagnostic/non-ground-truth"
DEFAULT_RESAMPLE_HZ = 10.0
DEFAULT_WINDOW_GAP_S = 1.0
DEFAULT_WINDOW_CONTEXT_S = 0.5
DEFAULT_RESOURCE_MAX_AGE_S = 1.0


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _finite_trajectory(trajectory: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    timestamps = np.asarray(trajectory["timestamp_s"], dtype=np.float64)
    positions = np.asarray(trajectory["positions"], dtype=np.float64)
    yaw = np.unwrap(np.asarray(trajectory["yaw_rad"], dtype=np.float64))
    if len(timestamps) < 2 or positions.shape != (len(timestamps), 3) or len(yaw) != len(timestamps):
        raise ValueError("trajectory must contain at least two aligned timestamp/XYZ/yaw samples")
    valid = np.isfinite(timestamps) & np.isfinite(positions).all(axis=1) & np.isfinite(yaw)
    timestamps, positions, yaw = timestamps[valid], positions[valid], yaw[valid]
    if len(timestamps) < 2:
        raise ValueError("trajectory contains fewer than two finite samples")
    order = np.argsort(timestamps, kind="stable")
    timestamps, positions, yaw = timestamps[order], positions[order], yaw[order]
    unique = np.r_[True, np.diff(timestamps) > 0.0]
    timestamps, positions, yaw = timestamps[unique], positions[unique], yaw[unique]
    if len(timestamps) < 2:
        raise ValueError("trajectory contains fewer than two unique timestamps")
    return timestamps, positions, yaw


def resample_fixed_rate(
    trajectory: dict[str, np.ndarray],
    origin_timestamp_s: float,
    hz: float = DEFAULT_RESAMPLE_HZ,
) -> list[dict[str, float]]:
    """Resample one trajectory on a grid anchored to the run sensor-time origin."""
    if hz <= 0:
        raise ValueError("hz must be > 0")
    timestamps, positions, yaw = _finite_trajectory(trajectory)
    origin = float(origin_timestamp_s)
    step = 1.0 / float(hz)

    # Anchor every algorithm to the same bag-relative multiples of 1/hz. This
    # removes output-frequency bias from cross-algorithm delta comparisons.
    first_index = int(math.ceil((float(timestamps[0]) - origin) * hz - 1e-9))
    last_index = int(math.floor((float(timestamps[-1]) - origin) * hz + 1e-9))
    if last_index < first_index:
        return []
    grid_index = np.arange(first_index, last_index + 1, dtype=np.int64)
    grid = origin + grid_index.astype(np.float64) * step

    xyz = np.column_stack(
        [np.interp(grid, timestamps, positions[:, axis]) for axis in range(3)]
    )
    yaw_interp = np.interp(grid, timestamps, yaw)

    delta_position = np.zeros(len(grid), dtype=np.float64)
    delta_yaw_signed_deg = np.zeros(len(grid), dtype=np.float64)
    if len(grid) > 1:
        delta_position[1:] = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
        delta_yaw_signed_deg[1:] = np.diff(yaw_interp) * 180.0 / np.pi
    delta_yaw = np.abs(delta_yaw_signed_deg)
    speed = delta_position / step
    yaw_rate = delta_yaw_signed_deg / step
    acceleration = np.zeros(len(grid), dtype=np.float64)
    if len(grid) > 1:
        acceleration[1:] = np.diff(speed) / step

    return [
        {
            "timestamp_s": float(grid[index]),
            "bag_time_s": float(grid[index] - origin),
            "x_m": float(xyz[index, 0]),
            "y_m": float(xyz[index, 1]),
            "z_m": float(xyz[index, 2]),
            "yaw_rad": float(yaw_interp[index]),
            "delta_position_m": float(delta_position[index]),
            "delta_yaw_deg": float(delta_yaw[index]),
            "speed_mps": float(speed[index]),
            "yaw_rate_deg_s": float(yaw_rate[index]),
            "acceleration_mps2": float(acceleration[index]),
        }
        for index in range(len(grid))
    ]


def detect_resampled_events(
    algorithm: str,
    rows: list[dict[str, float]],
    *,
    position_floor_m: float = POSITION_JUMP_FLOOR_M,
    yaw_floor_deg: float = YAW_JUMP_FLOOR_DEG,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Detect outlier jumps after every algorithm has been normalized to one rate."""
    if not rows:
        return [], {
            "position_jump_threshold_m": float(position_floor_m),
            "yaw_jump_threshold_deg": float(yaw_floor_deg),
        }
    position_values = np.asarray([row["delta_position_m"] for row in rows], dtype=np.float64)
    yaw_values = np.asarray([row["delta_yaw_deg"] for row in rows], dtype=np.float64)
    position_threshold = robust_jump_threshold(position_values[1:], position_floor_m)
    yaw_threshold = robust_jump_threshold(yaw_values[1:], yaw_floor_deg)

    events: list[dict[str, Any]] = []
    for row in rows[1:]:
        common = {
            "algorithm": algorithm,
            "timestamp_s": float(row["timestamp_s"]),
            "bag_time_s": float(row["bag_time_s"]),
            "relative_time_s": float(row["bag_time_s"]),
            "position_step_m": float(row["delta_position_m"]),
            "yaw_step_deg": float(row["delta_yaw_deg"]),
            "speed_mps": float(row["speed_mps"]),
            "yaw_rate_deg_s": float(row["yaw_rate_deg_s"]),
            "x_m": float(row["x_m"]),
            "y_m": float(row["y_m"]),
            "z_m": float(row["z_m"]),
        }
        if float(row["delta_position_m"]) > position_threshold:
            events.append(
                {
                    **common,
                    "type": "position_jump",
                    "threshold": float(position_threshold),
                }
            )
        if float(row["delta_yaw_deg"]) > yaw_threshold:
            events.append(
                {
                    **common,
                    "type": "yaw_jump",
                    "threshold": float(yaw_threshold),
                }
            )
    events.sort(key=lambda item: (item["bag_time_s"], item["type"]))
    return events, {
        "position_jump_threshold_m": float(position_threshold),
        "yaw_jump_threshold_deg": float(yaw_threshold),
    }


def _event_severity(event: dict[str, Any]) -> float:
    threshold = max(float(event.get("threshold") or 0.0), 1e-12)
    if event.get("type") == "yaw_jump":
        return float(event.get("yaw_step_deg") or 0.0) / threshold
    return float(event.get("position_step_m") or 0.0) / threshold


def cluster_anomaly_windows(
    events: list[dict[str, Any]],
    *,
    max_gap_s: float = DEFAULT_WINDOW_GAP_S,
    context_s: float = DEFAULT_WINDOW_CONTEXT_S,
) -> list[dict[str, Any]]:
    """Group dense per-algorithm events into reviewable anomaly windows."""
    if max_gap_s < 0 or context_s < 0:
        raise ValueError("max_gap_s and context_s must be >= 0")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        algorithm = str(event.get("algorithm") or "")
        if not algorithm:
            continue
        if event.get("bag_time_s") is None:
            if event.get("relative_time_s") is None:
                continue
            event = {**event, "bag_time_s": float(event["relative_time_s"])}
        grouped.setdefault(algorithm, []).append(event)

    windows: list[dict[str, Any]] = []
    for algorithm in sorted(grouped):
        ordered = sorted(grouped[algorithm], key=lambda item: float(item["bag_time_s"]))
        clusters: list[list[dict[str, Any]]] = []
        for event in ordered:
            if not clusters:
                clusters.append([event])
                continue
            previous_time = float(clusters[-1][-1]["bag_time_s"])
            current_time = float(event["bag_time_s"])
            if current_time - previous_time <= max_gap_s + 1e-12:
                clusters[-1].append(event)
            else:
                clusters.append([event])

        for index, cluster in enumerate(clusters, start=1):
            start = float(cluster[0]["bag_time_s"])
            end = float(cluster[-1]["bag_time_s"])
            severity = max((_event_severity(item) for item in cluster), default=0.0)
            types = sorted({str(item.get("type")) for item in cluster if item.get("type")})
            windows.append(
                {
                    "window_id": f"{algorithm}:window_{index:04d}",
                    "algorithm": algorithm,
                    "start_bag_time_s": start,
                    "end_bag_time_s": end,
                    "center_bag_time_s": 0.5 * (start + end),
                    "view_start_bag_time_s": max(0.0, start - context_s),
                    "view_end_bag_time_s": end + context_s,
                    "duration_s": max(0.0, end - start),
                    "event_count": len(cluster),
                    "types": types,
                    "peak_position_step_m": max(
                        (float(item.get("position_step_m") or 0.0) for item in cluster),
                        default=0.0,
                    ),
                    "peak_yaw_step_deg": max(
                        (float(item.get("yaw_step_deg") or 0.0) for item in cluster),
                        default=0.0,
                    ),
                    "severity": float(severity),
                    "events": cluster,
                }
            )
    windows.sort(key=lambda item: (item["start_bag_time_s"], item["algorithm"]))
    return windows


def aligned_resource_rows(
    aligned_samples: list[dict[str, Any]],
    origin_timestamp_s: float,
) -> list[dict[str, Any]]:
    """Convert phase-analysis aligned resource samples into bag-relative rows."""
    result: list[dict[str, Any]] = []
    origin = float(origin_timestamp_s)
    for sample in aligned_samples:
        try:
            header_time = float(sample["trajectory_time_s"])
        except (KeyError, TypeError, ValueError):
            continue
        if not np.isfinite(header_time):
            continue
        rss_bytes = sample.get("rss_bytes")
        row = {
            "timestamp_s": header_time,
            "bag_time_s": header_time - origin,
            "recorded_timestamp_s": (
                float(sample["recorded_time_s"])
                if sample.get("recorded_time_s") is not None
                else None
            ),
            "wall_time": sample.get("at"),
            "cpu_percent": (
                float(sample["cpu_percent"])
                if sample.get("cpu_percent") is not None
                else None
            ),
            "rss_mib": (
                float(rss_bytes) / (1024.0 * 1024.0)
                if rss_bytes is not None
                else None
            ),
            "threads": (
                int(sample["threads"]) if sample.get("threads") is not None else None
            ),
            "write_bytes": (
                int(sample["write_bytes"])
                if sample.get("write_bytes") is not None
                else None
            ),
        }
        result.append(row)
    result.sort(key=lambda item: item["bag_time_s"])
    return result


def nearest_resource_sample(
    resources: list[dict[str, Any]],
    bag_time_s: float,
    *,
    max_age_s: float = DEFAULT_RESOURCE_MAX_AGE_S,
) -> tuple[dict[str, Any] | None, float | None]:
    """Return the closest aligned resource sample inside the allowed age."""
    if max_age_s < 0:
        raise ValueError("max_age_s must be >= 0")
    if not resources:
        return None, None
    times = [float(item["bag_time_s"]) for item in resources]
    index = bisect.bisect_left(times, float(bag_time_s))
    candidates = []
    if index < len(resources):
        candidates.append(resources[index])
    if index > 0:
        candidates.append(resources[index - 1])
    if not candidates:
        return None, None
    sample = min(candidates, key=lambda item: abs(float(item["bag_time_s"]) - float(bag_time_s)))
    age = abs(float(sample["bag_time_s"]) - float(bag_time_s))
    if age > max_age_s + 1e-12:
        return None, None
    return sample, float(age)


def _attach_resource_samples(
    rows: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    *,
    mode: str,
    max_age_s: float,
) -> None:
    if not resources:
        for row in rows:
            row.update(
                {
                    "resource_alignment_mode": mode,
                    "resource_age_s": None,
                    "cpu_percent": None,
                    "rss_mib": None,
                    "threads": None,
                    "write_bytes": None,
                }
            )
        return

    times = np.asarray([float(item["bag_time_s"]) for item in resources], dtype=np.float64)
    queries = np.asarray([float(row["bag_time_s"]) for row in rows], dtype=np.float64)
    insertions = np.searchsorted(times, queries, side="left")
    for row, query, insertion in zip(rows, queries, insertions):
        indices = []
        if insertion < len(resources):
            indices.append(int(insertion))
        if insertion > 0:
            indices.append(int(insertion - 1))
        if not indices:
            nearest = None
            age = None
        else:
            selected = min(indices, key=lambda idx: abs(times[idx] - query))
            candidate_age = abs(float(times[selected] - query))
            if candidate_age <= max_age_s + 1e-12:
                nearest = resources[selected]
                age = candidate_age
            else:
                nearest = None
                age = None
        row["resource_alignment_mode"] = mode
        row["resource_age_s"] = float(age) if age is not None else None
        for key in ("cpu_percent", "rss_mib", "threads", "write_bytes"):
            row[key] = nearest.get(key) if nearest is not None else None


def _tag_anomaly_windows(
    rows: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    algorithm: str,
) -> None:
    selected = [item for item in windows if item["algorithm"] == algorithm]
    for row in rows:
        timestamp = float(row["bag_time_s"])
        active = [
            item
            for item in selected
            if float(item["start_bag_time_s"]) - 1e-9
            <= timestamp
            <= float(item["end_bag_time_s"]) + 1e-9
        ]
        row["anomaly_window_ids"] = ";".join(item["window_id"] for item in active)
        row["anomaly_types"] = ";".join(
            sorted({value for item in active for value in item.get("types", [])})
        )


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _plot_fixed_rate(
    path: Path,
    rows_by_algorithm: dict[str, list[dict[str, Any]]],
    windows: list[dict[str, Any]],
    *,
    value_key: str,
    ylabel: str,
    title: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(14, 7), constrained_layout=True)
    for algorithm, rows in rows_by_algorithm.items():
        if not rows:
            continue
        values = np.maximum(
            np.asarray([abs(float(row[value_key])) for row in rows], dtype=np.float64),
            1e-6,
        )
        axis.plot(
            [row["bag_time_s"] for row in rows],
            values,
            linewidth=0.8,
            alpha=0.75,
            label=LABELS.get(algorithm, algorithm),
        )
        centers = [
            item["center_bag_time_s"] for item in windows if item["algorithm"] == algorithm
        ]
        if centers:
            row_times = np.asarray([row["bag_time_s"] for row in rows], dtype=np.float64)
            indices = [int(np.argmin(np.abs(row_times - center))) for center in centers]
            axis.scatter(
                [rows[index]["bag_time_s"] for index in indices],
                [max(abs(float(rows[index][value_key])), 1e-6) for index in indices],
                marker="x",
                s=22,
            )
    axis.set_yscale("log")
    axis.set_xlabel("Bag-relative time (s)")
    axis.set_ylabel(ylabel)
    axis.set_title(title)
    axis.grid(alpha=0.2)
    axis.legend(fontsize=8, ncol=2)
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _plot_aligned_resource(
    path: Path,
    resources_by_algorithm: dict[str, list[dict[str, Any]]],
    *,
    value_key: str,
    ylabel: str,
    title: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(14, 7), constrained_layout=True)
    plotted = False
    for algorithm, rows in resources_by_algorithm.items():
        usable = [row for row in rows if row.get(value_key) is not None]
        if not usable:
            continue
        plotted = True
        axis.plot(
            [row["bag_time_s"] for row in usable],
            [row[value_key] for row in usable],
            linewidth=0.9,
            alpha=0.8,
            label=LABELS.get(algorithm, algorithm),
        )
    if not plotted:
        plt.close(figure)
        return
    axis.set_xlabel("Bag-relative time (s)")
    axis.set_ylabel(ylabel)
    axis.set_title(title)
    axis.grid(alpha=0.2)
    axis.legend(fontsize=8, ncol=2)
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Unified diagnostic timeline",
        "",
        f"- Baseline: `{payload['baseline']}`",
        f"- Time origin: `{payload['origin_source']}` = `{payload['origin_timestamp_s']:.9f}`",
        f"- Fixed trajectory rate: `{payload['resample_hz']:.3f} Hz`",
        f"- Metric class: `{METRIC_CLASS}`",
        "- Cross-algorithm delta comparisons use the fixed-rate timeline; raw per-output-step diagnostics remain available separately for audit.",
        "- Anomaly windows are diagnostic review regions and do not automatically change trajectory health.",
        "",
        "| Algorithm | 10 Hz samples | Events | Windows | Resource mode | Resource samples | Resource warnings |",
        "|---|---:|---:|---:|---|---:|---|",
    ]
    for algorithm in payload["algorithm_order"]:
        item = payload["algorithms"][algorithm]
        warnings = "; ".join(item.get("resource_warnings") or []) or "none"
        lines.append(
            f"| {LABELS.get(algorithm, algorithm)} | {item['timeline_samples']} | "
            f"{item['event_count']} | {item['window_count']} | "
            f"{item['resource_alignment_mode']} | {item['resource_samples']} | {warnings} |"
        )

    lines.extend(
        [
            "",
            "## Anomaly windows",
            "",
            "| ID | Algorithm | Start (s) | End (s) | Events | Types | Peak Δpos (m) | Peak Δyaw (deg) | Severity | Review view (s) |",
            "|---|---|---:|---:|---:|---|---:|---:|---:|---|",
        ]
    )
    for item in payload["anomaly_windows"]:
        lines.append(
            f"| {item['window_id']} | {LABELS.get(item['algorithm'], item['algorithm'])} | "
            f"{item['start_bag_time_s']:.3f} | {item['end_bag_time_s']:.3f} | "
            f"{item['event_count']} | {';'.join(item['types'])} | "
            f"{item['peak_position_step_m']:.3f} | {item['peak_yaw_step_deg']:.3f} | "
            f"{item['severity']:.2f} | "
            f"{item['view_start_bag_time_s']:.3f}–{item['view_end_bag_time_s']:.3f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--hz", type=float, default=DEFAULT_RESAMPLE_HZ)
    parser.add_argument("--window-gap", type=float, default=DEFAULT_WINDOW_GAP_S)
    parser.add_argument("--window-context", type=float, default=DEFAULT_WINDOW_CONTEXT_S)
    parser.add_argument("--resource-max-age", type=float, default=DEFAULT_RESOURCE_MAX_AGE_S)
    parser.add_argument("--position-floor-m", type=float, default=POSITION_JUMP_FLOOR_M)
    parser.add_argument("--yaw-floor-deg", type=float, default=YAW_JUMP_FLOOR_DEG)
    args = parser.parse_args()
    if args.hz <= 0:
        raise ValueError("--hz must be > 0")
    if args.window_gap < 0 or args.window_context < 0 or args.resource_max_age < 0:
        raise ValueError("window/resource timing parameters must be >= 0")

    run = args.run.resolve()
    manifest = load_json(run / "manifest.json", {}) or {}
    run_status = load_json(run / "metadata" / "run_status.json", {}) or {}
    bag_analysis = load_json(run / "metrics" / "bag_analysis.json", {}) or {}
    algorithms = discover_algorithms(run)
    if args.baseline not in algorithms:
        raise ValueError(f"baseline standardized trajectory is unavailable: {args.baseline}")

    trajectory_dir = run / "standardized" / "trajectories"
    trajectories = {
        algorithm: load_trajectory(trajectory_dir / f"{algorithm}.csv")
        for algorithm in algorithms
    }
    origin_timestamp_s, origin_source = resolve_time_origin(run, trajectories[args.baseline])
    dataset = manifest.get("dataset") or {}
    lidar_topic = str(dataset.get("lidar_topic") or "")
    playback_rate = float(manifest.get("playback_rate") or 1.0)

    rows_by_algorithm: dict[str, list[dict[str, Any]]] = {}
    resources_by_algorithm: dict[str, list[dict[str, Any]]] = {}
    algorithm_metadata: dict[str, dict[str, Any]] = {}
    all_events: list[dict[str, Any]] = []

    for algorithm in algorithms:
        rows = resample_fixed_rate(
            trajectories[algorithm],
            origin_timestamp_s,
            hz=args.hz,
        )
        events, thresholds = detect_resampled_events(
            algorithm,
            rows,
            position_floor_m=args.position_floor_m,
            yaw_floor_deg=args.yaw_floor_deg,
        )
        all_events.extend(events)

        raw = _raw_directory(run, algorithm, run_status)
        monitor = load_json(raw / "resource_monitor.json", {}) or {}
        anchors = _clock_anchors(raw / "clock_anchors.json")
        mode, aligned, evidence, warnings = align_resource_samples(
            monitor,
            algorithm,
            run_status,
            bag_analysis,
            lidar_topic,
            anchors,
            playback_rate=playback_rate,
        )
        resource_rows = aligned_resource_rows(aligned, origin_timestamp_s)
        _attach_resource_samples(
            rows,
            resource_rows,
            mode=mode,
            max_age_s=args.resource_max_age,
        )
        rows_by_algorithm[algorithm] = rows
        resources_by_algorithm[algorithm] = resource_rows
        algorithm_metadata[algorithm] = {
            "timeline_samples": len(rows),
            "event_count": len(events),
            "position_jump_count": sum(item["type"] == "position_jump" for item in events),
            "yaw_jump_count": sum(item["type"] == "yaw_jump" for item in events),
            **thresholds,
            "resource_alignment_mode": mode,
            "resource_samples": len(resource_rows),
            "resource_warnings": warnings,
            "resource_alignment_evidence": evidence,
        }

    all_events.sort(key=lambda item: (item["bag_time_s"], item["algorithm"], item["type"]))
    windows = cluster_anomaly_windows(
        all_events,
        max_gap_s=args.window_gap,
        context_s=args.window_context,
    )
    for algorithm, rows in rows_by_algorithm.items():
        _tag_anomaly_windows(rows, windows, algorithm)
        algorithm_metadata[algorithm]["window_count"] = sum(
            item["algorithm"] == algorithm for item in windows
        )

    timeline_dir = run / "metrics" / "diagnostic_timeline"
    resource_dir = timeline_dir / "resources"
    timeline_fields = [
        "timestamp_s",
        "bag_time_s",
        "x_m",
        "y_m",
        "z_m",
        "yaw_rad",
        "delta_position_m",
        "delta_yaw_deg",
        "speed_mps",
        "yaw_rate_deg_s",
        "acceleration_mps2",
        "resource_alignment_mode",
        "resource_age_s",
        "cpu_percent",
        "rss_mib",
        "threads",
        "write_bytes",
        "anomaly_window_ids",
        "anomaly_types",
    ]
    resource_fields = [
        "timestamp_s",
        "bag_time_s",
        "recorded_timestamp_s",
        "wall_time",
        "cpu_percent",
        "rss_mib",
        "threads",
        "write_bytes",
    ]
    for algorithm in algorithms:
        _write_csv(timeline_dir / f"{algorithm}.csv", rows_by_algorithm[algorithm], timeline_fields)
        _write_csv(resource_dir / f"{algorithm}.csv", resources_by_algorithm[algorithm], resource_fields)

    payload = {
        "schema_version": 1,
        "metric_class": METRIC_CLASS,
        "baseline": args.baseline,
        "origin_timestamp_s": origin_timestamp_s,
        "origin_source": origin_source,
        "resample_hz": float(args.hz),
        "window_policy": {
            "max_gap_s": float(args.window_gap),
            "context_s": float(args.window_context),
        },
        "resource_max_age_s": float(args.resource_max_age),
        "algorithm_order": algorithms,
        "algorithms": algorithm_metadata,
        "events": all_events,
        "anomaly_windows": windows,
    }
    (run / "metrics" / "diagnostic_timeline.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    reports = run / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    _write_markdown(reports / "diagnostic_timeline.md", payload)

    figures = run / "figures" / "diagnostic_timeline"
    figures.mkdir(parents=True, exist_ok=True)
    _plot_fixed_rate(
        figures / "position_step_10hz.png",
        rows_by_algorithm,
        windows,
        value_key="delta_position_m",
        ylabel=f"Δposition per {1.0 / args.hz:.3f} s sample (m, log scale)",
        title=f"Fixed-rate trajectory position-step timeline ({args.hz:g} Hz)",
    )
    _plot_fixed_rate(
        figures / "yaw_step_10hz.png",
        rows_by_algorithm,
        windows,
        value_key="delta_yaw_deg",
        ylabel=f"|Δyaw| per {1.0 / args.hz:.3f} s sample (deg, log scale)",
        title=f"Fixed-rate trajectory yaw-step timeline ({args.hz:g} Hz)",
    )
    _plot_aligned_resource(
        figures / "cpu_aligned.png",
        resources_by_algorithm,
        value_key="cpu_percent",
        ylabel="CPU (%) — 100% = one logical core",
        title="Clock-aligned process-tree CPU timeline",
    )
    _plot_aligned_resource(
        figures / "rss_aligned.png",
        resources_by_algorithm,
        value_key="rss_mib",
        ylabel="RSS (MiB)",
        title="Clock-aligned process-tree RSS timeline",
    )

    print(
        json.dumps(
            {
                "output": str(run / "metrics" / "diagnostic_timeline.json"),
                "algorithms": len(algorithms),
                "events": len(all_events),
                "windows": len(windows),
                "resample_hz": float(args.hz),
                "origin_timestamp_s": origin_timestamp_s,
                "origin_source": origin_source,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
