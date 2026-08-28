#!/usr/bin/env python3
"""Render phase-aware benchmark figures from metrics/phase_analysis.json only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


FIGURE_NAMES = (
    "phase_timeline.png",
    "trajectory_error_by_phase.png",
    "z_change_by_phase.png",
    "cpu_by_phase.png",
    "rss_growth_by_phase.png",
    "phase_dashboard.png",
)


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("phases"), list):
        raise ValueError(f"invalid phase analysis JSON: {path}")
    return data


def _phase_labels(result: dict[str, Any]) -> list[str]:
    return [f"{phase['id']}\n{phase['state']}" for phase in result["phases"]]


def _series(result: dict[str, Any], section: str, key: str) -> dict[str, list[float]]:
    phase_ids = [phase["id"] for phase in result["phases"]]
    output: dict[str, list[float]] = {}
    for algorithm, item in (result.get("algorithms") or {}).items():
        values: list[float] = []
        for phase_id in phase_ids:
            phase = ((item.get("phases") or {}).get(phase_id) or {}).get(section) or {}
            value = phase.get(key)
            values.append(float(value) if value is not None else float("nan"))
        output[algorithm] = values
    return output


def _save(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _plot_lines(
    result: dict[str, Any],
    key: str,
    ylabel: str,
    title: str,
    path: Path,
    *,
    section: str,
) -> None:
    labels = _phase_labels(result)
    x = np.arange(len(labels), dtype=float)
    fig, ax = plt.subplots(figsize=(max(7.0, len(labels) * 1.3), 4.6))
    plotted = False
    for algorithm, values in _series(result, section, key).items():
        array = np.asarray(values, dtype=float)
        if np.isfinite(array).any():
            ax.plot(x, array, marker="o", label=algorithm)
            plotted = True
    ax.set_xticks(x, labels, rotation=30, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, axis="y", alpha=0.25)
    if plotted:
        ax.legend(fontsize="small")
    else:
        ax.text(0.5, 0.5, "unavailable", transform=ax.transAxes, ha="center", va="center")
    _save(fig, path)


def _timeline(result: dict[str, Any], path: Path) -> None:
    phases = result["phases"]
    fig, ax = plt.subplots(figsize=(10, 2.8))
    for index, phase in enumerate(phases):
        start = float(phase["start_s"])
        duration = float(phase["end_s"]) - start
        ax.barh(0, duration, left=start, height=0.5)
        ax.text(
            start + duration / 2.0,
            0,
            f"{index}\n{phase['state']}",
            ha="center",
            va="center",
            fontsize=8,
        )
    ax.set_yticks([])
    ax.set_xlabel("trajectory/header time (s)")
    ax.set_title(
        f"Phase timeline — baseline {result.get('baseline')} | "
        f"{result.get('time_alignment_mode')}"
    )
    _save(fig, path)


def _dashboard(result: dict[str, Any], path: Path) -> None:
    labels = _phase_labels(result)
    x = np.arange(len(labels), dtype=float)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    specs = [
        ("trajectory", "relative_position_rmse_m", "Relative position RMSE (m)"),
        ("trajectory", "z_change_m", "Z change (m)"),
        ("resource", "cpu_p95_percent", "CPU p95 (%)"),
        ("resource", "rss_growth_mib", "RSS growth (MiB)"),
    ]
    for ax, (section, key, ylabel) in zip(axes.ravel(), specs):
        plotted = False
        for algorithm, values in _series(result, section, key).items():
            array = np.asarray(values, dtype=float)
            if np.isfinite(array).any():
                ax.plot(x, array, marker="o", label=algorithm)
                plotted = True
        ax.set_xticks(x, labels, rotation=35, ha="right")
        ax.set_ylabel(ylabel)
        ax.grid(True, axis="y", alpha=0.25)
        if not plotted:
            ax.text(0.5, 0.5, "unavailable", transform=ax.transAxes, ha="center", va="center")
    handles, legends = axes[0, 0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, legends, loc="upper center", ncol=max(1, min(4, len(handles))))
    fig.suptitle(
        f"Phase-aware diagnostic dashboard — {result.get('metric_class')}\n"
        f"time alignment: {result.get('time_alignment_mode')}",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_phase_analysis(run: Path) -> list[Path]:
    run = Path(run).resolve()
    result = _load(run / "metrics" / "phase_analysis.json")
    output = run / "figures" / "phase_analysis"
    output.mkdir(parents=True, exist_ok=True)
    paths = {name: output / name for name in FIGURE_NAMES}
    _timeline(result, paths["phase_timeline.png"])
    _plot_lines(
        result,
        "relative_position_rmse_m",
        "Relative position RMSE (m)",
        "Trajectory deviation by phase",
        paths["trajectory_error_by_phase.png"],
        section="trajectory",
    )
    _plot_lines(
        result,
        "z_change_m",
        "Z change (m)",
        "Z change by phase",
        paths["z_change_by_phase.png"],
        section="trajectory",
    )
    _plot_lines(
        result,
        "cpu_p95_percent",
        "CPU p95 (%)",
        "CPU load by phase",
        paths["cpu_by_phase.png"],
        section="resource",
    )
    _plot_lines(
        result,
        "rss_growth_mib",
        "RSS growth (MiB)",
        "RSS growth by phase",
        paths["rss_growth_by_phase.png"],
        section="resource",
    )
    _dashboard(result, paths["phase_dashboard.png"])
    return [paths[name] for name in FIGURE_NAMES]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    paths = plot_phase_analysis(args.run)
    print(json.dumps({"figures": [str(path) for path in paths]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
