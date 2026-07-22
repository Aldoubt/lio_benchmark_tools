#!/usr/bin/env python3
"""Plot full-run CPU, RSS, thread and disk-write time series."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


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


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def output_directory(run: Path, algorithm: str, entry: dict[str, Any]) -> Path:
    result = entry.get("result") or {}
    configured = result.get("output_dir") or entry.get("output_dir")
    if configured:
        candidate = Path(configured)
        if candidate.is_dir():
            return candidate
    return run / "raw" / algorithm


def samples_for(path: Path) -> list[dict[str, float]]:
    data = load_json(path)
    history = data.get("sample_history")
    if not isinstance(history, list):
        latest = data.get("latest")
        history = [latest] if isinstance(latest, dict) else []
    samples: list[dict[str, float]] = []
    for item in history:
        if not isinstance(item, dict) or item.get("elapsed_s") is None:
            continue
        samples.append({
            "elapsed_s": float(item.get("elapsed_s", 0.0)),
            "cpu_percent": float(item.get("cpu_percent", 0.0) or 0.0),
            "rss_mib": float(item.get("rss_bytes", 0.0) or 0.0) / (1024.0 ** 2),
            "threads": float(item.get("threads", 0.0) or 0.0),
            "write_mib": float(item.get("write_bytes", 0.0) or 0.0) / (1024.0 ** 2),
        })
    return samples


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        fields = ("algorithm", "label", "elapsed_s", "cpu_percent", "rss_mib", "threads", "write_mib")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def plot_curves(path: Path, series: dict[str, list[dict[str, float]]]) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(14, 13), sharex=True, constrained_layout=True)
    colors = plt.get_cmap("tab10")
    for index, (algorithm, samples) in enumerate(series.items()):
        if not samples:
            continue
        color = colors(index % 10)
        times = [item["elapsed_s"] for item in samples]
        axes[0].plot(times, [item["cpu_percent"] for item in samples], label=LABELS.get(algorithm, algorithm), color=color, linewidth=1.0)
        axes[1].plot(times, [item["rss_mib"] for item in samples], label=LABELS.get(algorithm, algorithm), color=color, linewidth=1.0)
        axes[2].plot(times, [item["threads"] for item in samples], label=LABELS.get(algorithm, algorithm), color=color, linewidth=1.0)
    axes[0].set_ylabel("CPU (%)")
    axes[1].set_ylabel("RSS (MiB)")
    axes[2].set_ylabel("Threads")
    axes[2].set_xlabel("Elapsed algorithm time (s)")
    axes[0].set_title("Algorithm process-tree resource curves")
    for axis in axes:
        axis.grid(alpha=0.25)
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=5, bbox_to_anchor=(0.5, 1.02), fontsize=9)
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def plot_summary(path: Path, summary: list[dict[str, Any]]) -> None:
    valid = [item for item in summary if item.get("sample_count", 0) > 0]
    labels = [item["label"] for item in valid]
    positions = list(range(len(labels)))
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), constrained_layout=True)
    axes[0].bar(positions, [item["mean_cpu_percent"] for item in valid], label="Mean CPU")
    axes[0].bar(positions, [item["peak_cpu_percent"] for item in valid], alpha=0.45, label="Peak CPU")
    axes[0].set_ylabel("CPU (%)")
    axes[1].bar(positions, [item["peak_rss_mib"] for item in valid], color="#d95f02")
    axes[1].set_ylabel("Peak RSS (MiB)")
    axes[2].bar(positions, [item["peak_threads"] for item in valid], color="#1b9e77")
    axes[2].set_ylabel("Peak threads")
    axes[2].set_xticks(positions, labels, rotation=35, ha="right")
    axes[0].legend()
    for axis in axes:
        axis.grid(axis="y", alpha=0.25)
    fig.suptitle("Resource summary")
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    output = (args.output_dir or run / "figures" / "resource_curves").resolve()
    output.mkdir(parents=True, exist_ok=True)
    status = load_json(run / "metadata" / "run_status.json")
    series: dict[str, list[dict[str, float]]] = {}
    summary: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for algorithm, entry in (status.get("algorithms") or {}).items():
        resource_path = output_directory(run, algorithm, entry) / "resource_monitor.json"
        samples = samples_for(resource_path)
        series[algorithm] = samples
        for sample in samples:
            rows.append({"algorithm": algorithm, "label": LABELS.get(algorithm, algorithm), **sample})
        resource = load_json(resource_path)
        summary.append({
            "algorithm": algorithm,
            "label": LABELS.get(algorithm, algorithm),
            "status": (entry.get("result") or {}).get("status"),
            "sample_count": len(samples),
            "duration_s": float(resource.get("wall_time_s", 0.0) or 0.0),
            "mean_cpu_percent": float(resource.get("mean_cpu_percent", 0.0) or 0.0),
            "peak_cpu_percent": float(resource.get("peak_cpu_percent", 0.0) or 0.0),
            "mean_rss_mib": float(resource.get("mean_rss_bytes", 0.0) or 0.0) / (1024.0 ** 2),
            "peak_rss_mib": float(resource.get("peak_rss_bytes", 0.0) or 0.0) / (1024.0 ** 2),
            "peak_threads": int(resource.get("peak_threads", 0) or 0),
            "resource_file": str(resource_path),
        })
    write_csv(output / "resource_timeseries.csv", rows)
    (output / "resource_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "resource_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = tuple(summary[0].keys()) if summary else ("algorithm", "label", "status", "sample_count")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary)
    plot_curves(output / "resource_curves.png", series)
    plot_summary(output / "resource_summary.png", summary)
    (output / "README.md").write_text(
        "# Resource curves\n\n"
        "CPU is the logical CPU sum of the algorithm process tree; 100% is one logical core. "
        "RSS is the process-tree resident set size. Samples are recorded at the manifest or environment interval.\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "algorithms": len(series), "samples": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
