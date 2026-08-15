#!/usr/bin/env python3
"""Generate paper-oriented comparison figures and a benchmark summary report."""
from __future__ import annotations

import argparse
import html
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.trajectory import Trajectory  # noqa: E402
from reporting.contracts import AlgorithmSummary, collect_summary, write_summary_csv  # noqa: E402
from visualization.alignment import StartYawAlignment, load_start_yaw_alignment  # noqa: E402
from visualization.pointcloud_io import PointCloudData, read_standard_ply  # noqa: E402
from visualization.presets import RoiPreset, load_roi  # noqa: E402


def require_matplotlib() -> Any:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("Report generation requires matplotlib.") from exc
    return plt


def algorithm_label(manifest: dict[str, Any], algorithm_id: str) -> str:
    value = manifest.get("algorithms", {}).get(algorithm_id, {})
    return str(value.get("display_name", algorithm_id)) if isinstance(value, dict) else algorithm_id


def alignment_for(run: Path, algorithm_id: str, mode: str) -> StartYawAlignment | None:
    if mode == "raw":
        return None
    path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
    if not path.is_file():
        return None
    return load_start_yaw_alignment(path)


def load_maps(run: Path, algorithms: list[str], roi: RoiPreset | None, display_alignment: str) -> dict[str, PointCloudData]:
    result: dict[str, PointCloudData] = {}
    for algorithm_id in algorithms:
        path = run / "standardized" / "maps" / algorithm_id / "unified_map.ply"
        if not path.is_file():
            continue
        try:
            cloud = read_standard_ply(path)
            alignment = alignment_for(run, algorithm_id, display_alignment)
            if alignment is not None:
                cloud = PointCloudData(alignment.apply_xyz(cloud.xyz), cloud.intensity)
            if roi is not None:
                cloud = cloud.cropped(roi.min_xyz, roi.max_xyz)
            if len(cloud.xyz):
                result[algorithm_id] = cloud
        except ValueError as exc:
            print(f"skip map {algorithm_id}: {exc}", file=sys.stderr)
    return result


def shared_limits(clouds: dict[str, PointCloudData]) -> tuple[np.ndarray, np.ndarray]:
    low = np.min(np.vstack([cloud.bounds()[0] for cloud in clouds.values()]), axis=0)
    high = np.max(np.vstack([cloud.bounds()[1] for cloud in clouds.values()]), axis=0)
    padding = np.maximum((high - low) * 0.03, 0.05)
    return low - padding, high + padding


def shared_height_limits(clouds: dict[str, PointCloudData]) -> tuple[float, float]:
    samples: list[np.ndarray] = []
    for cloud in clouds.values():
        z = cloud.xyz[:, 2]
        samples.append(z[::max(1, len(z) // 50_000)])
    joined = np.concatenate(samples)
    low, high = np.percentile(joined, [2.0, 98.0])
    return float(low), float(high if high > low else low + 1.0)


def plot_map_grid(manifest: dict[str, Any], clouds: dict[str, PointCloudData], plane: str, output: Path) -> None:
    if not clouds:
        return
    plt = require_matplotlib()
    axes_index = {"xy": (0, 1), "xz": (0, 2), "yz": (1, 2)}
    a, b = axes_index[plane]
    low, high = shared_limits(clouds)
    zlow, zhigh = shared_height_limits(clouds)
    columns = min(3, len(clouds)); rows = math.ceil(len(clouds) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(5.2 * columns, 5.0 * rows), squeeze=False, constrained_layout=True)
    for axis in axes.flat:
        axis.set_visible(False)
    for axis, (algorithm_id, cloud) in zip(axes.flat, clouds.items()):
        axis.set_visible(True)
        step = max(1, len(cloud.xyz) // 150_000); shown = cloud.xyz[::step]
        axis.scatter(shown[:, a], shown[:, b], c=shown[:, 2], s=0.15, cmap="viridis", vmin=zlow, vmax=zhigh, rasterized=True)
        axis.set_xlim(low[a], high[a]); axis.set_ylim(low[b], high[b]); axis.set_aspect("equal", adjustable="box")
        axis.set_title(algorithm_label(manifest, algorithm_id)); axis.set_xlabel("XYZ"[a] + " (m)"); axis.set_ylabel("XYZ"[b] + " (m)"); axis.grid(alpha=0.2)
    fig.suptitle(f"Same-bag unified map comparison — {plane.upper()} · shared height scale")
    output.parent.mkdir(parents=True, exist_ok=True); fig.savefig(output, dpi=200); plt.close(fig)


def plot_trajectory(run: Path, manifest: dict[str, Any], algorithms: list[str], output: Path, display_alignment: str) -> None:
    plt = require_matplotlib(); fig, axis = plt.subplots(figsize=(9, 8), constrained_layout=True); count = 0
    for algorithm_id in algorithms:
        path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
        if not path.is_file():
            continue
        try:
            trajectory = Trajectory.from_csv(path)
        except ValueError:
            continue
        xyz = np.asarray([[s.x_m, s.y_m, s.z_m] for s in trajectory.samples], dtype=np.float64)
        alignment = alignment_for(run, algorithm_id, display_alignment)
        if alignment is not None:
            xyz = alignment.apply_xyz(xyz)
        axis.plot(xyz[:, 0], xyz[:, 1], linewidth=1.2, label=algorithm_label(manifest, algorithm_id)); count += 1
    if not count:
        plt.close(fig); return
    axis.set_xlabel("X (m)"); axis.set_ylabel("Y (m)"); axis.set_title("Standardized XY trajectories")
    axis.set_aspect("equal", adjustable="box"); axis.grid(alpha=0.25); axis.legend(); output.parent.mkdir(parents=True, exist_ok=True); fig.savefig(output, dpi=200); plt.close(fig)


def plot_runtime(manifest: dict[str, Any], summaries: list[AlgorithmSummary], output: Path) -> None:
    valid = [row for row in summaries if row.runtime_s is not None]
    if not valid:
        return
    plt = require_matplotlib(); fig, axis = plt.subplots(figsize=(9, 5), constrained_layout=True)
    axis.bar([algorithm_label(manifest, row.algorithm_id) for row in valid], [row.runtime_s for row in valid])
    axis.set_ylabel("runner wall-clock time (s)"); axis.set_title("Benchmark runner wall-clock time (formal adapters default bag rate = 1.0)")
    axis.tick_params(axis="x", rotation=25); axis.grid(axis="y", alpha=0.25); output.parent.mkdir(parents=True, exist_ok=True); fig.savefig(output, dpi=200); plt.close(fig)


def markdown_table(rows: list[AlgorithmSummary], manifest: dict[str, Any]) -> str:
    lines = ["| Algorithm | Run | Trajectory | Map | Path (m) | Map points | Matched / Unmatched scans | Runtime (s) |", "|---|---|---|---|---:|---:|---:|---:|"]
    for row in rows:
        pair = "—" if row.matched_scans is None else f"{row.matched_scans} / {row.unmatched_scans}"
        lines.append("| " + " | ".join((algorithm_label(manifest, row.algorithm_id), row.run_status, row.trajectory_status, f"{row.map_status} ({row.map_source or '—'})", "—" if row.path_length_m is None else f"{row.path_length_m:.3f}", "—" if row.map_points is None else str(row.map_points), pair, "—" if row.runtime_s is None else f"{row.runtime_s:.2f}")) + " |")
    return "\n".join(lines)


def write_report(run: Path, manifest: dict[str, Any], summaries: list[AlgorithmSummary], figures: list[Path], display_alignment: str) -> None:
    dataset = manifest.get("dataset", {}); table = markdown_table(summaries, manifest)
    figure_lines = "\n".join(f"![{path.stem}](../figures/{path.name})" for path in figures if path.is_file())
    markdown = f"""# LIO Benchmark Report — {manifest.get('run_id', run.name)}

- Dataset: `{dataset.get('dataset_id', 'legacy_v1_dataset')}`
- Bag: `{dataset.get('bag_dir', '')}`
- Display alignment: `{display_alignment}`
- Ground truth: this report does **not** assume trajectory ground truth unless a separate evaluator explicitly provides it

`start_yaw` display alignment subtracts each estimator's first position and removes only its initial yaw for visualization. It never rewrites standardized trajectory/map artifacts and is not an accuracy correction.

## Artifact status

{table}

Missing and invalid artifacts are reported explicitly rather than converted to zero scores.

## Figures

{figure_lines or 'No plot-ready standardized artifacts were available.'}
"""
    reports = run / "reports"; reports.mkdir(parents=True, exist_ok=True); (reports / "report.md").write_text(markdown, encoding="utf-8")
    image_tags = "".join(f'<h3>{html.escape(path.stem)}</h3><img src="../figures/{html.escape(path.name)}" style="max-width:100%;">' for path in figures if path.is_file())
    (reports / "report.html").write_text("<!doctype html><meta charset='utf-8'><title>LIO Benchmark Report</title><style>body{font-family:system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem;}pre{white-space:pre-wrap;}img{border:1px solid #ddd;}</style><pre>" + html.escape(markdown) + "</pre>" + image_tags, encoding="utf-8")


def generate(run: Path, roi_path: Path | None = None, display_alignment: str = "start_yaw") -> None:
    manifest = load_json(run / "manifest.json"); algorithms = list(manifest.get("algorithms", {}))
    summaries = [collect_summary(run, algorithm_id) for algorithm_id in algorithms]; write_summary_csv(run / "metrics" / "summary.csv", summaries)
    roi = load_roi(roi_path) if roi_path else None; clouds = load_maps(run, algorithms, roi, display_alignment)
    figures = [run / "figures/trajectory_xy.png", run / "figures/map_xy_comparison.png", run / "figures/map_xz_comparison.png", run / "figures/map_yz_comparison.png", run / "figures/runtime_comparison.png"]
    plot_trajectory(run, manifest, algorithms, figures[0], display_alignment); plot_map_grid(manifest, clouds, "xy", figures[1]); plot_map_grid(manifest, clouds, "xz", figures[2]); plot_map_grid(manifest, clouds, "yz", figures[3]); plot_runtime(manifest, summaries, figures[4]); write_report(run, manifest, summaries, figures, display_alignment); print(run / "reports/report.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", type=Path, required=True); parser.add_argument("--roi", type=Path); parser.add_argument("--display-alignment", choices=("start_yaw", "raw"), default="start_yaw"); args = parser.parse_args(); generate(args.run.resolve(), args.roi, args.display_alignment); return 0


if __name__ == "__main__":
    raise SystemExit(main())
