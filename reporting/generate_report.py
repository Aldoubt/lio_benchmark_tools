#!/usr/bin/env python3
"""Generate paper-oriented comparison figures and a role-aware benchmark report."""
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

from benchmark_base.lib.artifacts import map_artifact_paths  # noqa: E402
from benchmark_base.lib.display_alignment import (  # noqa: E402
    normalize_display_alignment_mode,
    write_display_alignment_metadata,
)
from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.scoreboards import (  # noqa: E402
    SCOREBOARDS,
    group_manifest_algorithms,
    scoreboard_title,
)
from benchmark_base.lib.trajectory import Trajectory  # noqa: E402
from reporting.contracts import AlgorithmSummary, collect_summary, write_summary_csv  # noqa: E402
from reporting.diagnostics import (  # noqa: E402
    PairwiseDisagreement,
    collect_run_diagnostics,
    warmup_suffix,
    write_run_diagnostics,
)
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
    canonical = normalize_display_alignment_mode(mode)
    path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
    if not path.is_file():
        return None
    write_display_alignment_metadata(
        run=run,
        algorithm_id=algorithm_id,
        trajectory_role="ODOMETRY",
        trajectory_path=path,
        mode=canonical,
    )
    if canonical == "NONE":
        return None
    return load_start_yaw_alignment(path)


def _unified_map_path(run: Path, algorithm_id: str) -> Path:
    paths = map_artifact_paths(run, algorithm_id)
    if paths.unified_map.is_file():
        return paths.unified_map
    return paths.compat_unified_map


def load_maps(run: Path, algorithms: list[str], roi: RoiPreset | None, display_alignment: str) -> dict[str, PointCloudData]:
    result: dict[str, PointCloudData] = {}
    for algorithm_id in algorithms:
        path = _unified_map_path(run, algorithm_id)
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


def plot_map_grid(manifest: dict[str, Any], clouds: dict[str, PointCloudData], plane: str, output: Path, alignment_mode: str) -> None:
    if not clouds:
        return
    plt = require_matplotlib()
    axes_index = {"xy": (0, 1), "xz": (0, 2), "yz": (1, 2)}
    a, b = axes_index[plane]
    low, high = shared_limits(clouds)
    zlow, zhigh = shared_height_limits(clouds)
    columns = min(3, len(clouds))
    rows = math.ceil(len(clouds) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(5.2 * columns, 5.0 * rows), squeeze=False, constrained_layout=True)
    for axis in axes.flat:
        axis.set_visible(False)
    for axis, (algorithm_id, cloud) in zip(axes.flat, clouds.items()):
        axis.set_visible(True)
        step = max(1, len(cloud.xyz) // 150_000)
        shown = cloud.xyz[::step]
        axis.scatter(shown[:, a], shown[:, b], c=shown[:, 2], s=0.15, cmap="viridis", vmin=zlow, vmax=zhigh, rasterized=True)
        axis.set_xlim(low[a], high[a])
        axis.set_ylim(low[b], high[b])
        axis.set_aspect("equal", adjustable="box")
        axis.set_title(algorithm_label(manifest, algorithm_id))
        axis.set_xlabel("XYZ"[a] + " (m)")
        axis.set_ylabel("XYZ"[b] + " (m)")
        axis.grid(alpha=0.2)
    fig.suptitle(f"Same-bag unified map comparison — {plane.upper()} · shared height scale · {alignment_mode}")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200)
    plt.close(fig)


def plot_trajectory(run: Path, manifest: dict[str, Any], algorithms: list[str], output: Path, display_alignment: str) -> None:
    plt = require_matplotlib()
    fig, axis = plt.subplots(figsize=(9, 8), constrained_layout=True)
    count = 0
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
        axis.plot(xyz[:, 0], xyz[:, 1], linewidth=1.2, label=algorithm_label(manifest, algorithm_id))
        count += 1
    if not count:
        plt.close(fig)
        return
    axis.set_xlabel("X (m)")
    axis.set_ylabel("Y (m)")
    axis.set_title(f"Standardized XY trajectories — {normalize_display_alignment_mode(display_alignment)}")
    axis.set_aspect("equal", adjustable="box")
    axis.grid(alpha=0.25)
    axis.legend()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200)
    plt.close(fig)


def _trajectory_series(trajectory: Trajectory, warmup_s: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if warmup_s < 0.0 or not math.isfinite(warmup_s):
        raise ValueError("warmup_s must be a finite non-negative value")
    if warmup_s == 0.0:
        selected = list(trajectory.samples)
        start = trajectory.timestamps[0]
    else:
        start = trajectory.timestamps[0] + warmup_s
        if start >= trajectory.timestamps[-1]:
            return tuple(np.asarray([], dtype=np.float64) for _ in range(5))  # type: ignore[return-value]
        max_gap = max(b - a for a, b in zip(trajectory.timestamps, trajectory.timestamps[1:]))
        boundary = trajectory.interpolate_pose(start, tolerance_s=max_gap + 1e-12).pose
        selected = [boundary]
        selected.extend(sample for sample in trajectory.samples if sample.timestamp_s > start + 1e-12)
    if len(selected) < 2:
        return tuple(np.asarray([], dtype=np.float64) for _ in range(5))  # type: ignore[return-value]
    time = np.asarray([sample.timestamp_s - start for sample in selected], dtype=np.float64)
    z = np.asarray([sample.z_m for sample in selected], dtype=np.float64)
    roll = np.asarray([sample.roll_rad for sample in selected], dtype=np.float64)
    pitch = np.asarray([sample.pitch_rad for sample in selected], dtype=np.float64)
    yaw = np.unwrap(np.asarray([sample.yaw_rad for sample in selected], dtype=np.float64))
    yaw -= yaw[0]
    return time, z, roll, pitch, yaw


def plot_state_series(run: Path, manifest: dict[str, Any], algorithms: list[str], output: Path, field: str, warmup_s: float) -> None:
    labels = {
        "z": ("Z (m)", "Trajectory Z vs relative time"),
        "roll": ("Roll (rad)", "Trajectory roll vs relative time"),
        "pitch": ("Pitch (rad)", "Trajectory pitch vs relative time"),
        "yaw": ("Relative yaw (rad)", "Relative yaw change vs time"),
    }
    plt = require_matplotlib()
    fig, axis = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
    count = 0
    index = {"z": 1, "roll": 2, "pitch": 3, "yaw": 4}[field]
    for algorithm_id in algorithms:
        path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
        if not path.is_file():
            continue
        try:
            series = _trajectory_series(Trajectory.from_csv(path), warmup_s)
        except ValueError:
            continue
        if not len(series[0]):
            continue
        axis.plot(series[0], series[index], linewidth=1.2, label=algorithm_label(manifest, algorithm_id))
        count += 1
    if not count:
        plt.close(fig)
        return
    axis.set_xlabel(f"Time after warmup (s), warmup={warmup_s:g}s")
    axis.set_ylabel(labels[field][0])
    axis.set_title(labels[field][1])
    axis.grid(alpha=0.25)
    axis.legend()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200)
    plt.close(fig)


def plot_pairwise_disagreement(
    manifest: dict[str, Any],
    details: dict[tuple[str, str], PairwiseDisagreement],
    output: Path,
    field: str,
) -> None:
    if not details:
        return
    plt = require_matplotlib()
    fig, axis = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
    for (left_id, right_id), result in details.items():
        time = [row.relative_time_s for row in result.samples]
        values = [row.xy_m if field == "xy" else row.z_abs_m for row in result.samples]
        axis.plot(time, values, linewidth=1.2, label=f"{algorithm_label(manifest, left_id)} ↔ {algorithm_label(manifest, right_id)}")
    axis.set_xlabel("Common-overlap relative time (s)")
    axis.set_ylabel("XY disagreement (m)" if field == "xy" else "Absolute Z disagreement (m)")
    first = next(iter(details.values()))
    axis.set_title(
        ("Pairwise XY disagreement" if field == "xy" else "Pairwise Z disagreement")
        + f" — {first.alignment_mode} · warmup={first.warmup_s:g}s"
    )
    axis.grid(alpha=0.25)
    axis.legend()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200)
    plt.close(fig)


def plot_runtime(manifest: dict[str, Any], summaries: list[AlgorithmSummary], output: Path) -> None:
    valid = [row for row in summaries if row.runtime_s is not None]
    if not valid:
        return
    plt = require_matplotlib()
    fig, axis = plt.subplots(figsize=(9, 5), constrained_layout=True)
    axis.bar([algorithm_label(manifest, row.algorithm_id) for row in valid], [row.runtime_s for row in valid])
    axis.set_ylabel("runner wall-clock time (s)")
    axis.set_title("Benchmark runner wall-clock time (formal adapters default bag rate = 1.0)")
    axis.tick_params(axis="x", rotation=25)
    axis.grid(axis="y", alpha=0.25)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200)
    plt.close(fig)


def markdown_table(rows: list[AlgorithmSummary], manifest: dict[str, Any]) -> str:
    lines = [
        "| Algorithm | Run | Trajectory | Unified Map | Path (m) | Map points | Matched / Unmatched scans | Runtime (s) |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        pair = "—" if row.matched_scans is None else f"{row.matched_scans} / {row.unmatched_scans}"
        lines.append(
            "| "
            + " | ".join(
                (
                    algorithm_label(manifest, row.algorithm_id),
                    row.run_status,
                    row.trajectory_status,
                    f"{row.map_status} ({row.map_source or '—'})",
                    "—" if row.path_length_m is None else f"{row.path_length_m:.3f}",
                    "—" if row.map_points is None else str(row.map_points),
                    pair,
                    "—" if row.runtime_s is None else f"{row.runtime_s:.2f}",
                )
            )
            + " |"
        )
    return "\n".join(lines)


def scoreboard_markdown(manifest: dict[str, Any], summaries: list[AlgorithmSummary]) -> str:
    summary_by_id = {row.algorithm_id: row for row in summaries}
    grouped = group_manifest_algorithms(manifest)
    sections: list[str] = []
    for board in SCOREBOARDS:
        algorithm_ids = grouped[board]
        sections.append(f"### {scoreboard_title(board)}")
        if not algorithm_ids:
            sections.append("No algorithms in this run are eligible for this view.")
            continue
        rows = [summary_by_id[algorithm_id] for algorithm_id in algorithm_ids if algorithm_id in summary_by_id]
        sections.append(markdown_table(rows, manifest))
        if board == "COMMON_LIO":
            sections.append("Only LiDAR+IMU odometry runs with no camera, kinematics, GNSS, or wheel-odometry inputs are included here.")
        elif board == "SYSTEM_MAPPING":
            sections.append("This view contains globally optimized/system-mapping outputs and is not ranked as if it were pure odometry.")
        else:
            sections.append("This view contains controls or runs with an input profile that differs from the common LiDAR+IMU comparison.")
    return "\n\n".join(sections)


def write_report(run: Path, manifest: dict[str, Any], summaries: list[AlgorithmSummary], figures: list[Path], display_alignment: str, warmup_s: float) -> Path:
    dataset = manifest.get("dataset", {})
    canonical = normalize_display_alignment_mode(display_alignment)
    suffix = warmup_suffix(warmup_s)
    table = markdown_table(summaries, manifest)
    scoreboards = scoreboard_markdown(manifest, summaries)
    figure_lines = "\n".join(f"![{path.stem}](../figures/{path.name})" for path in figures if path.is_file())
    alignment_note = (
        "`START_XY_YAW` removes only each estimator's arbitrary initial X/Y origin and initial yaw for display/comparison. "
        "It preserves initial Z, roll, pitch, subsequent drift, scale error and non-rigid map distortion. "
        "It never rewrites standardized trajectories, Native Maps, Unified Maps, or scientific metrics."
        if canonical == "START_XY_YAW"
        else "`NONE` displays/compares standardized artifacts without a display transform."
    )
    smoke_name = f"smoke_diagnostics{suffix}.csv"
    pair_name = f"pairwise_disagreement{suffix}.csv"
    markdown = f"""# LIO Benchmark Report — {manifest.get('run_id', run.name)}

- Dataset: `{dataset.get('dataset_id', 'legacy_v1_dataset')}`
- Bag: `{dataset.get('bag_dir', '')}`
- Display alignment: `{canonical}`
- Diagnostic warmup: `{warmup_s:g} s`
- Map comparison shown in figures: `UNIFIED_RECONSTRUCTION`
- Ground truth: this report does **not** assume trajectory ground truth unless a separate evaluator explicitly provides it

{alignment_note}

## Artifact audit

{table}

Missing, blocked, failed, and invalid artifacts remain visible and are never converted to zero scores.

## Descriptive divergence diagnostics

`metrics/{smoke_name}` describes each standardized trajectory. `metrics/{pair_name}` compares estimator pairs only over their common timestamp interval using trajectory interpolation. Pairwise values are **disagreement**, not localization error or accuracy, because no ground-truth trajectory is assumed.

A non-zero warmup produces an additional post-initialization view with suffixed filenames; it does not delete, overwrite or rewrite the full-run diagnostic artifacts or source trajectory samples.

## Scoreboards

{scoreboards}

## Figures

{figure_lines or 'No plot-ready standardized artifacts were available.'}
"""
    reports = run / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    md_path = reports / f"report{suffix}.md"
    html_path = reports / f"report{suffix}.html"
    md_path.write_text(markdown, encoding="utf-8")
    image_tags = "".join(
        f'<h3>{html.escape(path.stem)}</h3><img src="../figures/{html.escape(path.name)}" style="max-width:100%;">'
        for path in figures
        if path.is_file()
    )
    html_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>LIO Benchmark Report</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem;}"
        "pre{white-space:pre-wrap;}img{border:1px solid #ddd;}</style><pre>"
        + html.escape(markdown)
        + "</pre>"
        + image_tags,
        encoding="utf-8",
    )
    return md_path


def generate(
    run: Path,
    roi_path: Path | None = None,
    display_alignment: str = "START_XY_YAW",
    warmup_s: float = 0.0,
) -> None:
    canonical = normalize_display_alignment_mode(display_alignment)
    suffix = warmup_suffix(warmup_s)
    manifest = load_json(run / "manifest.json")
    algorithms = list(manifest.get("algorithms", {}))
    summaries = [collect_summary(run, algorithm_id) for algorithm_id in algorithms]
    write_summary_csv(run / "metrics" / "summary.csv", summaries)
    diagnostic_rows, pair_rows, pair_details = collect_run_diagnostics(
        run,
        algorithms,
        warmup_s=warmup_s,
        alignment_mode=canonical,
        sample_period_s=0.1,
    )
    write_run_diagnostics(run, diagnostic_rows, pair_rows, warmup_s=warmup_s)
    roi = load_roi(roi_path) if roi_path else None
    clouds = load_maps(run, algorithms, roi, canonical)
    figures = [
        run / "figures/trajectory_xy.png",
        run / "figures/map_xy_comparison.png",
        run / "figures/map_xz_comparison.png",
        run / "figures/map_yz_comparison.png",
        run / "figures/runtime_comparison.png",
        run / f"figures/trajectory_z_vs_time{suffix}.png",
        run / f"figures/trajectory_roll_vs_time{suffix}.png",
        run / f"figures/trajectory_pitch_vs_time{suffix}.png",
        run / f"figures/trajectory_yaw_relative_vs_time{suffix}.png",
        run / f"figures/pairwise_xy_disagreement{suffix}.png",
        run / f"figures/pairwise_z_disagreement{suffix}.png",
    ]
    plot_trajectory(run, manifest, algorithms, figures[0], canonical)
    plot_map_grid(manifest, clouds, "xy", figures[1], canonical)
    plot_map_grid(manifest, clouds, "xz", figures[2], canonical)
    plot_map_grid(manifest, clouds, "yz", figures[3], canonical)
    plot_runtime(manifest, summaries, figures[4])
    plot_state_series(run, manifest, algorithms, figures[5], "z", warmup_s)
    plot_state_series(run, manifest, algorithms, figures[6], "roll", warmup_s)
    plot_state_series(run, manifest, algorithms, figures[7], "pitch", warmup_s)
    plot_state_series(run, manifest, algorithms, figures[8], "yaw", warmup_s)
    plot_pairwise_disagreement(manifest, pair_details, figures[9], "xy")
    plot_pairwise_disagreement(manifest, pair_details, figures[10], "z")
    report_path = write_report(run, manifest, summaries, figures, canonical, warmup_s)
    print(report_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--roi", type=Path)
    parser.add_argument("--warmup-s", type=float, default=0.0, help="Optional post-initialization diagnostic warmup; source/full-run artifacts remain unchanged.")
    parser.add_argument(
        "--display-alignment",
        choices=("START_XY_YAW", "NONE", "start_yaw", "raw"),
        default="START_XY_YAW",
        help="Display/comparison-only transform. start_yaw/raw are deprecated aliases.",
    )
    args = parser.parse_args()
    generate(args.run.resolve(), args.roi, args.display_alignment, args.warmup_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
