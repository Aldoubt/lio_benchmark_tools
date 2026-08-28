#!/usr/bin/env python3
"""Detect timestamped trajectory discontinuities from standardized CSVs.

This stage is ROS-free and does not replay the bag. Events are diagnostic only:
a pose-graph correction can be a legitimate discontinuity, so these events do
not automatically modify lifecycle/trajectory health.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from plot_comparison_dashboard import LABELS, discover_algorithms, load_trajectory


POSITION_JUMP_FLOOR_M = 0.5
YAW_JUMP_FLOOR_DEG = 10.0
MAD_SCALE = 1.4826
MAD_MULTIPLIER = 10.0
METRIC_CLASS = "diagnostic/non-ground-truth"


def robust_jump_threshold(values: np.ndarray, floor: float) -> float:
    """Return max(floor, median + 10 * scaled MAD) for finite samples."""
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return float(floor)
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    return float(max(floor, median + MAD_MULTIPLIER * MAD_SCALE * mad))


def step_series(
    trajectory: dict[str, np.ndarray],
    origin_timestamp_s: float,
) -> dict[str, np.ndarray]:
    timestamps = np.asarray(trajectory["timestamp_s"], dtype=np.float64)
    positions = np.asarray(trajectory["positions"], dtype=np.float64)
    yaw = np.unwrap(np.asarray(trajectory["yaw_rad"], dtype=np.float64))
    if len(timestamps) < 2 or len(positions) != len(timestamps) or len(yaw) != len(timestamps):
        raise ValueError("trajectory must contain at least two aligned timestamp/pose samples")

    dt = np.diff(timestamps)
    position_step = np.linalg.norm(np.diff(positions, axis=0), axis=1)
    yaw_step_deg = np.abs(np.diff(yaw)) * 180.0 / np.pi
    current_positions = positions[1:]
    current_timestamps = timestamps[1:]
    valid = (
        np.isfinite(dt)
        & (dt > 0.0)
        & np.isfinite(position_step)
        & np.isfinite(yaw_step_deg)
        & np.isfinite(current_positions).all(axis=1)
    )
    dt = dt[valid]
    position_step = position_step[valid]
    yaw_step_deg = yaw_step_deg[valid]
    current_positions = current_positions[valid]
    current_timestamps = current_timestamps[valid]
    return {
        "timestamp_s": current_timestamps,
        "relative_time_s": current_timestamps - float(origin_timestamp_s),
        "dt_s": dt,
        "position_step_m": position_step,
        "yaw_step_deg": yaw_step_deg,
        "speed_mps": position_step / dt,
        "yaw_rate_deg_s": yaw_step_deg / dt,
        "x_m": current_positions[:, 0],
        "y_m": current_positions[:, 1],
        "z_m": current_positions[:, 2],
    }


def summarize_discontinuities(
    algorithm: str,
    trajectory: dict[str, np.ndarray],
    origin_timestamp_s: float,
    *,
    position_floor_m: float = POSITION_JUMP_FLOOR_M,
    yaw_floor_deg: float = YAW_JUMP_FLOOR_DEG,
) -> dict[str, Any]:
    series = step_series(trajectory, origin_timestamp_s)
    position_threshold = robust_jump_threshold(series["position_step_m"], position_floor_m)
    yaw_threshold = robust_jump_threshold(series["yaw_step_deg"], yaw_floor_deg)
    position_mask = series["position_step_m"] > position_threshold
    yaw_mask = series["yaw_step_deg"] > yaw_threshold

    events: list[dict[str, Any]] = []
    for index in range(len(series["timestamp_s"])):
        common = {
            "algorithm": algorithm,
            "timestamp_s": float(series["timestamp_s"][index]),
            "relative_time_s": float(series["relative_time_s"][index]),
            "dt_s": float(series["dt_s"][index]),
            "position_step_m": float(series["position_step_m"][index]),
            "yaw_step_deg": float(series["yaw_step_deg"][index]),
            "speed_mps": float(series["speed_mps"][index]),
            "yaw_rate_deg_s": float(series["yaw_rate_deg_s"][index]),
            "x_m": float(series["x_m"][index]),
            "y_m": float(series["y_m"][index]),
            "z_m": float(series["z_m"][index]),
        }
        if bool(position_mask[index]):
            events.append(
                {
                    **common,
                    "type": "position_jump",
                    "threshold": float(position_threshold),
                }
            )
        if bool(yaw_mask[index]):
            events.append(
                {
                    **common,
                    "type": "yaw_jump",
                    "threshold": float(yaw_threshold),
                }
            )
    events.sort(key=lambda item: (item["timestamp_s"], item["type"]))

    return {
        "algorithm": algorithm,
        "metric_class": METRIC_CLASS,
        "samples": int(len(series["timestamp_s"])),
        "position_jump_threshold_m": float(position_threshold),
        "yaw_jump_threshold_deg": float(yaw_threshold),
        "position_jump_count": int(np.count_nonzero(position_mask)),
        "yaw_jump_count": int(np.count_nonzero(yaw_mask)),
        "event_count": int(len(events)),
        "max_position_step_m": (
            float(np.max(series["position_step_m"])) if len(series["position_step_m"]) else None
        ),
        "p99_position_step_m": (
            float(np.percentile(series["position_step_m"], 99)) if len(series["position_step_m"]) else None
        ),
        "max_yaw_step_deg": (
            float(np.max(series["yaw_step_deg"])) if len(series["yaw_step_deg"]) else None
        ),
        "p99_yaw_step_deg": (
            float(np.percentile(series["yaw_step_deg"], 99)) if len(series["yaw_step_deg"]) else None
        ),
        "events": events,
    }


def _write_series_csv(
    path: Path,
    series: dict[str, np.ndarray],
    position_threshold_m: float,
    yaw_threshold_deg: float,
) -> None:
    fields = [
        "timestamp_s",
        "relative_time_s",
        "dt_s",
        "position_step_m",
        "yaw_step_deg",
        "speed_mps",
        "yaw_rate_deg_s",
        "x_m",
        "y_m",
        "z_m",
        "position_jump",
        "yaw_jump",
        "anomaly_types",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index in range(len(series["timestamp_s"])):
            position_jump = bool(series["position_step_m"][index] > position_threshold_m)
            yaw_jump = bool(series["yaw_step_deg"][index] > yaw_threshold_deg)
            anomaly_types = []
            if position_jump:
                anomaly_types.append("position_jump")
            if yaw_jump:
                anomaly_types.append("yaw_jump")
            writer.writerow(
                {
                    key: float(series[key][index])
                    for key in fields[:10]
                }
                | {
                    "position_jump": int(position_jump),
                    "yaw_jump": int(yaw_jump),
                    "anomaly_types": ";".join(anomaly_types),
                }
            )


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Trajectory discontinuity diagnostics",
        "",
        f"- Baseline time origin: `{payload['baseline']}` first standardized timestamp.",
        f"- Metric class: `{METRIC_CLASS}`",
        "- Events are diagnostic only; a loop-closure correction can be a legitimate pose jump.",
        "- Per-step CSVs retain sensor timestamps for later point-cloud/resource highlighting.",
        "",
        "| Algorithm | Steps | Position jumps | Yaw jumps | Max Δpos (m) | P99 Δpos (m) | Max Δyaw (deg) | P99 Δyaw (deg) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for algorithm in payload["algorithm_order"]:
        item = payload["algorithms"][algorithm]
        lines.append(
            f"| {LABELS.get(algorithm, algorithm)} | {item['samples']} | "
            f"{item['position_jump_count']} | {item['yaw_jump_count']} | "
            f"{item['max_position_step_m'] or 0.0:.3f} | "
            f"{item['p99_position_step_m'] or 0.0:.3f} | "
            f"{item['max_yaw_step_deg'] or 0.0:.3f} | "
            f"{item['p99_yaw_step_deg'] or 0.0:.3f} |"
        )
    lines.extend(["", "## Top timestamped events", ""])
    events = sorted(
        payload["events"],
        key=lambda item: max(
            item["position_step_m"] / max(item.get("threshold", 1e-9), 1e-9)
            if item["type"] == "position_jump" else 0.0,
            item["yaw_step_deg"] / max(item.get("threshold", 1e-9), 1e-9)
            if item["type"] == "yaw_jump" else 0.0,
        ),
        reverse=True,
    )[:30]
    lines.append("| Algorithm | Type | Relative time (s) | Sensor timestamp | Δpos (m) | Δyaw (deg) | XYZ (m) |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for item in events:
        lines.append(
            f"| {LABELS.get(item['algorithm'], item['algorithm'])} | {item['type']} | "
            f"{item['relative_time_s']:.3f} | {item['timestamp_s']:.6f} | "
            f"{item['position_step_m']:.3f} | {item['yaw_step_deg']:.3f} | "
            f"({item['x_m']:.2f}, {item['y_m']:.2f}, {item['z_m']:.2f}) |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plot_timeline(
    path: Path,
    series_by_algorithm: dict[str, dict[str, np.ndarray]],
    summaries: dict[str, dict[str, Any]],
    *,
    value_key: str,
    event_type: str,
    ylabel: str,
    title: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(14, 7), constrained_layout=True)
    for algorithm, series in series_by_algorithm.items():
        values = np.maximum(np.asarray(series[value_key], dtype=np.float64), 1e-6)
        axis.plot(
            series["relative_time_s"],
            values,
            linewidth=0.8,
            alpha=0.75,
            label=LABELS.get(algorithm, algorithm),
        )
        events = [
            item for item in summaries[algorithm]["events"] if item["type"] == event_type
        ]
        if events:
            axis.scatter(
                [item["relative_time_s"] for item in events],
                [max(float(item[value_key]), 1e-6) for item in events],
                s=18,
                marker="x",
            )
    axis.set_yscale("log")
    axis.set_xlabel("Time relative to baseline start (s)")
    axis.set_ylabel(ylabel)
    axis.set_title(title)
    axis.grid(alpha=0.2)
    axis.legend(fontsize=8, ncol=2)
    figure.savefig(path, dpi=180)
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--position-floor-m", type=float, default=POSITION_JUMP_FLOOR_M)
    parser.add_argument("--yaw-floor-deg", type=float, default=YAW_JUMP_FLOOR_DEG)
    args = parser.parse_args()
    if args.position_floor_m <= 0 or args.yaw_floor_deg <= 0:
        raise ValueError("jump floors must be > 0")

    run = args.run.resolve()
    algorithms = discover_algorithms(run)
    if args.baseline not in algorithms:
        raise ValueError(f"baseline standardized trajectory is unavailable: {args.baseline}")
    trajectory_dir = run / "standardized" / "trajectories"
    trajectories = {
        algorithm: load_trajectory(trajectory_dir / f"{algorithm}.csv")
        for algorithm in algorithms
    }
    origin_timestamp_s = float(trajectories[args.baseline]["timestamp_s"][0])

    series_by_algorithm: dict[str, dict[str, np.ndarray]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    csv_dir = run / "metrics" / "trajectory_discontinuity"
    csv_dir.mkdir(parents=True, exist_ok=True)
    for algorithm in algorithms:
        series = step_series(trajectories[algorithm], origin_timestamp_s)
        summary = summarize_discontinuities(
            algorithm,
            trajectories[algorithm],
            origin_timestamp_s,
            position_floor_m=args.position_floor_m,
            yaw_floor_deg=args.yaw_floor_deg,
        )
        series_by_algorithm[algorithm] = series
        summaries[algorithm] = summary
        events.extend(summary["events"])
        _write_series_csv(
            csv_dir / f"{algorithm}.csv",
            series,
            summary["position_jump_threshold_m"],
            summary["yaw_jump_threshold_deg"],
        )

    events.sort(key=lambda item: (item["timestamp_s"], item["algorithm"], item["type"]))
    payload = {
        "schema_version": 1,
        "metric_class": METRIC_CLASS,
        "baseline": args.baseline,
        "origin_timestamp_s": origin_timestamp_s,
        "threshold_policy": {
            "median_plus_scaled_mad_multiplier": MAD_MULTIPLIER,
            "mad_scale": MAD_SCALE,
            "position_floor_m": args.position_floor_m,
            "yaw_floor_deg": args.yaw_floor_deg,
        },
        "algorithm_order": algorithms,
        "algorithms": summaries,
        "events": events,
    }
    metrics_path = run / "metrics" / "trajectory_discontinuity.json"
    metrics_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    reports = run / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    _write_markdown(reports / "trajectory_discontinuity.md", payload)

    figures = run / "figures" / "trajectory_discontinuity"
    figures.mkdir(parents=True, exist_ok=True)
    _plot_timeline(
        figures / "position_step.png",
        series_by_algorithm,
        summaries,
        value_key="position_step_m",
        event_type="position_jump",
        ylabel="Position step Δp per sample (m, log scale)",
        title="Trajectory position-step discontinuity timeline",
    )
    _plot_timeline(
        figures / "yaw_step.png",
        series_by_algorithm,
        summaries,
        value_key="yaw_step_deg",
        event_type="yaw_jump",
        ylabel="Yaw step Δyaw per sample (deg, log scale)",
        title="Trajectory yaw-step discontinuity timeline",
    )

    print(
        json.dumps(
            {
                "output": str(metrics_path),
                "algorithms": len(algorithms),
                "events": len(events),
                "origin_timestamp_s": origin_timestamp_s,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
