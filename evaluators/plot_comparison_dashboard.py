#!/usr/bin/env python3
"""Generate lightweight, paper-friendly trajectory and diagnostic comparison figures.

This module intentionally consumes only standardized CSV trajectories and the
existing full_comparison.json. It has no ROS dependency, so visual inspection
can be repeated without replaying a bag. Alignment is relative to a selected
baseline and is diagnostic only when independent ground truth is unavailable.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

LABELS = {
    "kiss_icp": "KISS-ICP",
    "mola_lo": "MOLA-LO",
    "mola_lio": "MOLA-LIO",
    "fast_livo2": "FAST-LIVO2",
    "point_lio": "Point-LIO",
    "dlio": "DLIO",
    "glim_odometry": "GLIM odometry",
    "glim_full_slam": "GLIM full SLAM",
    "lio_sam_no_loop": "LIO-SAM no-loop",
    "lio_sam_loop": "LIO-SAM loop",
}


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_trajectory(path: Path) -> dict[str, np.ndarray]:
    with path.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) < 2:
        raise ValueError(f"trajectory has fewer than two rows: {path}")
    keys = ("timestamp_s", "x_m", "y_m", "z_m")
    data = {key: np.asarray([float(row[key]) for row in rows], dtype=np.float64) for key in keys}
    yaw = np.asarray([float(row.get("yaw_rad") or 0.0) for row in rows], dtype=np.float64)
    order = np.argsort(data["timestamp_s"], kind="stable")
    data = {key: value[order] for key, value in data.items()}
    yaw = yaw[order]
    _, unique = np.unique(data["timestamp_s"], return_index=True)
    unique = np.sort(unique)
    data = {key: value[unique] for key, value in data.items()}
    yaw = yaw[unique]
    data["positions"] = np.column_stack((data["x_m"], data["y_m"], data["z_m"]))
    data["yaw_rad"] = np.unwrap(yaw)
    return data


def discover_algorithms(run: Path) -> list[str]:
    trajectory_dir = run / "standardized" / "trajectories"
    available = {path.stem for path in trajectory_dir.glob("*.csv")}
    comparison = load_json(run / "metrics" / "full_comparison.json", {}) or {}
    ordered = [
        item.get("algorithm")
        for item in comparison.get("algorithms", [])
        if isinstance(item, dict) and item.get("algorithm") in available
    ]
    if ordered:
        return ordered
    return sorted(available)


def _interp_positions(trajectory: dict[str, np.ndarray], times: np.ndarray) -> np.ndarray:
    return np.column_stack([
        np.interp(times, trajectory["timestamp_s"], trajectory["positions"][:, axis])
        for axis in range(3)
    ])


def _interp_yaw(trajectory: dict[str, np.ndarray], times: np.ndarray) -> np.ndarray:
    return np.interp(times, trajectory["timestamp_s"], trajectory["yaw_rad"])


def align_candidate_to_baseline(
    baseline: dict[str, np.ndarray],
    candidate: dict[str, np.ndarray],
) -> tuple[np.ndarray, dict[str, Any]]:
    start = max(float(baseline["timestamp_s"][0]), float(candidate["timestamp_s"][0]))
    end = min(float(baseline["timestamp_s"][-1]), float(candidate["timestamp_s"][-1]))
    if end <= start:
        raise ValueError("baseline and candidate have no common time window")

    sample_count = min(1000, max(2, int(math.ceil((end - start) * 10.0)) + 1))
    times = np.linspace(start, end, sample_count)
    base_common = _interp_positions(baseline, times)
    candidate_common = _interp_positions(candidate, times)
    base_yaw = float(_interp_yaw(baseline, np.asarray([start]))[0])
    candidate_yaw = float(_interp_yaw(candidate, np.asarray([start]))[0])
    yaw_delta = base_yaw - candidate_yaw
    c, s = math.cos(yaw_delta), math.sin(yaw_delta)
    rotation = np.asarray([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    candidate_start = _interp_positions(candidate, np.asarray([start]))[0]
    baseline_start = _interp_positions(baseline, np.asarray([start]))[0]
    translation = baseline_start - rotation @ candidate_start

    aligned = (rotation @ candidate["positions"].T).T + translation
    aligned_common = (rotation @ candidate_common.T).T + translation
    errors = np.linalg.norm(aligned_common - base_common, axis=1)
    metadata = {
        "method": "initial_yaw_translation",
        "common_start_s": start,
        "common_end_s": end,
        "common_duration_s": end - start,
        "samples": int(sample_count),
        "yaw_delta_rad": yaw_delta,
        "translation_xyz_m": translation.tolist(),
        "relative_rmse_m": float(np.sqrt(np.mean(errors ** 2))),
        "relative_p95_m": float(np.percentile(errors, 95)),
        "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
    }
    return aligned, metadata


def build_metric_summary(comparison: dict[str, Any], algorithms: list[str]) -> list[dict[str, Any]]:
    indexed = {
        item.get("algorithm"): item
        for item in comparison.get("algorithms", [])
        if isinstance(item, dict) and item.get("algorithm")
    }
    rows: list[dict[str, Any]] = []
    for algorithm in algorithms:
        item = indexed.get(algorithm, {})
        trajectory = item.get("trajectory") or {}
        resource = item.get("resource_monitor") or item.get("resource") or {}
        rows.append({
            "algorithm": algorithm,
            "status": item.get("status"),
            "health_flags": list(item.get("health_flags") or []),
            "path_length_m": trajectory.get("path_length_m"),
            "z_range_m": trajectory.get("z_range_m"),
            "mean_cpu_percent": resource.get("mean_cpu_percent"),
            "peak_rss_mib": resource.get("peak_rss_mib"),
        })
    return rows


def _metric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    result = []
    for row in rows:
        value = row.get(key)
        result.append(float(value) if value is not None else 0.0)
    return result


def _save_figures(
    output: Path,
    algorithms: list[str],
    trajectories: dict[str, dict[str, np.ndarray]],
    aligned: dict[str, np.ndarray],
    metric_rows: list[dict[str, Any]],
    baseline: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = plt.get_cmap("tab20")
    color_map = {algorithm: colors(index % 20) for index, algorithm in enumerate(algorithms)}

    fig, axis = plt.subplots(figsize=(11, 8), constrained_layout=True)
    origin = aligned[baseline][0]
    for algorithm in algorithms:
        positions = aligned[algorithm] - origin
        axis.plot(positions[:, 0], positions[:, 1], linewidth=1.3, label=LABELS.get(algorithm, algorithm), color=color_map[algorithm])
        axis.scatter([positions[0, 0]], [positions[0, 1]], s=14, color=color_map[algorithm])
    axis.set_title(f"Trajectory XY overlay aligned to {LABELS.get(baseline, baseline)}")
    axis.set_xlabel("X (m)")
    axis.set_ylabel("Y (m)")
    axis.set_aspect("equal", adjustable="box")
    axis.grid(alpha=0.25)
    axis.legend(fontsize=8, ncol=2)
    fig.savefig(output / "trajectory_xy_overlay.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(12, 7), constrained_layout=True)
    for algorithm in algorithms:
        trajectory = trajectories[algorithm]
        times = trajectory["timestamp_s"] - trajectory["timestamp_s"][0]
        z = aligned[algorithm][:, 2] - aligned[algorithm][0, 2]
        axis.plot(times, z, linewidth=1.2, label=LABELS.get(algorithm, algorithm), color=color_map[algorithm])
    axis.set_title("Relative Z change over trajectory time")
    axis.set_xlabel("Elapsed trajectory time (s)")
    axis.set_ylabel("Z - Z0 (m)")
    axis.grid(alpha=0.25)
    axis.legend(fontsize=8, ncol=2)
    fig.savefig(output / "trajectory_z_drift.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    labels = [LABELS.get(row["algorithm"], row["algorithm"]) for row in metric_rows]
    positions = np.arange(len(metric_rows))
    fig, axes = plt.subplots(2, 2, figsize=(16, 10), constrained_layout=True)
    metrics = [
        ("z_range_m", "Diagnostic Z range", "m"),
        ("path_length_m", "Estimated path length", "m"),
        ("mean_cpu_percent", "Mean process-tree CPU", "% (100%=1 logical core)"),
        ("peak_rss_mib", "Peak process-tree RSS", "MiB"),
    ]
    for axis, (key, title, unit) in zip(axes.flat, metrics):
        values = _metric_values(metric_rows, key)
        axis.bar(positions, values)
        axis.set_title(title)
        axis.set_ylabel(unit)
        axis.set_xticks(positions)
        axis.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        axis.grid(axis="y", alpha=0.25)
        positives = [value for value in values if value > 0]
        if key == "path_length_m" and positives and max(positives) / min(positives) > 20:
            axis.set_yscale("log")
    fig.suptitle("LIO diagnostic/resource comparison (no absolute accuracy claim without ground truth)")
    fig.savefig(output / "diagnostic_dashboard.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render lightweight LIO comparison figures from standardized outputs")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--algorithms", help="Comma-separated algorithm keys; default follows full_comparison.json order")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    run = args.run.resolve()
    algorithms = discover_algorithms(run)
    if args.algorithms:
        requested = [item.strip() for item in args.algorithms.split(",") if item.strip()]
        algorithms = [algorithm for algorithm in requested if algorithm in algorithms]
    if len(algorithms) < 1:
        raise ValueError(f"no standardized trajectories found in {run / 'standardized' / 'trajectories'}")
    baseline = args.baseline if args.baseline in algorithms else algorithms[0]
    trajectories = {
        algorithm: load_trajectory(run / "standardized" / "trajectories" / f"{algorithm}.csv")
        for algorithm in algorithms
    }
    aligned: dict[str, np.ndarray] = {baseline: trajectories[baseline]["positions"].copy()}
    alignment: dict[str, Any] = {
        baseline: {
            "method": "identity",
            "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
        }
    }
    for algorithm in algorithms:
        if algorithm == baseline:
            continue
        aligned[algorithm], alignment[algorithm] = align_candidate_to_baseline(trajectories[baseline], trajectories[algorithm])

    comparison = load_json(run / "metrics" / "full_comparison.json", {}) or {}
    metric_rows = build_metric_summary(comparison, algorithms)
    output = (args.output_dir or run / "figures" / "comparison_dashboard").resolve()
    output.mkdir(parents=True, exist_ok=True)
    _save_figures(output, algorithms, trajectories, aligned, metric_rows, baseline)

    metadata = {
        "schema_version": 1,
        "baseline": baseline,
        "algorithms": algorithms,
        "metric_class": "diagnostic/relative-to-baseline/non-ground-truth",
        "alignment": alignment,
        "metrics": metric_rows,
        "figures": {
            "trajectory_xy_overlay": str(output / "trajectory_xy_overlay.png"),
            "trajectory_z_drift": str(output / "trajectory_z_drift.png"),
            "diagnostic_dashboard": str(output / "diagnostic_dashboard.png"),
        },
        "note": "XY overlays use initial yaw + translation alignment to the selected baseline. Without independent ground truth these are diagnostic visualizations, not absolute accuracy rankings.",
    }
    (output / "comparison_visualization.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "README.md").write_text(
        "# Comparison dashboard\n\n"
        "Lightweight figures generated from standardized trajectories and full_comparison.json. "
        "No rosbag replay is needed. XY trajectories are aligned by initial yaw and translation to the selected baseline. "
        "Without independent ground truth, all trajectory differences remain diagnostic rather than absolute accuracy metrics.\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "baseline": baseline, "algorithms": algorithms}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
