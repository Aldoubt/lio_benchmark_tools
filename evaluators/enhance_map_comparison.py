#!/usr/bin/env python3
"""Enhance reconstructed-map comparison with health gating and shared scales.

The raw maps are produced by visualize_baseline_maps.py from the same LiDAR
samples and each standardized trajectory.  This script does not rebuild the
maps.  It reads those PLY files and produces presentation/diagnostic grids
whose panels share projection limits and a common Z color scale.
"""
from __future__ import annotations

import argparse
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
) -> tuple[list[str], list[str]]:
    """Return paper-facing health-valid algorithms and the all-run diagnostic set."""
    all_algorithms = list(algorithms)
    primary = [
        algorithm
        for algorithm in all_algorithms
        if health_valid(health.get(algorithm, {}))
    ]
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
    """Read the fixed x/y/z/intensity binary PLY written by visualize_baseline_maps."""
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
        suffix = "" if health_valid(health.get(algorithm, {})) else " [health-fail]"
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
) -> dict[str, dict[str, Any]]:
    comparisons = visualization.get("trajectory_comparison") or {}
    result: dict[str, dict[str, Any]] = {}
    for algorithm in algorithms:
        cloud = clouds[algorithm]
        relative = comparisons.get(algorithm) or {}
        health_item = health.get(algorithm, {})
        result[algorithm] = {
            "label": LABELS.get(algorithm, algorithm),
            "status": health_item.get("status"),
            "health_flags": list(health_item.get("health_flags") or []),
            "health_pass": health_valid(health_item),
            "available": True,
            "map_points": int(len(cloud)),
            "extent_xyz_m": np.ptp(cloud[:, :3], axis=0).tolist(),
            "relative_rmse_m": relative.get("rmse_m"),
            "relative_p95_m": relative.get("p95_m"),
            "ply": f"{algorithm}_map.ply",
        }
    return result


def _write_metrics_markdown(path: Path, metrics: dict[str, Any]) -> None:
    lines = [
        "# Map comparison metrics",
        "",
        f"- Baseline: `{metrics['baseline']}`",
        f"- Metric class: `{METRIC_CLASS}`",
        "- Primary figures are health-gated; `*_all` retains failed/crashed trajectories when a map exists.",
        "- Every panel in one figure shares projection limits and one Z color scale.",
        "",
        "| Algorithm | Status | Health | Map points | X extent (m) | Y extent (m) | Z extent (m) | Rel RMSE (m) | Rel P95 (m) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    def number(value: Any) -> str:
        return "N/A" if value is None else f"{float(value):.3f}"

    for algorithm in metrics["all_algorithms"]:
        item = metrics["algorithms"][algorithm]
        extent = item["extent_xyz_m"]
        health = (
            "normal"
            if item["health_pass"]
            else ";".join(item["health_flags"]) or "needs_review"
        )
        lines.append(
            f"| {item['label']} | {item['status']} | {health} | {item['map_points']} | "
            f"{extent[0]:.3f} | {extent[1]:.3f} | {extent[2]:.3f} | "
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

    clouds = {
        algorithm: read_ply(output / f"{algorithm}_map.ply")
        for algorithm in algorithms
    }
    primary, all_algorithms = choose_map_sets(algorithms, health)
    if args.baseline in all_algorithms and args.baseline not in primary:
        primary.insert(0, args.baseline)

    _plot_grid(
        output / "map_comparison_xy.png",
        clouds,
        primary,
        health,
        projection="xy",
        title="Map comparison XY — health-valid algorithms, shared axes/Z scale",
    )
    _plot_grid(
        output / "map_comparison_xz.png",
        clouds,
        primary,
        health,
        projection="xz",
        title="Map comparison XZ — health-valid algorithms, shared axes/Z scale",
    )
    _plot_grid(
        output / "map_comparison_xy_all.png",
        clouds,
        all_algorithms,
        health,
        projection="xy",
        title="Map comparison XY — all available algorithms",
    )
    _plot_grid(
        output / "map_comparison_xz_all.png",
        clouds,
        all_algorithms,
        health,
        projection="xz",
        title="Map comparison XZ — all available algorithms",
    )

    metrics = {
        "schema_version": 1,
        "baseline": args.baseline,
        "metric_class": METRIC_CLASS,
        "primary_algorithms": primary,
        "all_algorithms": all_algorithms,
        "shared_scale": True,
        "algorithms": build_metrics(
            clouds,
            all_algorithms,
            health,
            visualization,
        ),
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
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
