#!/usr/bin/env python3
"""Audit run-local LiDAR input, adapter boundary, and trajectory cadence."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.cloud_contract import scan_timestamp  # noqa: E402
from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.map_sampling import in_scan_window, resolve_scan_window  # noqa: E402
from benchmark_base.lib.rosbag_trajectory import (  # noqa: E402
    find_bag_for_topic,
    normalize_topic,
    open_reader,
    stamp_seconds,
    topic_map,
)
from benchmark_base.lib.trajectory_coverage import (  # noqa: E402
    coverage_against_input,
    summarize_timestamps,
)


SCHEMA_VERSION = 1
KISS_ADAPTER_TOPIC = "/lio_benchmark/kiss_icp_points"
CSV_FIELDS = (
    "algorithm_id",
    "input_lidar_count",
    "input_lidar_effective_hz",
    "input_lidar_median_period_s",
    "input_lidar_p95_period_s",
    "input_lidar_max_period_s",
    "input_lidar_large_gap_count",
    "adapter_status",
    "adapter_output_count",
    "adapter_output_effective_hz",
    "adapter_output_median_period_s",
    "adapter_output_p95_period_s",
    "adapter_output_max_period_s",
    "adapter_output_large_gap_count",
    "trajectory_count",
    "trajectory_effective_hz",
    "trajectory_median_period_s",
    "trajectory_p95_period_s",
    "trajectory_max_period_s",
    "trajectory_large_gap_count",
    "first_trajectory_lag_from_input_s",
    "last_trajectory_delta_to_input_end_s",
    "trajectory_to_input_count_ratio",
    "adapter_to_input_count_ratio",
    "trajectory_to_adapter_count_ratio",
)


def _source_lidar_timestamps(manifest: dict[str, Any]) -> tuple[float, ...]:
    dataset = manifest.get("dataset", {})
    if not isinstance(dataset, dict):
        raise ValueError("run manifest dataset must be an object")
    bag = Path(str(dataset.get("bag_dir", ""))).expanduser()
    if not bag.is_dir():
        raise ValueError(f"dataset bag directory does not exist: {bag}")
    topics = dataset.get("topics", {})
    topic = topics.get("lidar") if isinstance(topics, dict) else None
    topic = str(topic or dataset.get("lidar_topic", "")).strip()
    if not topic:
        raise ValueError("dataset LiDAR topic is required")

    topic_types = topic_map(bag)
    normalized = normalize_topic(topic)
    if normalized not in topic_types:
        raise ValueError(f"bag missing LiDAR topic {normalized}")
    actual_topic, message_type = topic_types[normalized]
    message_class = get_message(message_type)

    timestamp_contract = dataset.get("timestamp", {})
    timestamp_contract = timestamp_contract if isinstance(timestamp_contract, dict) else {}
    point_time_field = timestamp_contract.get(
        "point_time_field", dataset.get("point_time_field", "timestamp")
    )
    point_time_unit = timestamp_contract.get(
        "point_time_unit", dataset.get("point_time_unit", "ns_absolute")
    )

    replay = manifest.get("replay")
    legacy_replay = manifest.get("replay_window")
    window, _ = resolve_scan_window(
        replay=replay if isinstance(replay, dict) else None,
        legacy_replay_window=legacy_replay if isinstance(legacy_replay, dict) else None,
        start_offset_override=None,
        duration_override=None,
    )

    reader = open_reader(bag)
    first_record_s: float | None = None
    values: list[float] = []
    while reader.has_next():
        name, raw, recorded_ns = reader.read_next()
        if normalize_topic(name) != normalized:
            continue
        record_s = recorded_ns * 1e-9
        if first_record_s is None:
            first_record_s = record_s
        if not in_scan_window(record_s, first_record_s, window):
            continue
        message = deserialize_message(raw, message_class)
        value, _ = scan_timestamp(
            message,
            recorded_ns,
            str(point_time_field or ""),
            str(point_time_unit or "ns_absolute"),
        )
        values.append(float(value))
    if not values:
        raise ValueError(f"no LiDAR messages found in frozen replay window for {actual_topic}")
    return tuple(values)


def _topic_header_timestamps(bag: Path, topic: str, message_type: str) -> tuple[float, ...]:
    message_class = get_message(message_type)
    target = normalize_topic(topic)
    reader = open_reader(bag)
    values: list[float] = []
    while reader.has_next():
        current_topic, raw, recorded_ns = reader.read_next()
        if normalize_topic(current_topic) != target:
            continue
        message = deserialize_message(raw, message_class)
        values.append(stamp_seconds(message, recorded_ns))
    if not values:
        raise ValueError(f"topic {target} has no messages in {bag}")
    return tuple(values)


def _trajectory_timestamps(path: Path) -> tuple[float, ...]:
    if not path.is_file():
        raise ValueError(f"missing standardized trajectory: {path}")
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    values = tuple(float(row["timestamp_s"]) for row in rows)
    if not values:
        raise ValueError(f"standardized trajectory has no samples: {path}")
    return values


def _stats_fields(prefix: str, values: tuple[float, ...]) -> dict[str, Any]:
    stats = summarize_timestamps(values)
    return {
        f"{prefix}_count": stats.count,
        f"{prefix}_effective_hz": stats.effective_hz,
        f"{prefix}_median_period_s": stats.median_period_s,
        f"{prefix}_p95_period_s": stats.p95_period_s,
        f"{prefix}_max_period_s": stats.max_period_s,
        f"{prefix}_large_gap_count": stats.gap_count_over_1p5x_median,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def build_record(
    *,
    run: Path,
    algorithm_id: str,
    input_timestamps: tuple[float, ...],
) -> dict[str, Any]:
    trajectory_timestamps = _trajectory_timestamps(
        run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
    )
    input_stats = summarize_timestamps(input_timestamps)
    trajectory_stats = summarize_timestamps(trajectory_timestamps)
    input_coverage = coverage_against_input(input_timestamps, trajectory_timestamps)

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "algorithm_id": algorithm_id,
        **_stats_fields("input_lidar", input_timestamps),
        "adapter_status": "NOT_APPLICABLE",
        "adapter_output_count": None,
        "adapter_output_effective_hz": None,
        "adapter_output_median_period_s": None,
        "adapter_output_p95_period_s": None,
        "adapter_output_max_period_s": None,
        "adapter_output_large_gap_count": None,
        **_stats_fields("trajectory", trajectory_timestamps),
        "first_trajectory_lag_from_input_s": input_coverage[
            "first_output_lag_from_input_s"
        ],
        "last_trajectory_delta_to_input_end_s": input_coverage[
            "last_output_delta_to_input_end_s"
        ],
        "trajectory_to_input_count_ratio": input_coverage[
            "output_to_input_count_ratio"
        ],
        "adapter_to_input_count_ratio": None,
        "trajectory_to_adapter_count_ratio": None,
    }

    if algorithm_id == "kiss_icp":
        try:
            adapter_bag, actual_topic, message_type = find_bag_for_topic(
                run / "raw" / algorithm_id,
                KISS_ADAPTER_TOPIC,
            )
            adapter_timestamps = _topic_header_timestamps(
                adapter_bag, actual_topic, message_type
            )
        except ValueError as exc:
            record["adapter_status"] = "UNAVAILABLE"
            record["adapter_reason"] = str(exc)
        else:
            adapter_stats = summarize_timestamps(adapter_timestamps)
            adapter_coverage = coverage_against_input(input_timestamps, adapter_timestamps)
            trajectory_adapter_coverage = coverage_against_input(
                adapter_timestamps, trajectory_timestamps
            )
            record.update(_stats_fields("adapter_output", adapter_timestamps))
            record["adapter_status"] = "AVAILABLE"
            record["adapter_bag"] = str(adapter_bag)
            record["adapter_topic"] = normalize_topic(actual_topic)
            record["adapter_message_type"] = message_type
            record["adapter_to_input_count_ratio"] = adapter_coverage[
                "output_to_input_count_ratio"
            ]
            record["trajectory_to_adapter_count_ratio"] = trajectory_adapter_coverage[
                "output_to_input_count_ratio"
            ]

    # Preserve explicit primitive types in the JSON/CSV record.
    for key, value in tuple(record.items()):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"non-finite coverage value for {algorithm_id}: {key}={value}")
    return record


def audit_run(run: Path, algorithms: list[str] | None = None) -> Path:
    run = run.resolve()
    manifest = load_json(run / "manifest.json")
    selected_algorithms = manifest.get("algorithms", {})
    if not isinstance(selected_algorithms, dict):
        raise ValueError("frozen run algorithms must be an object")
    selected = algorithms or list(selected_algorithms)
    unknown = [value for value in selected if value not in selected_algorithms]
    if unknown:
        raise ValueError(f"algorithms are not selected in frozen run: {unknown}")

    input_timestamps = _source_lidar_timestamps(manifest)
    records = [
        build_record(run=run, algorithm_id=algorithm_id, input_timestamps=input_timestamps)
        for algorithm_id in selected
    ]

    metadata_root = run / "metadata" / "trajectory_coverage"
    metadata_root.mkdir(parents=True, exist_ok=True)
    for record in records:
        path = metadata_root / f"{record['algorithm_id']}.json"
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    output = run / "metrics" / "trajectory_coverage.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithms", nargs="+")
    args = parser.parse_args()
    print(audit_run(args.run, args.algorithms))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
