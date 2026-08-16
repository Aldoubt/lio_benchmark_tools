#!/usr/bin/env python3
"""Audit raw ROS2 trajectory frame semantics against standardized trajectories.

This tool is read-only. It never rewrites a raw bag, standardized trajectory,
map, or display-alignment artifact.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.frame_audit import RawPoseObservation, build_frame_audit  # noqa: E402
from benchmark_base.lib.trajectory import Trajectory  # noqa: E402


def normalize_topic(value: str) -> str:
    value = str(value).strip()
    if not value:
        return ""
    return "/" + value.lstrip("/")


def storage_identifier(bag: Path) -> str:
    metadata = bag / "metadata.yaml"
    if not metadata.is_file():
        raise ValueError(f"not a rosbag2 directory: {bag}")
    text = metadata.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^\s*storage_identifier:\s*([^\s#]+)", text, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    if any(bag.glob("*.db3")):
        return "sqlite3"
    if any(bag.glob("*.mcap")):
        return "mcap"
    raise ValueError(f"unable to determine rosbag2 storage identifier: {bag}")


def open_reader(bag: Path) -> rosbag2_py.SequentialReader:
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id=storage_identifier(bag)),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    return reader


def topic_map(bag: Path) -> dict[str, tuple[str, str]]:
    reader = open_reader(bag)
    return {
        normalize_topic(item.name): (item.name, item.type)
        for item in reader.get_all_topics_and_types()
    }


def find_bag_for_topic(raw_dir: Path, declared_topic: str) -> tuple[Path, str, str]:
    target = normalize_topic(declared_topic)
    if not target:
        raise ValueError("trajectory topic is not declared")
    matches: list[tuple[Path, str, str]] = []
    if raw_dir.is_dir():
        for metadata in sorted(raw_dir.rglob("metadata.yaml")):
            bag = metadata.parent
            try:
                topics = topic_map(bag)
            except Exception:
                continue
            if target in topics:
                actual_topic, message_type = topics[target]
                matches.append((bag, actual_topic, message_type))
    if not matches:
        raise ValueError(f"no raw rosbag under {raw_dir} contains trajectory topic {target}")
    if len(matches) > 1:
        options = ", ".join(str(item[0]) for item in matches)
        raise ValueError(f"multiple raw rosbags contain trajectory topic {target}: {options}")
    return matches[0]


def stamp_seconds(message: Any, recorded_ns: int) -> float:
    if hasattr(message, "header") and hasattr(message.header, "stamp"):
        stamp = message.header.stamp
        value = float(stamp.sec) + float(stamp.nanosec) * 1e-9
        if value != 0.0:
            return value
    return recorded_ns * 1e-9


def pose_fields(message: Any, message_type: str) -> tuple[str, str, Any]:
    if message_type == "nav_msgs/msg/Odometry":
        return str(message.header.frame_id), str(message.child_frame_id), message.pose.pose
    if message_type == "geometry_msgs/msg/PoseStamped":
        return str(message.header.frame_id), "", message.pose
    if message_type == "geometry_msgs/msg/PoseWithCovarianceStamped":
        return str(message.header.frame_id), "", message.pose.pose
    raise ValueError(f"unsupported trajectory message type for frame audit: {message_type}")


def read_observations(bag: Path, topic: str, message_type: str) -> tuple[RawPoseObservation, ...]:
    message_class = get_message(message_type)
    target = normalize_topic(topic)
    reader = open_reader(bag)
    rows: list[RawPoseObservation] = []
    while reader.has_next():
        current_topic, raw, recorded_ns = reader.read_next()
        if normalize_topic(current_topic) != target:
            continue
        message = deserialize_message(raw, message_class)
        parent, child, pose = pose_fields(message, message_type)
        rows.append(
            RawPoseObservation(
                timestamp_s=stamp_seconds(message, recorded_ns),
                parent_frame_id=parent,
                child_frame_id=child,
                x_m=float(pose.position.x),
                y_m=float(pose.position.y),
                z_m=float(pose.position.z),
                qx=float(pose.orientation.x),
                qy=float(pose.orientation.y),
                qz=float(pose.orientation.z),
                qw=float(pose.orientation.w),
            )
        )
    if not rows:
        raise ValueError(f"trajectory topic {target} has no readable pose messages in {bag}")
    return tuple(rows)


def declared_semantics(algorithm: dict[str, Any]) -> tuple[str, str]:
    value = algorithm.get("trajectory_semantics", {})
    if not isinstance(value, dict):
        return "UNKNOWN", "UNKNOWN"
    return (
        str(value.get("pose_represents", "UNKNOWN")) or "UNKNOWN",
        str(value.get("world_frame_semantics", "UNKNOWN")) or "UNKNOWN",
    )


def trajectory_topic(algorithm: dict[str, Any]) -> str:
    topics = algorithm.get("topics", {})
    outputs = topics.get("outputs", {}) if isinstance(topics, dict) else {}
    value = outputs.get("trajectory", "") if isinstance(outputs, dict) else ""
    return str(value)


def standardized_first(run: Path, algorithm_id: str):
    path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
    if not path.is_file():
        return None
    return Trajectory.from_csv(path).samples[0]


def _csv_value(value: Any) -> Any:
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    return value


def audit_algorithm(run: Path, manifest: dict[str, Any], algorithm_id: str) -> dict[str, Any]:
    algorithm = manifest.get("algorithms", {}).get(algorithm_id)
    if not isinstance(algorithm, dict):
        raise ValueError(f"algorithm is not selected in run: {algorithm_id}")
    source_topic = trajectory_topic(algorithm)
    raw_dir = run / "raw" / algorithm_id
    bag, actual_topic, message_type = find_bag_for_topic(raw_dir, source_topic)
    observations = read_observations(bag, actual_topic, message_type)
    pose_represents, world_semantics = declared_semantics(algorithm)
    audit = build_frame_audit(
        algorithm_id=algorithm_id,
        source_topic=normalize_topic(actual_topic),
        message_type=message_type,
        raw_bag=str(bag),
        observations=observations,
        standardized_first=standardized_first(run, algorithm_id),
        declared_pose_represents=pose_represents,
        declared_world_frame_semantics=world_semantics,
    )
    return audit.to_dict()


def write_outputs(run: Path, rows: list[dict[str, Any]]) -> Path:
    output_dir = run / "metadata" / "frame_audit"
    output_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        algorithm_id = str(row["algorithm_id"])
        (output_dir / f"{algorithm_id}.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    csv_path = run / "metrics" / "trajectory_frame_audit.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key, "")) for key in fieldnames})
    return csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithms", nargs="+")
    args = parser.parse_args()

    run = args.run.resolve()
    manifest_path = run / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"missing run manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = args.algorithms or list(manifest.get("algorithms", {}))
    rows: list[dict[str, Any]] = []
    failed = False
    for algorithm_id in selected:
        try:
            row = audit_algorithm(run, manifest, algorithm_id)
        except Exception as exc:
            failed = True
            algorithm = manifest.get("algorithms", {}).get(algorithm_id, {})
            rows.append(
                {
                    "algorithm_id": algorithm_id,
                    "status": "AUDIT_FAILED",
                    "source_topic": trajectory_topic(algorithm) if isinstance(algorithm, dict) else "",
                    "error": str(exc),
                }
            )
        else:
            row["error"] = ""
            rows.append(row)

    csv_path = write_outputs(run, rows)
    print(csv_path)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
