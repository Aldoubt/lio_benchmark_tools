#!/usr/bin/env python3
"""Enhance reconstructed-map comparison with quantitative map consistency.

The raw maps are produced from the same LiDAR samples and each standardized
trajectory. This stage does not rebuild maps. It reads current-run PLY files,
computes baseline-relative map-consistency diagnostics and renders shared-scale
health-gated plus all-run comparison grids.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from map_consistency import (
    MAP_SYMMETRIC_NN_P95_MAX_M,
    MAP_VOXEL_IOU_MIN,
    MAP_Z_SPAN_RATIO_LIMIT,
    ROBUST_HIGH_PERCENTILE,
    ROBUST_LOW_PERCENTILE,
    map_health_flags,
    robust_extent_xyz,
    symmetric_nn_metrics,
    voxel_iou,
)


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

METRIC_CLASS = "relative-to-baseline/diagnostic/non-ground-truth"


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def health_valid(item: dict[str, Any]) -> bool:
    return item.get("status") == "SUCCESS" and not list(item.get("health_flags") or [])


def choose_map_sets(
    algorithms: list[str],
    health: dict[str, dict[str, Any]],
    map_metrics: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[str], list[str]]:
    """Return selection-facing and all-run map sets.

    Before map metrics exist this behaves like the original trajectory-health
    gate. Once map metrics are available, an explicit map-health failure also
    removes the algorithm from the primary view while `*_all` retains it.
    """
    all_algorithms = list(algorithms)
    primary = []
    for algorithm in all_algorithms:
        if not health_valid(health.get(algorithm, {})):
            continue
        if map_metrics is not None:
            item = map_metrics.get(algorithm, {})
            if item.get("map_health_pass") is False:
                continue
        primary.append(algorithm)
    return primary, all_algorithms


def shared_projection_limits(
    clouds: dict[str, np.ndarray],
    algorithms: list[str],
) -> dict[str, tuple[float, float]]:
    selected = [
        clouds[algorithm]
        for algorithm in algorithms
        if algorithm in clouds and len(clouds[algorithm])
    ]
    if not selected:
        raise ValueError("no map clouds available")
    return {
        axis: (
            float(min(np.min(cloud[:, index]) for cloud in selected)),
            float(max(np.max(cloud[:, index]) for cloud in selected)),
        )
        for index, axis in enumerate(("x", "y", "z"))
    }


def read_ply(path: Path) -> np.ndarray:
    """Read the fixed x/y/z/intensity binary PLY written by the map builder."""
    path = Path(path)
    with path.open("rb") as stream:
        vertex_count = None
        while True:
            line = stream.readline()
            if not line:
                raise ValueError(f"invalid PLY header: {path}")
            text = line.decode("ascii").strip()
            if text.startswith("element vertex "):
                vertex_count = int(text.split()[-1])
            if text == "end_header":
                break
        if vertex_count is None:
            raise ValueError(f"PLY missing vertex count: {path}")
        data = np.fromfile(stream, dtype="<f4", count=vertex_count * 4)
    if data.size != vertex_count * 4:
        raise ValueError(f"truncated PLY: {path}")
    return data.reshape(vertex_count, 4).astype(np.float64)


def _expanded(pair: tuple[float, float]) -> tuple[float, float]:
    low, high = pair
    if high > low:
        return low, high
    padding = max(abs(low) * 0.01, 0.5)
    return low - padding, high + padding


def _plot_grid(
    path: Path,
    clouds: dict[str, np.ndarray],
    algorithms: list[str],
    health: dict[str, dict[str, Any]],
    map_metrics: dict[str, dict[str, Any]],
    *,
    projection: str,
    title: str,
) -> None:
    if not algorithms:
        return

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize

    limits = shared_projection_limits(clouds, algorithms)
    z_low, z_high = _expanded(limits["z"])
    normalizer = Normalize(z_low, z_high)
    colormap = plt.get_cmap("viridis")

    columns = min(5, max(1, len(algorithms)))
    rows = math.ceil(len(algorithms) / columns)
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(4.5 * columns, 3.8 * rows),
        squeeze=False,
        constrained_layout=True,
    )

    if projection == "xy":
        first, second = 0, 1
        x_limits = _expanded(limits["x"])
        y_limits = _expanded(limits["y"])
        y_label = "Y (m)"
    elif projection == "xz":
        first, second = 0, 2
        x_limits = _expanded(limits["x"])
        y_limits = _expanded(limits["z"])
        y_label = "Z (m)"
    else:
        raise ValueError(f"unknown projection: {projection}")

    for axis, algorithm in zip(axes.flat, algorithms):
        cloud = clouds[algorithm]
        shown = cloud[:: max(1, len(cloud) // 100_000)]
        axis.scatter(
            shown[:, first],
            shown[:, second],
            c=shown[:, 2],
            s=0.12,
            cmap=colormap,
            norm=normalizer,
            rasterized=True,
        )
        suffix = ""
        if not health_valid(health.get(algorithm, {})):
            suffix = " [trajectory-health-fail]"
        elif map_metrics.get(algorithm, {}).get("map_health_pass") is False:
            suffix = " [map-health-fail]"
        axis.set_title(LABELS.get(algorithm, algorithm) + suffix)
        axis.set_xlim(*x_limits)
        axis.set_ylim(*y_limits)
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlabel("X (m)")
        axis.set_ylabel(y_label)
        axis.grid(alpha=0.15)

    for axis in axes.flat[len(algorithms) :]:
        axis.set_visible(False)

    scalar = plt.cm.ScalarMappable(norm=normalizer, cmap=colormap)
    scalar.set_array([])
    figure.colorbar(
        scalar,
        ax=[axis for axis in axes.flat[: len(algorithms)]],
        label="Z (m), shared scale",
        shrink=0.82,
    )
    figure.suptitle(title)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def build_metrics(
    clouds: dict[str, np.ndarray],
    algorithms: list[str],
    health: dict[str, dict[str, Any]],
    visualization: dict[str, Any],
    *,
    baseline: str,
    comparison_voxel_m: float,
) -> dict[str, dict[str, Any]]:
    if baseline not in clouds:
        raise ValueError(f"baseline map is unavailable: {baseline}")
    comparisons = visualization.get("trajectory_comparison") or {}
    baseline_cloud = clouds[baseline]
    result: dict[str, dict[str, Any]] = {}

    for algorithm in algorithms:
        cloud = clouds[algorithm]
        relative = comparisons.get(algorithm) or {}
        health_item = health.get(algorithm, {})
        if algorithm == baseline:
            iou = 1.0
            nn = {
                "mean_m": 0.0,
                "rmse_m": 0.0,
                "p95_m": 0.0,
                "max_m": 0.0,
                "samples_reference": min(len(baseline_cloud), 50_000),
                "samples_candidate": min(len(baseline_cloud), 50_000),
            }
        else:
            iou = voxel_iou(baseline_cloud, cloud, comparison_voxel_m)
            nn = symmetric_nn_metrics(baseline_cloud, cloud)
        result[algorithm] = {
            "label": LABELS.get(algorithm, algorithm),
            "status": health_item.get("status"),
            "health_flags": list(health_item.get("health_flags") or []),
            "health_pass": health_valid(health_item),
            "available": True,
            "map_points": int(len(cloud)),
            "extent_xyz_m": np.ptp(cloud[:, :3], axis=0).tolist(),
            "robust_extent_xyz_m": robust_extent_xyz(cloud).tolist(),
            "baseline_voxel_iou": float(iou),
            "comparison_voxel_m": float(comparison_voxel_m),
            "symmetric_nn_mean_m": nn["mean_m"],
            "symmetric_nn_rmse_m": nn["rmse_m"],
            "symmetric_nn_p95_m": nn["p95_m"],
            "symmetric_nn_max_m": nn["max_m"],
            "symmetric_nn_samples_reference": nn["samples_reference"],
            "symmetric_nn_samples_candidate": nn["samples_candidate"],
            "relative_rmse_m": relative.get("rmse_m"),
            "relative_p95_m": relative.get("p95_m"),
            "ply": f"{algorithm}_map.ply",
        }

    baseline_metrics = result[baseline]
    for algorithm, item in result.items():
        flags = [] if algorithm == baseline else map_health_flags(item, baseline_metrics)
        item["map_health_flags"] = flags
        item["map_health_pass"] = not flags
    return result


def _write_metrics_markdown(path: Path, metrics: dict[str, Any]) -> None:
    lines = [
        "# Map comparison metrics",
        "",
        f"- Baseline: `{metrics['baseline']}`",
        f"- Metric class: `{METRIC_CLASS}`",
        f"- Robust extent: `P{ROBUST_HIGH_PERCENTILE:g}-P{ROBUST_LOW_PERCENTILE:g}` per axis.",
        f"- Occupancy comparison voxel: `{metrics['comparison_voxel_m']:.3f} m`.",
        "- Primary figures require trajectory health and map health; `*_all` retains every reconstructable map.",
        "- Symmetric nearest-neighbour metrics use deterministic bounded samples.",
        "",
        "| Algorithm | Status | Traj health | Map health | Map points | Raw Z span (m) | Robust Z span (m) | Voxel IoU | Sym NN RMSE (m) | Sym NN P95 (m) | Rel RMSE (m) | Rel P95 (m) |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def number(value: Any) -> str:
        return "N/A" if value is None else f"{float(value):.3f}"

    for algorithm in metrics["all_algorithms"]:
        item = metrics["algorithms"][algorithm]
        extent = item["extent_xyz_m"]
        robust = item["robust_extent_xyz_m"]
        trajectory_health = (
            "normal"
            if item["health_pass"]
            else ";".join(item["health_flags"]) or "needs_review"
        )
        map_health = (
            "normal"
            if item["map_health_pass"]
            else ";".join(item["map_health_flags"])
        )
        lines.append(
            f"| {item['label']} | {item['status']} | {trajectory_health} | {map_health} | "
            f"{item['map_points']} | {extent[2]:.3f} | {robust[2]:.3f} | "
            f"{number(item.get('baseline_voxel_iou'))} | "
            f"{number(item.get('symmetric_nn_rmse_m'))} | "
            f"{number(item.get('symmetric_nn_p95_m'))} | "
            f"{number(item.get('relative_rmse_m'))} | {number(item.get('relative_p95_m'))} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    args = parser.parse_args()

    run = args.run.resolve()
    output = run / "figures" / "fast_livo2_baseline_maps"
    comparison = load_json(run / "metrics" / "full_comparison.json", {}) or {}
    health = {
        item["algorithm"]: item
        for item in comparison.get("algorithms", []) or []
        if isinstance(item, dict) and item.get("algorithm")
    }
    visualization = load_json(output / "visualization_metadata.json", {}) or {}
    requested = visualization.get("selected_algorithms") or list(health)
    algorithms = [
        algorithm
        for algorithm in requested
        if (output / f"{algorithm}_map.ply").is_file()
    ]
    if not algorithms:
        raise ValueError(f"no reconstructed map PLY files found in {output}")
    if args.baseline not in algorithms:
        raise ValueError(f"baseline map is unavailable: {args.baseline}")

    clouds = {
        algorithm: read_ply(output / f"{algorithm}_map.ply")
        for algorithm in algorithms
    }
    reconstruction_voxel = float(visualization.get("voxel_m") or 0.12)
    comparison_voxel_m = max(0.5, 4.0 * reconstruction_voxel)
    algorithm_metrics = build_metrics(
        clouds,
        algorithms,
        health,
        visualization,
        baseline=args.baseline,
        comparison_voxel_m=comparison_voxel_m,
    )
    primary, all_algorithms = choose_map_sets(algorithms, health, algorithm_metrics)
    if args.baseline in all_algorithms and args.baseline not in primary:
        primary.insert(0, args.baseline)

    _plot_grid(
        output / "map_comparison_xy.png",
        clouds,
        primary,
        health,
        algorithm_metrics,
        projection="xy",
        title="Map comparison XY — trajectory+map-health valid, shared axes/Z scale",
    )
    _plot_grid(
        output / "map_comparison_xz.png",
        clouds,
        primary,
        health,
        algorithm_metrics,
        projection="xz",
        title="Map comparison XZ — trajectory+map-health valid, shared axes/Z scale",
    )
    _plot_grid(
        output / "map_comparison_xy_all.png",
        clouds,
        all_algorithms,
        health,
        algorithm_metrics,
        projection="xy",
        title="Map comparison XY — all available algorithms",
    )
    _plot_grid(
        output / "map_comparison_xz_all.png",
        clouds,
        all_algorithms,
        health,
        algorithm_metrics,
        projection="xz",
        title="Map comparison XZ — all available algorithms",
    )

    metrics = {
        "schema_version": 2,
        "baseline": args.baseline,
        "metric_class": METRIC_CLASS,
        "primary_algorithms": primary,
        "all_algorithms": all_algorithms,
        "shared_scale": True,
        "comparison_voxel_m": comparison_voxel_m,
        "robust_extent_percentiles": [ROBUST_LOW_PERCENTILE, ROBUST_HIGH_PERCENTILE],
        "map_health_thresholds": {
            "robust_z_span_ratio_max": MAP_Z_SPAN_RATIO_LIMIT,
            "baseline_voxel_iou_min": MAP_VOXEL_IOU_MIN,
            "symmetric_nn_p95_max_m": MAP_SYMMETRIC_NN_P95_MAX_M,
        },
        "algorithms": algorithm_metrics,
    }
    (output / "map_comparison_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_metrics_markdown(output / "map_comparison_metrics.md", metrics)

    print(
        json.dumps(
            {
                "output": str(output),
                "primary_algorithms": len(primary),
                "all_algorithms": len(all_algorithms),
                "comparison_voxel_m": comparison_voxel_m,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
