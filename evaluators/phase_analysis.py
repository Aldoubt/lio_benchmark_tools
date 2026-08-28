#!/usr/bin/env python3
"""Offline phase-aware diagnostic analysis for standardized LIO benchmark runs.

The module deliberately keeps trajectory comparisons relative to a selected
baseline. It does not report ATE/RPE without independent ground truth.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import statistics
from pathlib import Path
from typing import Any

import numpy as np


METRIC_CLASS = "relative-to-baseline/diagnostic/non-ground-truth"
DEFAULT_PHASE_PARAMETERS: dict[str, float] = {
    "resample_hz": 10.0,
    "stationary_speed_mps": 0.05,
    "turn_yaw_rate_deg_s": 8.0,
    "high_curvature_1pm": 0.12,
    "min_phase_duration_s": 1.5,
    "sustained_motion_s": 2.0,
    "near_start_radius_m": 3.0,
}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def _parse_iso_seconds(value: str) -> float:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def piecewise_wall_to_recorded(wall_time_s: float, anchors: list[dict[str, Any]]) -> float | None:
    """Map wall-clock epoch seconds to recorded ROS time inside known anchors."""
    usable = []
    for item in anchors:
        if item.get("wall_time_ns") is None:
            continue
        ros_time = item.get("ros_time_s")
        if ros_time is None and item.get("ros_time_ns") is not None:
            ros_time = float(item["ros_time_ns"]) * 1e-9
        if ros_time is None:
            continue
        usable.append((float(item["wall_time_ns"]) * 1e-9, float(ros_time)))
    usable.sort()
    if len(usable) < 2 or wall_time_s < usable[0][0] or wall_time_s > usable[-1][0]:
        return None
    for (w0, r0), (w1, r1) in zip(usable, usable[1:]):
        if w0 <= wall_time_s <= w1:
            if w1 <= w0:
                return r0
            ratio = (wall_time_s - w0) / (w1 - w0)
            return r0 + ratio * (r1 - r0)
    return None


def recorded_to_header_offset(
    bag_analysis: dict[str, Any], lidar_topic: str
) -> tuple[float | None, dict[str, Any], list[str]]:
    """Return recorded-minus-header median seconds and its evidence."""
    topic = (bag_analysis.get("topics") or {}).get(lidar_topic) or {}
    stats = topic.get("record_minus_header_s") or {}
    median = stats.get("median")
    evidence = {
        "source": f"bag_analysis:{lidar_topic}:record_minus_header_s",
        "count": stats.get("count", 0),
        "median_s": median,
        "mean_s": stats.get("mean"),
        "std_s": stats.get("std"),
        "min_s": stats.get("min"),
        "max_s": stats.get("max"),
        "recorded_first_s": topic.get("recorded_first_s"),
        "header_first_s": topic.get("header_first_s"),
    }
    warnings: list[str] = []
    if median is None or int(stats.get("count") or 0) < 1:
        warnings.append(f"missing recorded/header offset evidence for {lidar_topic}")
        return None, evidence, warnings
    std = stats.get("std")
    if std is not None and float(std) > 0.05:
        warnings.append(f"recorded/header offset varies by std={float(std):.3f}s")
    return float(median), evidence, warnings


def _playback_event(status: dict[str, Any], algorithm: str) -> dict[str, Any] | None:
    for event in status.get("events") or []:
        if event.get("algorithm") == algorithm and event.get("bag_playback") == "running" and event.get("at"):
            return event
    return None


def align_resource_samples(
    resource_monitor: dict[str, Any],
    algorithm: str,
    run_status: dict[str, Any],
    bag_analysis: dict[str, Any],
    lidar_topic: str,
    clock_anchors: list[dict[str, Any]] | None,
    *,
    playback_rate: float,
) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[str]]:
    """Map resource samples from wall clock into trajectory/header time."""
    samples = list(resource_monitor.get("sample_history") or [])
    offset, offset_evidence, offset_warnings = recorded_to_header_offset(bag_analysis, lidar_topic)
    evidence: dict[str, Any] = {"clock_to_trajectory_offset": offset_evidence}
    warnings = list(offset_warnings)
    if not samples:
        warnings.append(f"{algorithm}: resource monitor has no sample_history")
        return "trajectory-only", [], evidence, warnings
    if offset is None:
        return "trajectory-only", [], evidence, warnings

    if clock_anchors and len(clock_anchors) >= 2:
        aligned: list[dict[str, Any]] = []
        outside = 0
        for sample in samples:
            try:
                wall = _parse_iso_seconds(str(sample["at"]))
            except (KeyError, TypeError, ValueError):
                outside += 1
                continue
            recorded = piecewise_wall_to_recorded(wall, clock_anchors)
            if recorded is None:
                outside += 1
                continue
            aligned.append({**sample, "recorded_time_s": recorded, "trajectory_time_s": recorded - offset})
        evidence.update({"clock_anchor_count": len(clock_anchors), "outside_anchor_samples": outside})
        if aligned:
            return "strict/clock-anchored", aligned, evidence, warnings
        warnings.append(f"{algorithm}: no resource samples fall inside clock anchor range")
        return "trajectory-only", [], evidence, warnings

    playback = _playback_event(run_status, algorithm)
    topic = (bag_analysis.get("topics") or {}).get(lidar_topic) or {}
    recorded_start = topic.get("recorded_first_s")
    if playback is None or recorded_start is None or playback_rate <= 0:
        warnings.append(f"{algorithm}: insufficient lifecycle evidence for approximate resource alignment")
        return "trajectory-only", [], evidence, warnings
    try:
        playback_wall = _parse_iso_seconds(str(playback["at"]))
    except (TypeError, ValueError):
        warnings.append(f"{algorithm}: invalid lifecycle playback timestamp")
        return "trajectory-only", [], evidence, warnings

    aligned = []
    for sample in samples:
        try:
            wall = _parse_iso_seconds(str(sample["at"]))
        except (KeyError, TypeError, ValueError):
            continue
        recorded = float(recorded_start) + (wall - playback_wall) * playback_rate
        aligned.append({**sample, "recorded_time_s": recorded, "trajectory_time_s": recorded - offset})
    evidence.update(
        {
            "playback_wall_at": playback["at"],
            "recorded_start_s": float(recorded_start),
            "playback_rate": float(playback_rate),
        }
    )
    warnings.append(
        f"{algorithm}: approximate lifecycle alignment; sub-second resource/trajectory coincidence is not strict evidence"
    )
    return "approximate/lifecycle-aligned", aligned, evidence, warnings


def load_trajectory_csv(path: Path) -> list[dict[str, float]]:
    with path.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    result: list[dict[str, float]] = []
    for row in rows:
        result.append(
            {
                "timestamp_s": float(row["timestamp_s"]),
                "x_m": float(row["x_m"]),
                "y_m": float(row["y_m"]),
                "z_m": float(row["z_m"]),
                "roll_rad": float(row.get("roll_rad") or 0.0),
                "pitch_rad": float(row.get("pitch_rad") or 0.0),
                "yaw_rad": float(row.get("yaw_rad") or 0.0),
            }
        )
    result.sort(key=lambda item: item["timestamp_s"])
    unique: list[dict[str, float]] = []
    last: float | None = None
    for row in result:
        if last is None or row["timestamp_s"] > last:
            unique.append(row)
            last = row["timestamp_s"]
    if len(unique) < 2:
        raise ValueError(f"trajectory has fewer than two unique timestamps: {path}")
    return unique


def _trajectory_arrays(rows: list[dict[str, float]]) -> dict[str, np.ndarray]:
    keys = ("timestamp_s", "x_m", "y_m", "z_m", "roll_rad", "pitch_rad", "yaw_rad")
    arrays = {key: np.asarray([float(row.get(key, 0.0)) for row in rows], dtype=np.float64) for key in keys}
    arrays["yaw_rad"] = np.unwrap(arrays["yaw_rad"])
    return arrays


def _interp(arrays: dict[str, np.ndarray], key: str, times: np.ndarray) -> np.ndarray:
    return np.interp(times, arrays["timestamp_s"], arrays[key])


def _resampled_motion(rows: list[dict[str, float]], hz: float) -> list[dict[str, float]]:
    arrays = _trajectory_arrays(rows)
    start, end = float(arrays["timestamp_s"][0]), float(arrays["timestamp_s"][-1])
    step = 1.0 / hz
    count = max(2, int(math.floor((end - start) / step)) + 1)
    times = start + np.arange(count, dtype=np.float64) * step
    if end - times[-1] > step * 0.25:
        times = np.append(times, end)
    x, y, z = (_interp(arrays, key, times) for key in ("x_m", "y_m", "z_m"))
    yaw = _interp(arrays, "yaw_rad", times)
    roll = _interp(arrays, "roll_rad", times)
    pitch = _interp(arrays, "pitch_rad", times)
    speed = np.zeros_like(times)
    yaw_rate = np.zeros_like(times)
    if len(times) > 1:
        dt_values = np.diff(times)
        speed[1:] = np.hypot(np.diff(x), np.diff(y)) / np.maximum(dt_values, 1e-9)
        yaw_rate[1:] = np.diff(yaw) / np.maximum(dt_values, 1e-9)
    curvature = np.abs(yaw_rate) / np.maximum(speed, 1e-6)
    distance_to_start = np.hypot(x - x[0], y - y[0])
    return [
        {
            "timestamp_s": float(times[i]),
            "x_m": float(x[i]),
            "y_m": float(y[i]),
            "z_m": float(z[i]),
            "roll_rad": float(roll[i]),
            "pitch_rad": float(pitch[i]),
            "yaw_rad": float(yaw[i]),
            "speed_mps": float(speed[i]),
            "yaw_rate_rad_s": float(yaw_rate[i]),
            "curvature_1pm": float(curvature[i]),
            "distance_to_start_m": float(distance_to_start[i]),
        }
        for i in range(len(times))
    ]


def _segments(samples: list[dict[str, Any]]) -> list[tuple[int, int, str]]:
    if not samples:
        return []
    out: list[tuple[int, int, str]] = []
    start = 0
    state = str(samples[0]["state"])
    for index in range(1, len(samples)):
        current = str(samples[index]["state"])
        if current != state:
            out.append((start, index - 1, state))
            start, state = index, current
    out.append((start, len(samples) - 1, state))
    return out


def _segment_duration(samples: list[dict[str, Any]], segment: tuple[int, int, str], step: float) -> float:
    start, end, _ = segment
    return max(step, float(samples[end]["timestamp_s"] - samples[start]["timestamp_s"] + step))


def _merge_short_states(samples: list[dict[str, Any]], min_duration: float, step: float) -> None:
    for _ in range(max(1, len(samples))):
        segments = _segments(samples)
        target = next((segment for segment in segments if _segment_duration(samples, segment, step) < min_duration), None)
        if target is None or len(segments) == 1:
            return
        index = segments.index(target)
        left = segments[index - 1] if index > 0 else None
        right = segments[index + 1] if index + 1 < len(segments) else None
        if left and right and left[2] == right[2]:
            replacement = left[2]
        elif left is None:
            replacement = right[2]
        elif right is None:
            replacement = left[2]
        else:
            left_duration = _segment_duration(samples, left, step)
            right_duration = _segment_duration(samples, right, step)
            replacement = left[2] if left_duration >= right_duration else right[2]
        for sample_index in range(target[0], target[1] + 1):
            samples[sample_index]["state"] = replacement


def build_phases(
    baseline_rows: list[dict[str, float]], phase_parameters: dict[str, float] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    params = dict(DEFAULT_PHASE_PARAMETERS)
    if phase_parameters:
        params.update({key: float(value) for key, value in phase_parameters.items()})
    hz = params["resample_hz"]
    if hz <= 0:
        raise ValueError("resample_hz must be positive")
    samples = _resampled_motion(baseline_rows, hz)
    step = 1.0 / hz
    motion_count = max(1, int(math.ceil(params["sustained_motion_s"] * hz)))
    moving = [sample["speed_mps"] >= params["stationary_speed_mps"] for sample in samples]
    motion_start = len(samples)
    for index in range(0, len(samples) - motion_count + 1):
        if all(moving[index : index + motion_count]):
            motion_start = index
            break
    turn_threshold = math.radians(params["turn_yaw_rate_deg_s"])
    for index, sample in enumerate(samples):
        if index < motion_start:
            state = "INITIALIZATION"
        elif sample["speed_mps"] < params["stationary_speed_mps"]:
            state = "STATIONARY"
        elif abs(sample["yaw_rate_rad_s"]) > turn_threshold:
            state = "TURN"
        elif sample["curvature_1pm"] > params["high_curvature_1pm"]:
            state = "HIGH_CURVATURE"
        else:
            state = "STRAIGHT"
        sample["state"] = state
        sample["return_near_start"] = bool(
            index >= motion_start and sample["distance_to_start_m"] <= params["near_start_radius_m"]
        )
    _merge_short_states(samples, params["min_phase_duration_s"], step)

    phases: list[dict[str, Any]] = []
    for number, (start_i, end_i, state) in enumerate(_segments(samples)):
        start_s = float(samples[start_i]["timestamp_s"])
        end_s = (
            float(samples[end_i + 1]["timestamp_s"])
            if end_i + 1 < len(samples)
            else float(samples[end_i]["timestamp_s"])
        )
        if end_s <= start_s:
            end_s = start_s + step
        phases.append(
            {
                "id": f"phase_{number:03d}",
                "state": state,
                "start_s": start_s,
                "end_s": end_s,
                "duration_s": end_s - start_s,
                "return_near_start": any(bool(samples[i]["return_near_start"]) for i in range(start_i, end_i + 1)),
                "baseline_samples": end_i - start_i + 1,
            }
        )
    return samples, phases


def _initial_yaw_translation(
    baseline: list[dict[str, float]], candidate: list[dict[str, float]], start: float
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    base = _trajectory_arrays(baseline)
    candidate_arrays = _trajectory_arrays(candidate)
    base_yaw = float(_interp(base, "yaw_rad", np.asarray([start]))[0])
    candidate_yaw = float(_interp(candidate_arrays, "yaw_rad", np.asarray([start]))[0])
    delta = base_yaw - candidate_yaw
    c, s = math.cos(delta), math.sin(delta)
    rotation = np.asarray([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    base_start = np.asarray([_interp(base, key, np.asarray([start]))[0] for key in ("x_m", "y_m", "z_m")])
    candidate_start = np.asarray([_interp(candidate_arrays, key, np.asarray([start]))[0] for key in ("x_m", "y_m", "z_m")])
    translation = base_start - rotation @ candidate_start
    return rotation, translation, {"yaw_delta_rad": delta}


def compute_phase_trajectory_metrics(
    baseline: list[dict[str, float]],
    candidate: list[dict[str, float]],
    phase: dict[str, Any],
    *,
    resample_hz: float,
) -> dict[str, Any]:
    base = _trajectory_arrays(baseline)
    candidate_arrays = _trajectory_arrays(candidate)
    phase_start, phase_end = float(phase["start_s"]), float(phase["end_s"])
    common_start = max(phase_start, float(base["timestamp_s"][0]), float(candidate_arrays["timestamp_s"][0]))
    common_end = min(phase_end, float(base["timestamp_s"][-1]), float(candidate_arrays["timestamp_s"][-1]))
    phase_duration = max(1e-9, phase_end - phase_start)
    if common_end <= common_start:
        return {
            "samples": 0,
            "coverage_ratio": 0.0,
            "max_sample_gap_s": None,
            "relative_position_rmse_m": None,
            "relative_position_p95_m": None,
            "relative_z_rmse_m": None,
            "z_change_m": None,
            "roll_range_deg": None,
            "pitch_range_deg": None,
            "metric_class": METRIC_CLASS,
        }
    step = 1.0 / resample_hz
    sample_count = max(2, int(math.floor((common_end - common_start) / step)) + 1)
    times = np.linspace(common_start, common_end, sample_count)
    alignment_start = max(float(base["timestamp_s"][0]), float(candidate_arrays["timestamp_s"][0]))
    rotation, translation, _ = _initial_yaw_translation(baseline, candidate, alignment_start)
    base_pos = np.column_stack([_interp(base, key, times) for key in ("x_m", "y_m", "z_m")])
    candidate_pos = np.column_stack([_interp(candidate_arrays, key, times) for key in ("x_m", "y_m", "z_m")])
    candidate_aligned = (rotation @ candidate_pos.T).T + translation
    error_vec = candidate_aligned - base_pos
    errors = np.linalg.norm(error_vec, axis=1)
    z_errors = error_vec[:, 2]
    candidate_times_in_phase = candidate_arrays["timestamp_s"][(candidate_arrays["timestamp_s"] >= common_start) & (candidate_arrays["timestamp_s"] <= common_end)]
    gaps = np.diff(candidate_times_in_phase)
    roll = _interp(candidate_arrays, "roll_rad", times)
    pitch = _interp(candidate_arrays, "pitch_rad", times)
    return {
        "samples": int(sample_count),
        "coverage_ratio": float(min(1.0, (common_end - common_start) / phase_duration)),
        "max_sample_gap_s": float(np.max(gaps)) if len(gaps) else None,
        "relative_position_rmse_m": float(np.sqrt(np.mean(errors**2))),
        "relative_position_p95_m": float(np.percentile(errors, 95)),
        "relative_z_rmse_m": float(np.sqrt(np.mean(z_errors**2))),
        "z_change_m": float(candidate_aligned[-1, 2] - candidate_aligned[0, 2]),
        "roll_range_deg": float(math.degrees(float(np.max(roll) - np.min(roll)))),
        "pitch_range_deg": float(math.degrees(float(np.max(pitch) - np.min(pitch)))),
        "metric_class": METRIC_CLASS,
    }


def aggregate_resource_phase(
    aligned_resources: list[dict[str, Any]], phase: dict[str, Any]
) -> dict[str, Any]:
    start, end = float(phase["start_s"]), float(phase["end_s"])
    selected = [item for item in aligned_resources if start <= float(item["trajectory_time_s"]) <= end]
    if not selected:
        return {
            "resource_samples": 0,
            "cpu_median_percent": None,
            "cpu_mean_percent": None,
            "cpu_p95_percent": None,
            "cpu_peak_percent": None,
            "rss_start_mib": None,
            "rss_end_mib": None,
            "rss_growth_mib": None,
            "rss_peak_mib": None,
            "threads_p95": None,
            "threads_peak": None,
        }
    selected.sort(key=lambda item: float(item["trajectory_time_s"]))
    cpus = [float(item.get("cpu_percent") or 0.0) for item in selected]
    rss = [float(item.get("rss_bytes") or 0.0) / (1024 * 1024) for item in selected]
    threads = [float(item.get("threads") or 0.0) for item in selected]
    return {
        "resource_samples": len(selected),
        "cpu_median_percent": float(statistics.median(cpus)),
        "cpu_mean_percent": float(statistics.fmean(cpus)),
        "cpu_p95_percent": _percentile(cpus, 95),
        "cpu_peak_percent": max(cpus),
        "rss_start_mib": rss[0],
        "rss_end_mib": rss[-1],
        "rss_growth_mib": rss[-1] - rss[0],
        "rss_peak_mib": max(rss),
        "threads_p95": _percentile(threads, 95),
        "threads_peak": int(max(threads)),
    }


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _raw_directory(run: Path, algorithm: str, status: dict[str, Any]) -> Path:
    entry = (status.get("algorithms") or {}).get(algorithm) or {}
    result = entry.get("result") or {}
    output_dir = result.get("output_dir") or entry.get("output_dir")
    if output_dir:
        candidate = Path(output_dir)
        if candidate.exists():
            return candidate
    return run / "raw" / algorithm


def _health_index(run: Path) -> dict[str, dict[str, Any]]:
    comparison = _load_json(run / "metrics" / "full_comparison.json", {}) or {}
    return {
        item["algorithm"]: item
        for item in comparison.get("algorithms") or []
        if isinstance(item, dict) and item.get("algorithm")
    }


def _clock_anchors(path: Path) -> list[dict[str, Any]] | None:
    data = _load_json(path, None)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("anchors"), list):
        return data["anchors"]
    return None


def _markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Phase-aware LIO Benchmark",
        "",
        f"- Baseline: `{result['baseline']}`",
        f"- Metric class: `{result['metric_class']}`",
        f"- Time alignment: `{result['time_alignment_mode']}`",
        "- Interpretation: relative diagnostic comparison only; no independent ground truth, so this report is not ATE/RPE.",
        "",
        "## Phases",
        "",
        "| Phase | State | Start (s) | End (s) | Duration (s) | Return-near-start |",
        "|---|---|---:|---:|---:|---|",
    ]
    for phase in result["phases"]:
        lines.append(
            f"| {phase['id']} | {phase['state']} | {phase['start_s']:.3f} | {phase['end_s']:.3f} | {phase['duration_s']:.3f} | {phase['return_near_start']} |"
        )
    lines.extend(["", "## Algorithms", ""])
    for name, item in result["algorithms"].items():
        lines.extend(
            [
                f"### {name}",
                "",
                f"- Selection eligible: `{item['selection_eligible']}`",
                f"- Health flags: `{', '.join(item['health_flags']) or 'none'}`",
                f"- Resource alignment: `{item['time_alignment_mode']}`",
                "",
                "| Phase | Relative position RMSE (m) | Relative Z RMSE (m) | Z change (m) | CPU p95 (%) | RSS growth (MiB) |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for phase_id, values in item["phases"].items():
            trajectory = values["trajectory"]
            resource = values["resource"]
            def fmt(value: Any) -> str:
                return "" if value is None else f"{float(value):.3f}"
            lines.append(
                f"| {phase_id} | {fmt(trajectory.get('relative_position_rmse_m'))} | {fmt(trajectory.get('relative_z_rmse_m'))} | {fmt(trajectory.get('z_change_m'))} | {fmt(resource.get('cpu_p95_percent'))} | {fmt(resource.get('rss_growth_mib'))} |"
            )
    if result.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in result["warnings"])
    return "\n".join(lines) + "\n"


def run_phase_analysis(
    run: Path,
    *,
    baseline: str = "fast_livo2",
    phase_parameters: dict[str, float] | None = None,
) -> dict[str, Any]:
    run = Path(run).resolve()
    manifest = _load_json(run / "manifest.json", None)
    if not isinstance(manifest, dict):
        raise ValueError(f"run is missing manifest.json: {run}")
    trajectory_dir = run / "standardized" / "trajectories"
    baseline_path = trajectory_dir / f"{baseline}.csv"
    if not baseline_path.is_file():
        raise FileNotFoundError(f"missing baseline standardized trajectory: {baseline_path}")
    params = dict(DEFAULT_PHASE_PARAMETERS)
    if phase_parameters:
        params.update({key: float(value) for key, value in phase_parameters.items()})
    baseline_rows = load_trajectory_csv(baseline_path)
    _, phases = build_phases(baseline_rows, params)
    status = _load_json(run / "metadata" / "run_status.json", {}) or {}
    bag_analysis = _load_json(run / "metrics" / "bag_analysis.json", {}) or {}
    health = _health_index(run)
    lidar_topic = str((manifest.get("dataset") or {}).get("lidar_topic") or "")
    playback_rate = float(manifest.get("playback_rate") or 1.0)

    algorithms: dict[str, Any] = {}
    warnings: list[str] = []
    observed_modes: list[str] = []
    offset_evidence: dict[str, Any] = {}
    for path in sorted(trajectory_dir.glob("*.csv")):
        algorithm = path.stem
        candidate_rows = load_trajectory_csv(path)
        health_item = health.get(algorithm, {})
        health_flags = list(health_item.get("health_flags") or [])
        status_value = health_item.get("status")
        selection_eligible = status_value in {None, "SUCCESS"} and not health_flags
        raw = _raw_directory(run, algorithm, status)
        resource = _load_json(raw / "resource_monitor.json", {}) or {}
        anchors = _clock_anchors(raw / "clock_anchors.json")
        mode, aligned_resources, evidence, algorithm_warnings = align_resource_samples(
            resource,
            algorithm,
            status,
            bag_analysis,
            lidar_topic,
            anchors,
            playback_rate=playback_rate,
        )
        warnings.extend(algorithm_warnings)
        if aligned_resources:
            observed_modes.append(mode)
        if not offset_evidence and evidence.get("clock_to_trajectory_offset"):
            offset_evidence = evidence["clock_to_trajectory_offset"]
        phase_results: dict[str, Any] = {}
        outside = (
            sum(
                float(item["trajectory_time_s"]) < float(phases[0]["start_s"])
                or float(item["trajectory_time_s"]) > float(phases[-1]["end_s"])
                for item in aligned_resources
            )
            if phases
            else 0
        )
        for phase in phases:
            trajectory_metrics = compute_phase_trajectory_metrics(
                baseline_rows, candidate_rows, phase, resample_hz=params["resample_hz"]
            )
            resource_metrics = aggregate_resource_phase(aligned_resources, phase)
            resource_metrics["availability"] = "unavailable" if mode == "trajectory-only" else "available"
            resource_metrics["time_alignment_mode"] = mode
            phase_results[phase["id"]] = {"trajectory": trajectory_metrics, "resource": resource_metrics}
        algorithms[algorithm] = {
            "status": status_value,
            "health_flags": health_flags,
            "selection_eligible": selection_eligible,
            "metric_class": METRIC_CLASS,
            "time_alignment_mode": mode,
            "time_alignment_evidence": evidence,
            "outside_phase_window_samples": int(outside),
            "phases": phase_results,
        }

    if any(mode == "approximate/lifecycle-aligned" for mode in observed_modes):
        top_mode = "approximate/lifecycle-aligned"
    elif any(mode == "strict/clock-anchored" for mode in observed_modes):
        top_mode = "strict/clock-anchored"
    else:
        top_mode = "trajectory-only"
    result = {
        "schema_version": 1,
        "baseline": baseline,
        "metric_class": METRIC_CLASS,
        "time_alignment_mode": top_mode,
        "time_alignment_evidence": {
            "per_algorithm": {name: value["time_alignment_evidence"] for name, value in algorithms.items()}
        },
        "clock_to_trajectory_offset": offset_evidence,
        "phase_parameters": params,
        "phases": phases,
        "algorithms": algorithms,
        "warnings": sorted(set(warnings)),
    }
    metrics_path = run / "metrics" / "phase_analysis.json"
    report_path = run / "reports" / "phase_analysis.md"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(_markdown_report(result), encoding="utf-8")
    return result


def _parse_parameter(value: str) -> tuple[str, float]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("phase parameter must use key=value")
    key, raw = value.split("=", 1)
    if key not in DEFAULT_PHASE_PARAMETERS:
        raise argparse.ArgumentTypeError(f"unknown phase parameter: {key}")
    try:
        return key, float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid numeric phase parameter: {value}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--phase-param", action="append", type=_parse_parameter, default=[])
    args = parser.parse_args()
    parameters = dict(args.phase_param)
    result = run_phase_analysis(args.run, baseline=args.baseline, phase_parameters=parameters)
    print(
        json.dumps(
            {
                "output": str((args.run / "metrics/phase_analysis.json").resolve()),
                "time_alignment_mode": result["time_alignment_mode"],
                "phases": len(result["phases"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
