#!/usr/bin/env python3
"""Freeze the common LiDAR scans used by every Unified Map in one run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.cloud_contract import scan_timestamp  # noqa: E402
from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.map_sampling import SelectedScan, write_scan_manifest  # noqa: E402


def build_manifest(run: Path, overwrite: bool = False) -> Path:
    run = run.resolve()
    output = run / "standardized" / "map_sampling" / "selected_scans.csv"
    if output.exists() and not overwrite:
        return output

    manifest = load_json(run / "manifest.json")
    dataset = manifest["dataset"]
    standardization = manifest.get("standardization", manifest.get("evaluation", {}))
    scan_step = int(standardization.get("map_scan_step", 5))
    if scan_step < 1:
        raise ValueError("map_scan_step must be >= 1")

    bag = Path(dataset["bag_dir"]).expanduser()
    topic = dataset.get("topics", {}).get("lidar", dataset.get("lidar_topic"))
    if not topic:
        raise ValueError("dataset LiDAR topic is required")
    timestamp = dataset.get("timestamp", {})
    point_time_field = timestamp.get("point_time_field", dataset.get("point_time_field", "timestamp"))
    point_time_unit = timestamp.get("point_time_unit", dataset.get("point_time_unit", "ns_absolute"))

    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id="sqlite3"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    types = {item.name: item.type for item in reader.get_all_topics_and_types()}
    if topic not in types:
        raise ValueError(f"bag missing lidar topic {topic}; available={sorted(types)}")
    cls = get_message(types[topic])

    rows: list[SelectedScan] = []
    scan_index = 0
    while reader.has_next():
        name, raw, bag_stamp_ns = reader.read_next()
        if name != topic:
            continue
        if scan_index % scan_step == 0:
            msg = deserialize_message(raw, cls)
            timestamp_s, source = scan_timestamp(msg, bag_stamp_ns, point_time_field, point_time_unit)
            rows.append(
                SelectedScan(
                    scan_index=scan_index,
                    timestamp_s=timestamp_s,
                    timestamp_source=source,
                    bag_record_time_s=bag_stamp_ns * 1e-9,
                    lidar_topic=topic,
                    selected=True,
                )
            )
        scan_index += 1

    if not rows:
        raise ValueError("no LiDAR scans selected for map manifest")
    write_scan_manifest(output, rows)
    metadata = {
        "schema_version": 1,
        "dataset_id": dataset.get("dataset_id", "legacy_v1_dataset"),
        "lidar_topic": topic,
        "total_lidar_scans": scan_index,
        "scan_step": scan_step,
        "selected_scan_count": len(rows),
        "manifest": str(output),
    }
    (output.parent / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    print(build_manifest(args.run, overwrite=args.overwrite))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
