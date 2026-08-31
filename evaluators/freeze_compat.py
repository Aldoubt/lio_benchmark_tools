from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from diagnostic_timeline import (
    DEFAULT_RESAMPLE_HZ,
    DEFAULT_RESOURCE_MAX_AGE_S,
    DEFAULT_WINDOW_CONTEXT_S,
    DEFAULT_WINDOW_GAP_S,
    METRIC_CLASS,
    cluster_anomaly_windows,
    detect_resampled_events,
    resample_fixed_rate,
)
from plot_comparison_dashboard import load_trajectory
from trajectory_discontinuity import resolve_time_origin

TIMELINE_FIELDS = [
    "timestamp_s",
    "bag_time_s",
    "x_m",
    "y_m",
    "z_m",
    "yaw_rad",
    "delta_position_m",
    "delta_yaw_deg",
    "speed_mps",
    "yaw_rate_deg_s",
    "acceleration_mps2",
    "resource_alignment_mode",
    "resource_age_s",
    "cpu_percent",
    "rss_mib",
    "threads",
    "write_bytes",
    "anomaly_window_ids",
    "anomaly_types",
]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=TIMELINE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in TIMELINE_FIELDS})


def _tag_windows(
    rows: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    algorithm: str,
) -> None:
    selected = [item for item in windows if item.get("algorithm") == algorithm]
    for row in rows:
        bag_time = float(row["bag_time_s"])
        active = [
            item
            for item in selected
            if float(item["start_bag_time_s"]) - 1e-9
            <= bag_time
            <= float(item["end_bag_time_s"]) + 1e-9
        ]
        row["anomaly_window_ids"] = ";".join(
            str(item["window_id"]) for item in active
        )
        row["anomaly_types"] = ";".join(
            sorted({str(value) for item in active for value in item.get("types", [])})
        )


def build_compat_diagnostic_timeline(
    source: Path,
    *,
    algorithms: list[str],
    baseline: str,
    hz: float = DEFAULT_RESAMPLE_HZ,
) -> dict[str, Any]:
    """Build the modern trajectory-only diagnostic layer inside a frozen source copy.

    This compatibility path never reads or writes the original run directory. It
    deterministically derives the fixed-rate trajectory/anomaly timeline from the
    already-captured standardized trajectories. Resource alignment is deliberately
    omitted rather than guessed; map/pointcloud evidence is handled separately.
    """
    source = Path(source).resolve()
    algorithms = [str(item) for item in algorithms]
    if not algorithms:
        raise ValueError("compatibility timeline requires at least one algorithm")
    if baseline not in algorithms:
        raise ValueError(f"compatibility timeline baseline is unavailable: {baseline}")
    if hz <= 0:
        raise ValueError("compatibility timeline rate must be > 0")

    trajectory_dir = source / "standardized" / "trajectories"
    trajectories = {
        algorithm: load_trajectory(trajectory_dir / f"{algorithm}.csv")
        for algorithm in algorithms
    }
    origin_timestamp_s, origin_source = resolve_time_origin(
        source, trajectories[baseline]
    )

    rows_by_algorithm: dict[str, list[dict[str, Any]]] = {}
    algorithm_metadata: dict[str, dict[str, Any]] = {}
    all_events: list[dict[str, Any]] = []

    for algorithm in algorithms:
        rows = resample_fixed_rate(
            trajectories[algorithm],
            origin_timestamp_s,
            hz=hz,
        )
        events, thresholds = detect_resampled_events(algorithm, rows)
        all_events.extend(events)
        for row in rows:
            row.update(
                {
                    "resource_alignment_mode": "unavailable",
                    "resource_age_s": None,
                    "cpu_percent": None,
                    "rss_mib": None,
                    "threads": None,
                    "write_bytes": None,
                }
            )
        rows_by_algorithm[algorithm] = rows
        algorithm_metadata[algorithm] = {
            "timeline_samples": len(rows),
            "event_count": len(events),
            "position_jump_count": sum(
                item.get("type") == "position_jump" for item in events
            ),
            "yaw_jump_count": sum(item.get("type") == "yaw_jump" for item in events),
            **thresholds,
            "resource_alignment_mode": "unavailable",
            "resource_samples": 0,
            "resource_warnings": [
                "compatibility timeline rebuilt from standardized trajectories; resource alignment unavailable"
            ],
            "resource_alignment_evidence": {},
        }

    all_events.sort(
        key=lambda item: (
            float(item.get("bag_time_s") or 0.0),
            str(item.get("algorithm") or ""),
            str(item.get("type") or ""),
        )
    )
    windows = cluster_anomaly_windows(
        all_events,
        max_gap_s=DEFAULT_WINDOW_GAP_S,
        context_s=DEFAULT_WINDOW_CONTEXT_S,
    )
    for algorithm, rows in rows_by_algorithm.items():
        _tag_windows(rows, windows, algorithm)
        algorithm_metadata[algorithm]["window_count"] = sum(
            item.get("algorithm") == algorithm for item in windows
        )

    payload = {
        "schema_version": 1,
        "metric_class": METRIC_CLASS,
        "baseline": baseline,
        "origin_timestamp_s": origin_timestamp_s,
        "origin_source": origin_source,
        "resample_hz": float(hz),
        "window_policy": {
            "max_gap_s": DEFAULT_WINDOW_GAP_S,
            "context_s": DEFAULT_WINDOW_CONTEXT_S,
        },
        "resource_max_age_s": DEFAULT_RESOURCE_MAX_AGE_S,
        "algorithm_order": algorithms,
        "algorithms": algorithm_metadata,
        "events": all_events,
        "anomaly_windows": windows,
        "compatibility_derivation": {
            "derived": True,
            "method": "standardized-trajectories-fixed-rate-v1",
            "resource_alignment_reconstructed": False,
            "source_scope": "frozen/source standardized trajectories only",
        },
    }

    metrics_dir = source / "metrics"
    timeline_dir = metrics_dir / "diagnostic_timeline"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    timeline_dir.mkdir(parents=True, exist_ok=True)
    json_path = metrics_dir / "diagnostic_timeline.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    artifacts = ["metrics/diagnostic_timeline.json"]
    for algorithm in algorithms:
        relative = f"metrics/diagnostic_timeline/{algorithm}.csv"
        _write_csv(source / relative, rows_by_algorithm[algorithm])
        artifacts.append(relative)

    return {
        "derived": True,
        "method": "standardized-trajectories-fixed-rate-v1",
        "artifacts": artifacts,
        "algorithm_order": algorithms,
        "origin_timestamp_s": origin_timestamp_s,
        "origin_source": origin_source,
        "resample_hz": float(hz),
        "anomaly_windows": len(windows),
    }
