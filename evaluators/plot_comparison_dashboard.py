#!/usr/bin/env python3
"""Generate lightweight, paper-friendly LIO comparison figures.

Consumes standardized CSV trajectories plus metrics/full_comparison.json.
No ROS dependency is required. Without independent ground truth, all trajectory
differences remain diagnostic rather than absolute accuracy metrics.
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
    data = {
        key: np.asarray([float(row[key]) for row in rows], dtype=np.float64)
        for key in keys
    }
    yaw = np.asarray(
        [float(row.get("yaw_rad") or 0.0) for row in rows], dtype=np.float64
    )
    order = np.argsort(data["timestamp_s"], kind="stable")
    data = {key: value[order] for key, value in data.items()}
    yaw = yaw[order]
    _, unique = np.unique(data["timestamp_s"], return_index=True)
    unique = np.sort(unique)
    data = {key: value[unique] for key, value in data.items()}
    yaw = yaw[unique]
    data["positions"] = np.column_stack(
        (data["x_m"], data["y_m"], data["z_m"])
    )
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
    return ordered if ordered else sorted(available)


def _interp_positions(
    trajectory: dict[str, np.ndarray], times: np.ndarray
) -> np.ndarray:
    return np.column_stack(
        [
            np.interp(
                times,
                trajectory["timestamp_s"],
                trajectory["positions"][:, axis],
            )
            for axis in range(3)
        ]
    )


def _interp_yaw(
    trajectory: dict[str, np.ndarray], times: np.ndarray
) -> np.ndarray:
    return np.interp(times, trajectory["timestamp_s"], trajectory["yaw_rad"])


def align_candidate_to_baseline(
    baseline: dict[str, np.ndarray],
    candidate: dict[str, np.ndarray],
) -> tuple[np.ndarray, dict[str, Any]]:
    start = max(
        float(baseline["timestamp_s"][0]), float(candidate["timestamp_s"][0])
    )
    end = min(
        float(baseline["timestamp_s"][-1]), float(candidate["timestamp_s"][-1])
    )
    if end <= start:
        raise ValueError("baseline and candidate have no common time window")

    sample_count = min(
        1000, max(2, int(math.ceil((end - start) * 10.0)) + 1)
    )
    times = np.linspace(start, end, sample_count)
    base_common = _interp_positions(baseline, times)
    candidate_common = _interp_positions(candidate, times)
    base_yaw = float(_interp_yaw(baseline, np.asarray([start]))[0])
    candidate_yaw = float(_interp_yaw(candidate, np.asarray([start]))[0])
    yaw_delta = base_yaw - candidate_yaw
    c, s = math.cos(yaw_delta), math.sin(yaw_delta)
    rotation = np.asarray(
        [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64
    )
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
        "relative_rmse_m": float(np.sqrt(np.mean(errors**2))),
        "relative_p95_m": float(np.percentile(errors, 95)),
        "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
    }
    return aligned, metadata


def build_metric_summary(
    comparison: dict[str, Any], algorithms: list[str]
) -> list[dict[str, Any]]:
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
        rows.append(
            {
                "algorithm": algorithm,
                "status": item.get("status"),
                "health_flags": list(item.get("health_flags") or []),
                "path_length_m": trajectory.get("path_length_m"),
                "z_range_m": trajectory.get("z_range_m"),
                "mean_cpu_percent": resource.get("mean_cpu_percent"),
                "peak_rss_mib": resource.get("peak_rss_mib"),
            }
        )
    return rows


def health_valid(row: dict[str, Any]) -> bool:
    """A lifecycle SUCCESS is usable only when trajectory health has no flags."""
    return row.get("status") == "SUCCESS" and not list(row.get("health_flags") or [])


def choose_stable_algorithms(
    algorithms: list[str],
    metric_rows: list[dict[str, Any]],
    baseline: str,
) -> tuple[list[str], dict[str, list[str]]]:
    indexed = {row["algorithm"]: row for row in metric_rows}
    stable: list[str] = []
    excluded: dict[str, list[str]] = {}
    for algorithm in algorithms:
        row = indexed.get(algorithm, {})
        if algorithm == baseline or health_valid(row):
            stable.append(algorithm)
            continue
        reasons = list(row.get("health_flags") or [])
        if row.get("status") != "SUCCESS":
            reasons = [f"status:{row.get('status') or 'UNKNOWN'}", *reasons]
        excluded[algorithm] = reasons or ["health_not_valid"]
    return stable, excluded


def build_alignment_summary(
    alignment: dict[str, dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    algorithms: list[str],
    baseline: str,
) -> list[dict[str, Any]]:
    indexed = {row["algorithm"]: row for row in metric_rows}
    result = []
    for algorithm in algorithms:
        info = alignment.get(algorithm, {})
        metric = indexed.get(algorithm, {})
        result.append(
            {
                "algorithm": algorithm,
                "status": metric.get("status"),
                "health_flags": list(metric.get("health_flags") or []),
                "relative_rmse_m": (
                    0.0 if algorithm == baseline else info.get("relative_rmse_m")
                ),
                "relative_p95_m": (
                    0.0 if algorithm == baseline else info.get("relative_p95_m")
                ),
            }
        )
    return result


def _metric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    result = []
    for row in rows:
        value = row.get(key)
        result.append(float(value) if value is not None else 0.0)
    return result


def _label(algorithm: str, invalid: bool = False) -> str:
    label = LABELS.get(algorithm, algorithm)
    return f"{label} [health-fail]" if invalid else label


def _plot_xy(
    path: Path,
    algorithms: list[str],
    aligned: dict[str, np.ndarray],
    baseline: str,
    color_map: dict[str, Any],
    title_suffix: str,
) -> None:
    import matplotlib.pyplot as plt

    fig, axis = plt.subplots(figsize=(11, 8), constrained_layout=True)
    origin = aligned[baseline][0]
    for algorithm in algorithms:
        positions = aligned[algorithm] - origin
        axis.plot(
            positions[:, 0],
            positions[:, 1],
            linewidth=1.3,
            label=LABELS.get(algorithm, algorithm),
            color=color_map[algorithm],
        )
        axis.scatter(
            [positions[0, 0]],
            [positions[0, 1]],
            s=14,
            color=color_map[algorithm],
        )
    axis.set_title(
        f"Trajectory XY overlay aligned to {LABELS.get(baseline, baseline)}"
        f" — {title_suffix}"
    )
    axis.set_xlabel("X (m)")
    axis.set_ylabel("Y (m)")
    axis.set_aspect("equal", adjustable="box")
    axis.grid(alpha=0.25)
    axis.legend(fontsize=8, ncol=2)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_z(
    path: Path,
    algorithms: list[str],
    trajectories: dict[str, dict[str, np.ndarray]],
    aligned: dict[str, np.ndarray],
    color_map: dict[str, Any],
    title_suffix: str,
) -> None:
    import matplotlib.pyplot as plt

    fig, axis = plt.subplots(figsize=(12, 7), constrained_layout=True)
    for algorithm in algorithms:
        trajectory = trajectories[algorithm]
        times = trajectory["timestamp_s"] - trajectory["timestamp_s"][0]
        z = aligned[algorithm][:, 2] - aligned[algorithm][0, 2]
        axis.plot(
            times,
            z,
            linewidth=1.2,
            label=LABELS.get(algorithm, algorithm),
            color=color_map[algorithm],
        )
    axis.set_title(f"Relative Z change over trajectory time — {title_suffix}")
    axis.set_xlabel("Elapsed trajectory time (s)")
    axis.set_ylabel("Z - Z0 (m)")
    axis.grid(alpha=0.25)
    axis.legend(fontsize=8, ncol=2)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_dashboard(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    title_suffix: str,
    mark_invalid: bool,
) -> None:
    import matplotlib.pyplot as plt

    labels = [
        _label(row["algorithm"], mark_invalid and not health_valid(row))
        for row in rows
    ]
    positions = np.arange(len(rows))
    fig, axes = plt.subplots(2, 2, figsize=(16, 10), constrained_layout=True)
    metrics = [
        ("z_range_m", "Diagnostic Z range", "m"),
        ("path_length_m", "Estimated path length", "m"),
        (
            "mean_cpu_percent",
            "Mean process-tree CPU",
            "% (100%=1 logical core)",
        ),
        ("peak_rss_mib", "Peak process-tree RSS", "MiB"),
    ]
    for axis, (key, title, unit) in zip(axes.flat, metrics):
        values = _metric_values(rows, key)
        axis.bar(positions, values)
        axis.set_title(title)
        axis.set_ylabel(unit)
        axis.set_xticks(positions)
        axis.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        axis.grid(axis="y", alpha=0.25)
        positives = [value for value in values if value > 0]
        if (
            key in {"path_length_m", "z_range_m"}
            and positives
            and max(positives) / min(positives) > 20
        ):
            axis.set_yscale("log")
    fig.suptitle(
        "LIO diagnostic/resource comparison "
        "(no absolute accuracy claim without ground truth)"
        f" — {title_suffix}"
    )
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_relative_baseline(
    path: Path,
    rows: list[dict[str, Any]],
    baseline: str,
) -> None:
    import matplotlib.pyplot as plt

    labels = [LABELS.get(row["algorithm"], row["algorithm"]) for row in rows]
    positions = np.arange(len(rows))
    width = 0.38
    rmse = [float(row.get("relative_rmse_m") or 0.0) for row in rows]
    p95 = [float(row.get("relative_p95_m") or 0.0) for row in rows]

    fig, axis = plt.subplots(figsize=(12, 7), constrained_layout=True)
    axis.bar(positions - width / 2, rmse, width=width, label="Relative RMSE")
    axis.bar(positions + width / 2, p95, width=width, label="Relative P95")
    axis.set_title(
        f"Relative trajectory difference to {LABELS.get(baseline, baseline)}"
        " — health-valid trajectories"
    )
    axis.set_ylabel("m (relative diagnostic, not absolute accuracy)")
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    axis.grid(axis="y", alpha=0.25)
    axis.legend()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _save_figures(
    output: Path,
    algorithms: list[str],
    stable_algorithms: list[str],
    trajectories: dict[str, dict[str, np.ndarray]],
    aligned: dict[str, np.ndarray],
    metric_rows: list[dict[str, Any]],
    alignment_rows: list[dict[str, Any]],
    baseline: str,
) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = plt.get_cmap("tab20")
    color_map = {
        algorithm: colors(index % 20)
        for index, algorithm in enumerate(algorithms)
    }
    indexed_metrics = {row["algorithm"]: row for row in metric_rows}
    stable_metric_rows = [
        indexed_metrics[algorithm]
        for algorithm in stable_algorithms
        if algorithm in indexed_metrics
    ]
    indexed_alignment = {row["algorithm"]: row for row in alignment_rows}
    stable_alignment_rows = [
        indexed_alignment[algorithm]
        for algorithm in stable_algorithms
        if algorithm in indexed_alignment
    ]

    figures = {
        "trajectory_xy_overlay": str(output / "trajectory_xy_overlay.png"),
        "trajectory_xy_overlay_all": str(
            output / "trajectory_xy_overlay_all.png"
        ),
        "trajectory_z_drift": str(output / "trajectory_z_drift.png"),
        "trajectory_z_drift_all": str(output / "trajectory_z_drift_all.png"),
        "diagnostic_dashboard": str(output / "diagnostic_dashboard.png"),
        "diagnostic_dashboard_all": str(
            output / "diagnostic_dashboard_all.png"
        ),
        "relative_to_baseline": str(output / "relative_to_baseline.png"),
    }

    _plot_xy(
        Path(figures["trajectory_xy_overlay"]),
        stable_algorithms,
        aligned,
        baseline,
        color_map,
        "health-valid trajectories",
    )
    _plot_xy(
        Path(figures["trajectory_xy_overlay_all"]),
        algorithms,
        aligned,
        baseline,
        color_map,
        "all trajectories, including divergence",
    )
    _plot_z(
        Path(figures["trajectory_z_drift"]),
        stable_algorithms,
        trajectories,
        aligned,
        color_map,
        "health-valid trajectories",
    )
    _plot_z(
        Path(figures["trajectory_z_drift_all"]),
        algorithms,
        trajectories,
        aligned,
        color_map,
        "all trajectories, including divergence",
    )
    _plot_dashboard(
        Path(figures["diagnostic_dashboard"]),
        stable_metric_rows,
        title_suffix="health-valid trajectories",
        mark_invalid=False,
    )
    _plot_dashboard(
        Path(figures["diagnostic_dashboard_all"]),
        metric_rows,
        title_suffix="all trajectories; health-fail rows marked",
        mark_invalid=True,
    )
    _plot_relative_baseline(
        Path(figures["relative_to_baseline"]),
        stable_alignment_rows,
        baseline,
    )
    return figures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render lightweight LIO comparison figures from standardized outputs"
    )
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument(
        "--algorithms",
        help="Comma-separated algorithm keys; default follows full_comparison.json order",
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    run = args.run.resolve()
    algorithms = discover_algorithms(run)
    if args.algorithms:
        requested = [
            item.strip() for item in args.algorithms.split(",") if item.strip()
        ]
        algorithms = [
            algorithm for algorithm in requested if algorithm in algorithms
        ]
    if not algorithms:
        raise ValueError(
            f"no standardized trajectories found in "
            f"{run / 'standardized' / 'trajectories'}"
        )
    baseline = args.baseline if args.baseline in algorithms else algorithms[0]
    trajectories = {
        algorithm: load_trajectory(
            run / "standardized" / "trajectories" / f"{algorithm}.csv"
        )
        for algorithm in algorithms
    }

    aligned: dict[str, np.ndarray] = {
        baseline: trajectories[baseline]["positions"].copy()
    }
    alignment: dict[str, Any] = {
        baseline: {
            "method": "identity",
            "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
        }
    }
    for algorithm in algorithms:
        if algorithm == baseline:
            continue
        aligned[algorithm], alignment[algorithm] = align_candidate_to_baseline(
            trajectories[baseline], trajectories[algorithm]
        )

    comparison = load_json(run / "metrics" / "full_comparison.json", {}) or {}
    metric_rows = build_metric_summary(comparison, algorithms)
    stable_algorithms, excluded = choose_stable_algorithms(
        algorithms, metric_rows, baseline
    )
    alignment_rows = build_alignment_summary(
        alignment, metric_rows, algorithms, baseline
    )

    output = (
        args.output_dir or run / "figures" / "comparison_dashboard"
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    figures = _save_figures(
        output,
        algorithms,
        stable_algorithms,
        trajectories,
        aligned,
        metric_rows,
        alignment_rows,
        baseline,
    )

    metadata = {
        "schema_version": 2,
        "baseline": baseline,
        "algorithms": algorithms,
        "health_valid_algorithms": stable_algorithms,
        "excluded_from_health_valid_views": excluded,
        "metric_class": "diagnostic/relative-to-baseline/non-ground-truth",
        "alignment": alignment,
        "alignment_summary": alignment_rows,
        "metrics": metric_rows,
        "figures": figures,
        "note": (
            "Main XY/Z/dashboard figures show only lifecycle-success trajectories "
            "without health flags. *_all figures retain divergent/short trajectories "
            "for failure diagnosis. XY alignment uses initial yaw + translation to "
            "the selected baseline. Without independent ground truth, relative "
            "differences are diagnostic rather than absolute accuracy rankings."
        ),
    }
    (output / "comparison_visualization.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        "# Comparison dashboard\n\n"
        "The primary `trajectory_xy_overlay.png`, `trajectory_z_drift.png`, and "
        "`diagnostic_dashboard.png` exclude trajectories that are not lifecycle "
        "SUCCESS or carry health flags such as `trajectory_short` or "
        "`path_divergence`. This prevents failed trajectories from flattening the "
        "scale of otherwise comparable algorithms.\n\n"
        "The corresponding `*_all.png` files retain every standardized trajectory "
        "for failure diagnosis. `relative_to_baseline.png` compares relative RMSE "
        "and P95 only among health-valid trajectories. No rosbag replay is needed. "
        "Without independent ground truth, all trajectory differences remain "
        "diagnostic rather than absolute accuracy metrics.\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "baseline": baseline,
                "algorithms": algorithms,
                "health_valid_algorithms": stable_algorithms,
                "excluded_from_health_valid_views": excluded,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
