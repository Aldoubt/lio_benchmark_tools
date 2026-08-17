#!/usr/bin/env python3
"""Audit raw run-local trajectory timestamp domains without repairing samples."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.rosbag_trajectory import (  # noqa: E402
    SUPPORTED_POSE_MESSAGE_TYPES,
    find_bag_for_topic,
    normalize_topic,
    open_reader,
    pose_fields,
    timestamp_components,
)
from benchmark_base.lib.trajectory_from_run import trajectory_topic_from_algorithm  # noqa: E402
from benchmark_base.lib.trajectory_timestamp_audit import (  # noqa: E402
    TimestampAuditSample,
    summarize_timestamp_samples,
)


CSV_FIELDS = (
    "index",
    "bag_record_timestamp_s",
    "header_timestamp_s",
    "effective_timestamp_s",
    "effective_source",
    "bag_record_delta_s",
    "header_delta_s",
    "effective_delta_s",
    "effective_relation",
    "translation_step_m",
    "rotation_step_deg",
)


def _rotation_step_deg(left: TimestampAuditSample, right: TimestampAuditSample) -> float:
    qa = (left.qx, left.qy, left.qz, left.qw)
    qb = (right.qx, right.qy, right.qz, right.qw)
    na = math.sqrt(sum(value * value for value in qa))
    nb = math.sqrt(sum(value * value for value in qb))
    if na <= 1e-15 or nb <= 1e-15:
        return float("nan")
    dot = abs(sum(a * b for a, b in zip(qa, qb)) / (na * nb))
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(2.0 * math.acos(dot))


def _rows(samples: tuple[TimestampAuditSample, ...]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, sample in enumerate(samples):
        if index == 0:
            rows.append(
                {
                    "index": sample.index,
                    "bag_record_timestamp_s": sample.bag_record_timestamp_s,
                    "header_timestamp_s": "" if sample.header_timestamp_s is None else sample.header_timestamp_s,
                    "effective_timestamp_s": sample.effective_timestamp_s,
                    "effective_source": sample.effective_source,
                    "bag_record_delta_s": "",
                    "header_delta_s": "",
                    "effective_delta_s": "",
                    "effective_relation": "FIRST",
                    "translation_step_m": "",
                    "rotation_step_deg": "",
                }
            )
            continue
        previous = samples[index - 1]
        effective_delta = sample.effective_timestamp_s - previous.effective_timestamp_s
        if effective_delta > 0.0:
            relation = "INCREASING"
        elif effective_delta == 0.0:
            relation = "DUPLICATE"
        else:
            relation = "REGRESSION"
        header_delta: float | str = ""
        if previous.header_timestamp_s is not None and sample.header_timestamp_s is not None:
            header_delta = sample.header_timestamp_s - previous.header_timestamp_s
        translation_step_m = math.sqrt(
            (sample.x_m - previous.x_m) ** 2
            + (sample.y_m - previous.y_m) ** 2
            + (sample.z_m - previous.z_m) ** 2
        )
        rows.append(
            {
                "index": sample.index,
                "bag_record_timestamp_s": sample.bag_record_timestamp_s,
                "header_timestamp_s": "" if sample.header_timestamp_s is None else sample.header_timestamp_s,
                "effective_timestamp_s": sample.effective_timestamp_s,
                "effective_source": sample.effective_source,
                "bag_record_delta_s": sample.bag_record_timestamp_s - previous.bag_record_timestamp_s,
                "header_delta_s": header_delta,
                "effective_delta_s": effective_delta,
                "effective_relation": relation,
                "translation_step_m": translation_step_m,
                "rotation_step_deg": _rotation_step_deg(previous, sample),
            }
        )
    return rows


def _read_samples(bag: Path, topic: str, message_type: str) -> tuple[TimestampAuditSample, ...]:
    if message_type not in SUPPORTED_POSE_MESSAGE_TYPES:
        raise ValueError(f"unsupported trajectory message type: {message_type}")
    target = normalize_topic(topic)
    message_class = get_message(message_type)
    reader = open_reader(bag)
    samples: list[TimestampAuditSample] = []
    while reader.has_next():
        current_topic, raw, recorded_ns = reader.read_next()
        if normalize_topic(current_topic) != target:
            continue
        message = deserialize_message(raw, message_class)
        _, _, pose = pose_fields(message, message_type)
        bag_record_timestamp_s, header_timestamp_s, effective_timestamp_s, source = (
            timestamp_components(message, recorded_ns)
        )
        samples.append(
            TimestampAuditSample(
                index=len(samples),
                bag_record_timestamp_s=bag_record_timestamp_s,
                header_timestamp_s=header_timestamp_s,
                effective_timestamp_s=effective_timestamp_s,
                effective_source=source,
                x_m=float(pose.position.x),
                y_m=float(pose.position.y),
                z_m=float(pose.position.z),
                qx=float(pose.orientation.x),
                qy=float(pose.orientation.y),
                qz=float(pose.orientation.z),
                qw=float(pose.orientation.w),
            )
        )
    if not samples:
        raise ValueError(f"trajectory topic {target} has no readable pose messages in {bag}")
    return tuple(samples)


def _audit_algorithm(run: Path, manifest: dict, algorithm_id: str) -> dict[str, object]:
    algorithms = manifest.get("algorithms", {})
    algorithm = algorithms.get(algorithm_id) if isinstance(algorithms, dict) else None
    if not isinstance(algorithm, dict):
        raise ValueError(f"algorithm is not selected in frozen run: {algorithm_id}")
    declared_topic = trajectory_topic_from_algorithm(algorithm)
    bag, actual_topic, message_type = find_bag_for_topic(run / "raw" / algorithm_id, declared_topic)
    samples = _read_samples(bag, actual_topic, message_type)
    summary = summarize_timestamp_samples(samples)
    rows = _rows(samples)

    metrics_dir = run / "metrics" / "trajectory_timestamp_audit"
    metadata_dir = run / "metadata" / "trajectory_timestamp_audit"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    csv_path = metrics_dir / f"{algorithm_id}.csv"
    metadata_path = metadata_dir / f"{algorithm_id}.json"

    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    offending = [row for row in rows if row["effective_relation"] in {"DUPLICATE", "REGRESSION"}]
    payload: dict[str, object] = {
        "schema_version": 1,
        "algorithm_id": algorithm_id,
        "source_bag": str(bag),
        "source_topic": normalize_topic(actual_topic),
        "source_message_type": message_type,
        "timestamp_policy": "HEADER_STAMP_ELSE_BAG_RECORD_TIME",
        "repair_applied": False,
        "samples_sorted": False,
        "samples_dropped": 0,
        "summary": summary,
        "offending_transition_count": len(offending),
        "first_offending_transitions": offending[:20],
        "csv": csv_path.relative_to(run).as_posix(),
    }
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{algorithm_id}: classification={summary['classification']} "
        f"samples={summary['sample_count']} "
        f"duplicates={summary['effective_duplicate_count']} "
        f"regressions={summary['effective_regression_count']}"
    )
    print(metadata_path)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithms", nargs="+", required=True)
    args = parser.parse_args()

    run = args.run.resolve()
    manifest_path = run / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"missing run manifest: {manifest_path}")
    manifest = load_json(manifest_path)
    try:
        for algorithm_id in args.algorithms:
            _audit_algorithm(run, manifest, str(algorithm_id))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
