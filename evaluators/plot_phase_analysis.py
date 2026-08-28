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


EDGE_STATIC_STATES = {"PRE_MOTION_STATIC", "POST_MOTION_STATIC"}
BASE_FIGURE_NAMES = (
    "phase_timeline.png",
    "trajectory_error_by_phase.png",
    "trajectory_error_by_phase_all.png",
    "z_change_by_phase.png",
    "z_change_by_phase_all.png",
    "phase_dashboard.png",
)
RESOURCE_FIGURE_NAMES = ("cpu_by_phase.png", "rss_growth_by_phase.png")


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("phases"), list):
        raise ValueError(f"invalid phase analysis JSON: {path}")
    return data


def _phase_lookup(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(phase["id"]): phase for phase in result["phases"]}


def _phase_labels(result: dict[str, Any], phase_ids: list[str] | None = None) -> list[str]:
    lookup = _phase_lookup(result)
    ids = phase_ids or [str(phase["id"]) for phase in result["phases"]]
    return [f"{phase_id}\n{lookup[phase_id]['state']}" for phase_id in ids]


def _motion_phase_ids(result: dict[str, Any]) -> list[str]:
    """Return analysis phases, excluding only long static edges of the run."""
    return [
        str(phase["id"])
        for phase in result["phases"]
        if str(phase.get("state")) not in EDGE_STATIC_STATES
    ]


def _selected_algorithms(result: dict[str, Any]) -> list[str]:
    """Health-valid algorithms used by primary figures."""
    return [
        name
        for name, item in (result.get("algorithms") or {}).items()
        if bool(item.get("selection_eligible"))
    ]


def _series(
    result: dict[str, Any],
    section: str,
    key: str,
    *,
    algorithms: list[str] | None = None,
    phase_ids: list[str] | None = None,
) -> dict[str, list[float]]:
    ids = phase_ids or [str(phase["id"]) for phase in result["phases"]]
    names = algorithms or list((result.get("algorithms") or {}).keys())
    output: dict[str, list[float]] = {}
    for algorithm in names:
        item = (result.get("algorithms") or {}).get(algorithm) or {}
        values: list[float] = []
        for phase_id in ids:
            phase = ((item.get("phases") or {}).get(phase_id) or {}).get(section) or {}
            value = phase.get(key)
            values.append(float(value) if value is not None else float("nan"))
        output[algorithm] = values
    return output


def _resource_available(result: dict[str, Any], algorithms: list[str] | None = None) -> bool:
    phase_ids = _motion_phase_ids(result)
    for key in ("cpu_p95_percent", "rss_growth_mib"):
        for values in _series(
            result,
            "resource",
            key,
            algorithms=algorithms,
            phase_ids=phase_ids,
        ).values():
            if np.isfinite(np.asarray(values, dtype=float)).any():
                return True
    return False


def _resource_unavailable_message(result: dict[str, Any]) -> str:
    mode = str(result.get("time_alignment_mode") or "unknown")
    if mode == "trajectory-only":
        detail = next(
            (
                str(item)
                for item in result.get("warnings") or []
                if "recorded/header" in str(item) or "resource" in str(item)
            ),
            "missing strict/approximate resource timing evidence",
        )
        return f"resource unavailable\n{mode}\n{detail}"
    return "resource unavailable"


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
    algorithms: list[str] | None = None,
    phase_ids: list[str] | None = None,
    unavailable_text: str = "unavailable",
) -> None:
    ids = phase_ids or [str(phase["id"]) for phase in result["phases"]]
    labels = _phase_labels(result, ids)
    x = np.arange(len(labels), dtype=float)
    fig, ax = plt.subplots(figsize=(max(7.0, len(labels) * 1.3), 4.6))
    plotted = False
    for algorithm, values in _series(
        result,
        section,
        key,
        algorithms=algorithms,
        phase_ids=ids,
    ).items():
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
        ax.text(0.5, 0.5, unavailable_text, transform=ax.transAxes, ha="center", va="center")
    _save(fig, path)


def _timeline(result: dict[str, Any], path: Path) -> None:
    phases = result["phases"]
    fig, ax = plt.subplots(figsize=(10, 2.8))
    if not phases:
        ax.text(0.5, 0.5, "no phases", transform=ax.transAxes, ha="center", va="center")
    else:
        origin = float(phases[0]["start_s"])
        for index, phase in enumerate(phases):
            start = float(phase["start_s"]) - origin
            duration = float(phase["end_s"]) - float(phase["start_s"])
            ax.barh(0, duration, left=start, height=0.5)
            ax.text(
                start + duration / 2.0,
                0,
                f"{index}\n{phase['state']}",
                ha="center",
                va="center",
                fontsize=8,
            )
        ax.set_xlabel(f"trajectory/header time from first phase (s); start={origin:.3f}")
    ax.set_yticks([])
    ax.set_title(
        f"Phase timeline — baseline {result.get('baseline')} | "
        f"{result.get('time_alignment_mode')}"
    )
    _save(fig, path)


def _dashboard(result: dict[str, Any], path: Path) -> None:
    phase_ids = _motion_phase_ids(result)
    algorithms = _selected_algorithms(result)
    labels = _phase_labels(result, phase_ids)
    x = np.arange(len(labels), dtype=float)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    specs = [
        ("trajectory", "relative_position_rmse_m", "Relative position RMSE (m)"),
        ("trajectory", "z_change_m", "Z change (m)"),
        ("resource", "cpu_p95_percent", "CPU p95 (%)"),
        ("resource", "rss_growth_mib", "RSS growth (MiB)"),
    ]
    resource_message = _resource_unavailable_message(result)
    for ax, (section, key, ylabel) in zip(axes.ravel(), specs):
        plotted = False
        for algorithm, values in _series(
            result,
            section,
            key,
            algorithms=algorithms,
            phase_ids=phase_ids,
        ).items():
            array = np.asarray(values, dtype=float)
            if np.isfinite(array).any():
                ax.plot(x, array, marker="o", label=algorithm)
                plotted = True
        ax.set_xticks(x, labels, rotation=35, ha="right")
        ax.set_ylabel(ylabel)
        ax.grid(True, axis="y", alpha=0.25)
        if not plotted:
            text = resource_message if section == "resource" else "unavailable"
            ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center", fontsize=8)
    handles, legends = axes[0, 0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, legends, loc="upper center", ncol=max(1, min(4, len(handles))))
    fig.suptitle(
        f"Phase-aware diagnostic dashboard — health-valid algorithms\n"
        f"{result.get('metric_class')} | time alignment: {result.get('time_alignment_mode')}",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _remove_stale(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def plot_phase_analysis(run: Path) -> list[Path]:
    run = Path(run).resolve()
    result = _load(run / "metrics" / "phase_analysis.json")
    output = run / "figures" / "phase_analysis"
    output.mkdir(parents=True, exist_ok=True)

    paths = {name: output / name for name in (*BASE_FIGURE_NAMES, *RESOURCE_FIGURE_NAMES)}
    selected = _selected_algorithms(result)
    analysis_phase_ids = _motion_phase_ids(result)
    all_phase_ids = [str(phase["id"]) for phase in result["phases"]]

    _timeline(result, paths["phase_timeline.png"])
    _plot_lines(
        result,
        "relative_position_rmse_m",
        "Relative position RMSE (m)",
        "Trajectory deviation by phase — health-valid algorithms",
        paths["trajectory_error_by_phase.png"],
        section="trajectory",
        algorithms=selected,
        phase_ids=analysis_phase_ids,
    )
    _plot_lines(
        result,
        "relative_position_rmse_m",
        "Relative position RMSE (m)",
        "Trajectory deviation by phase — all algorithms / failure diagnostic",
        paths["trajectory_error_by_phase_all.png"],
        section="trajectory",
        phase_ids=all_phase_ids,
    )
    _plot_lines(
        result,
        "z_change_m",
        "Z change (m)",
        "Z change by phase — health-valid algorithms",
        paths["z_change_by_phase.png"],
        section="trajectory",
        algorithms=selected,
        phase_ids=analysis_phase_ids,
    )
    _plot_lines(
        result,
        "z_change_m",
        "Z change (m)",
        "Z change by phase — all algorithms / failure diagnostic",
        paths["z_change_by_phase_all.png"],
        section="trajectory",
        phase_ids=all_phase_ids,
    )

    produced = [
        paths["phase_timeline.png"],
        paths["trajectory_error_by_phase.png"],
        paths["trajectory_error_by_phase_all.png"],
        paths["z_change_by_phase.png"],
        paths["z_change_by_phase_all.png"],
    ]
    if _resource_available(result, selected):
        _plot_lines(
            result,
            "cpu_p95_percent",
            "CPU p95 (%)",
            "CPU load by phase — health-valid algorithms",
            paths["cpu_by_phase.png"],
            section="resource",
            algorithms=selected,
            phase_ids=analysis_phase_ids,
        )
        _plot_lines(
            result,
            "rss_growth_mib",
            "RSS growth (MiB)",
            "RSS growth by phase — health-valid algorithms",
            paths["rss_growth_by_phase.png"],
            section="resource",
            algorithms=selected,
            phase_ids=analysis_phase_ids,
        )
        produced.extend([paths["cpu_by_phase.png"], paths["rss_growth_by_phase.png"]])
    else:
        _remove_stale(paths["cpu_by_phase.png"])
        _remove_stale(paths["rss_growth_by_phase.png"])

    _dashboard(result, paths["phase_dashboard.png"])
    produced.append(paths["phase_dashboard.png"])
    return produced


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    paths = plot_phase_analysis(args.run)
    print(json.dumps({"figures": [str(path) for path in paths]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
