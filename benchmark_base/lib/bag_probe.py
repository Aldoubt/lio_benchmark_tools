#!/usr/bin/env python3
"""Pure dataset-probe contracts for local ROS 2 bags.

This module intentionally has no ROS imports. ROS-aware message inspection lives
in ``benchmark_base.lib.rosbag_inspection``; this module only normalizes the
observed evidence, fingerprints bag content, and classifies conservative topic
roles/layouts.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


PROBE_SCHEMA = "lio_benchmark_dataset_probe/v1"
LIDAR_TYPES = frozenset({
    "livox_ros_driver2/msg/CustomMsg",
    "sensor_msgs/msg/PointCloud2",
})
IMU_TYPE = "sensor_msgs/msg/Imu"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_record(path: Path, bag_dir: Path) -> dict[str, Any]:
    return {
        "relative_path": path.relative_to(bag_dir).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_bag_identity(bag_dir: Path) -> dict[str, Any]:
    bag = bag_dir.expanduser().resolve()
    if not bag.is_dir():
        raise ValueError(f"bag path is not a directory: {bag}")

    storage_paths = sorted(
        path
        for pattern in ("*.db3", "*.mcap")
        for path in bag.glob(pattern)
        if path.is_file()
    )
    if not storage_paths:
        raise ValueError(f"no ROS 2 bag storage files found in: {bag}")

    storage_files = [_file_record(path, bag) for path in storage_paths]
    metadata_path = bag / "metadata.yaml"
    metadata = _file_record(metadata_path, bag) if metadata_path.is_file() else None

    aggregate_rows: list[dict[str, Any]] = [
        {
            "relative_path": row["relative_path"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
        }
        for row in storage_files
    ]
    if metadata is not None:
        aggregate_rows.append(
            {
                "relative_path": metadata["relative_path"],
                "size_bytes": metadata["size_bytes"],
                "sha256": metadata["sha256"],
            }
        )
    aggregate_rows.sort(key=lambda row: row["relative_path"])
    canonical = json.dumps(
        aggregate_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    content_sha = hashlib.sha256(canonical).hexdigest()
    return {
        "bag_dir": str(bag),
        "storage_files": storage_files,
        "metadata_yaml": metadata,
        "bag_content_sha256": content_sha,
    }


def _median(container: Any) -> float | None:
    if not isinstance(container, dict):
        return None
    value = container.get("median")
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate_from_period(period: float | None) -> float | None:
    if period is None or period <= 0.0:
        return None
    return 1.0 / period


def normalize_topic_evidence(raw_topics: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(raw_topics, dict):
        raise ValueError("raw topic evidence must be an object")
    rows: list[dict[str, Any]] = []
    for name, raw in raw_topics.items():
        if not isinstance(raw, dict):
            raise ValueError(f"topic evidence must be an object: {name}")
        recorded_period = _median(raw.get("recorded_dt_s"))
        header_period = _median(raw.get("header_dt_s"))
        rows.append(
            {
                "name": str(name),
                "type": str(raw.get("type", "")),
                "message_count": int(raw.get("count", 0)),
                "recorded_first_s": raw.get("recorded_first_s"),
                "recorded_last_s": raw.get("recorded_last_s"),
                "recorded_dt_median_s": recorded_period,
                "recorded_rate_hz": _rate_from_period(recorded_period),
                "recorded_time_reversal_count": int(raw.get("recorded_time_reversals", 0)),
                "header_first_s": raw.get("header_first_s"),
                "header_last_s": raw.get("header_last_s"),
                "header_dt_median_s": header_period,
                "header_rate_hz": _rate_from_period(header_period),
                "header_time_reversal_count": int(raw.get("header_time_reversals", 0)),
                "frame_ids": list(raw.get("frame_ids", [])),
                "point_fields": raw.get("point_fields"),
            }
        )
    return rows


def _role(candidates: list[str]) -> dict[str, Any]:
    ordered = sorted(candidates)
    if not ordered:
        return {"candidates": [], "recommended": None, "status": "MISSING"}
    if len(ordered) == 1:
        return {"candidates": ordered, "recommended": ordered[0], "status": "UNAMBIGUOUS"}
    return {"candidates": ordered, "recommended": None, "status": "AMBIGUOUS"}


def classify_candidate_roles(topics: list[dict[str, Any]]) -> dict[str, Any]:
    lidar = [str(row["name"]) for row in topics if row.get("type") in LIDAR_TYPES]
    imu = [str(row["name"]) for row in topics if row.get("type") == IMU_TYPE]
    return {"lidar": _role(lidar), "imu": _role(imu)}


def classify_sensor_layout(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for topic in topics:
        type_name = topic.get("type")
        if type_name == "livox_ros_driver2/msg/CustomMsg":
            layout = "LIVOX_CUSTOM_LAYOUT"
        elif type_name == "sensor_msgs/msg/PointCloud2":
            layout = "POINTCLOUD2_LAYOUT"
        else:
            continue
        rows.append({"topic": str(topic.get("name", "")), "layout": layout})
    return rows


def validate_probe_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("probe payload must be an object")
    if payload.get("schema") != PROBE_SCHEMA:
        raise ValueError(f"probe schema must be {PROBE_SCHEMA}")
    for key in (
        "created_at",
        "source",
        "bag_identity",
        "topics",
        "candidate_roles",
        "timestamp_evidence",
        "imu_evidence",
        "sensor_layout_candidates",
        "limitations",
    ):
        if key not in payload:
            raise ValueError(f"probe payload missing field: {key}")

    source = payload["source"]
    if not isinstance(source, dict) or not source.get("bag_dir"):
        raise ValueError("probe source.bag_dir is required")
    identity = payload["bag_identity"]
    if not isinstance(identity, dict):
        raise ValueError("probe bag_identity must be an object")
    if not isinstance(identity.get("storage_files"), list) or not identity["storage_files"]:
        raise ValueError("probe bag_identity.storage_files must be non-empty")
    content_sha = str(identity.get("bag_content_sha256", ""))
    if len(content_sha) != 64:
        raise ValueError("probe bag_identity.bag_content_sha256 must be SHA-256")
    if not isinstance(payload["topics"], list):
        raise ValueError("probe topics must be a list")
    if not isinstance(payload["candidate_roles"], dict):
        raise ValueError("probe candidate_roles must be an object")
    if not isinstance(payload["sensor_layout_candidates"], list):
        raise ValueError("probe sensor_layout_candidates must be a list")
    if not isinstance(payload["limitations"], list):
        raise ValueError("probe limitations must be a list")
