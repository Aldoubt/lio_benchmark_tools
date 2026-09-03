#!/usr/bin/env python3
"""Index raw LiDAR bag frames without copying point-cloud payloads.

The index lets an offline viewer seek from a bag-relative timestamp to the exact
rosbag2 message id and its recorded/header timestamps. Message payloads remain
in the original sqlite bag and are loaded on demand.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA_VERSION = 1


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def frame_index_row(
    *,
    message_id: int,
    recorded_timestamp_ns: int,
    header_timestamp_s: float,
    origin_timestamp_s: float,
) -> dict[str, Any]:
    recorded = int(recorded_timestamp_ns) / 1_000_000_000.0
    header = float(header_timestamp_s)
    return {
        "message_id": int(message_id),
        "recorded_timestamp_s": recorded,
        "header_timestamp_s": header,
        "bag_time_s": header - float(origin_timestamp_s),
    }


def select_topic_message_rows(
    connection: sqlite3.Connection,
    topic: str,
) -> tuple[str, Iterable[tuple[int, int, bytes]]]:
    """Return the topic type and a streaming cursor of id/timestamp/payload rows."""
    topic_row = connection.execute(
        "SELECT id, type FROM topics WHERE name = ?",
        (topic,),
    ).fetchone()
    if topic_row is None:
        raise ValueError(f"missing topic {topic}")
    topic_id, topic_type = topic_row
    cursor = connection.execute(
        "SELECT id, timestamp, data FROM messages WHERE topic_id = ? ORDER BY id",
        (int(topic_id),),
    )
    return str(topic_type), cursor


def _header_timestamp_s(message: Any) -> float:
    header = getattr(message, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None or not hasattr(stamp, "sec") or not hasattr(stamp, "nanosec"):
        raise ValueError(f"LiDAR message has no standard header stamp: {type(message)!r}")
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def _bag_origin(run: Path, lidar_topic: str) -> tuple[float | None, str | None]:
    analysis = load_json(run / "metrics" / "bag_analysis.json", {}) or {}
    topic = (analysis.get("topics") or {}).get(lidar_topic) or {}
    value = topic.get("header_first_s")
    if value is None:
        return None, None
    try:
        return float(value), f"bag_analysis:{lidar_topic}:header_first_s"
    except (TypeError, ValueError):
        return None, None


def _resolve_bag_dir(run: Path, declared: Path) -> Path:
    if declared.is_absolute():
        return declared.resolve()

    freeze_manifest = run.parent / "freeze_manifest.json"
    if run.name == "source" and freeze_manifest.is_file():
        payload = load_json(freeze_manifest, {}) or {}
        source_run = payload.get("source_run") or {}
        original = source_run.get("path") if isinstance(source_run, dict) else None
        if original:
            return (Path(str(original)).expanduser().resolve() / declared).resolve()
    return (run / declared).resolve()


def _write_csv(path: Path, frames: list[dict[str, Any]]) -> None:
    fields = [
        "message_id",
        "recorded_timestamp_s",
        "header_timestamp_s",
        "bag_time_s",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(frames)


def build_pointcloud_frame_index(
    run: Path,
    *,
    deserialize_message_fn: Callable[[bytes, Any], Any] | None = None,
    get_message_fn: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Materialize an index under ``run/metrics`` while keeping bag bytes read-only.

    ``run`` may be an immutable-source compatibility copy such as
    ``<frozen>/source``. Its manifest is allowed to point at the original bag;
    only the compact JSON/CSV index is written below ``run``.
    """
    run = Path(run).resolve()
    manifest = load_json(run / "manifest.json", {}) or {}
    dataset = manifest.get("dataset") or {}
    declared_bag_text = str(dataset.get("bag_dir") or "")
    if not declared_bag_text:
        raise ValueError("manifest dataset.bag_dir is missing")
    declared_bag = Path(declared_bag_text).expanduser()
    bag = _resolve_bag_dir(run, declared_bag)
    lidar_topic = str(dataset.get("lidar_topic") or "")
    if not lidar_topic:
        raise ValueError("manifest dataset.lidar_topic is missing")
    if not bag.is_dir():
        raise FileNotFoundError(f"bag directory does not exist: {bag}")
    db_files = sorted(bag.glob("*.db3"))
    if len(db_files) != 1:
        raise ValueError(f"expected one sqlite3 bag file, found {len(db_files)} in {bag}")

    if deserialize_message_fn is None or get_message_fn is None:
        # ROS imports stay inside the reusable builder so pure helpers remain
        # testable on non-ROS hosts. Real indexing requires the exact message
        # package used by the bag (e.g. livox_ros_driver2).
        from rclpy.serialization import deserialize_message
        from rosidl_runtime_py.utilities import get_message

        deserialize_message_fn = deserialize_message
        get_message_fn = get_message

    connection = sqlite3.connect(f"file:{db_files[0]}?mode=ro", uri=True)
    try:
        topic_type, rows = select_topic_message_rows(connection, lidar_topic)
        try:
            message_class = get_message_fn(topic_type)
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError(
                f"message type support unavailable for {topic_type}; source the dataset ROS overlays before indexing"
            ) from exc

        origin, origin_source = _bag_origin(run, lidar_topic)
        pending: list[tuple[int, int, float]] = []
        frames: list[dict[str, Any]] = []
        previous_recorded: float | None = None
        previous_header: float | None = None
        recorded_backtracks = 0
        header_backtracks = 0

        for message_id, recorded_timestamp_ns, payload in rows:
            message = deserialize_message_fn(payload, message_class)
            header_time = _header_timestamp_s(message)
            if origin is None:
                origin = header_time
                origin_source = f"bag:{lidar_topic}:first_deserialized_header"
            pending.append((int(message_id), int(recorded_timestamp_ns), header_time))

        if origin is None:
            raise ValueError(f"no LiDAR messages found for {lidar_topic}")

        for message_id, recorded_timestamp_ns, header_time in pending:
            item = frame_index_row(
                message_id=message_id,
                recorded_timestamp_ns=recorded_timestamp_ns,
                header_timestamp_s=header_time,
                origin_timestamp_s=origin,
            )
            recorded = float(item["recorded_timestamp_s"])
            header = float(item["header_timestamp_s"])
            if previous_recorded is not None and recorded < previous_recorded:
                recorded_backtracks += 1
            if previous_header is not None and header < previous_header:
                header_backtracks += 1
            previous_recorded, previous_header = recorded, header
            frames.append(item)
    finally:
        connection.close()

    output_csv = run / "metrics" / "pointcloud_frame_index.csv"
    output_json = run / "metrics" / "pointcloud_frame_index.json"
    _write_csv(output_csv, frames)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "bag": str(bag),
        "sqlite_db": str(db_files[0]),
        "lidar_topic": lidar_topic,
        "lidar_type": topic_type,
        "origin_timestamp_s": float(origin),
        "origin_source": origin_source,
        "frame_count": len(frames),
        "recorded_time_backtracks": recorded_backtracks,
        "header_time_backtracks": header_backtracks,
        "first_frame": frames[0] if frames else None,
        "last_frame": frames[-1] if frames else None,
        "frames": frames,
        "payload_policy": "index-only; point-cloud bytes remain in the source rosbag2 sqlite database",
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "csv": str(output_csv),
        "json": str(output_json),
        "frames": len(frames),
        "origin_timestamp_s": float(origin),
        "origin_source": origin_source,
        "artifacts": [
            "metrics/pointcloud_frame_index.json",
            "metrics/pointcloud_frame_index.csv",
        ],
        "payload": payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()

    result = build_pointcloud_frame_index(args.run)
    print(
        json.dumps(
            {
                "csv": result["csv"],
                "json": result["json"],
                "frames": result["frames"],
                "origin_timestamp_s": result["origin_timestamp_s"],
                "origin_source": result["origin_source"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
