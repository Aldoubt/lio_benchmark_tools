#!/usr/bin/env python3
"""Create immutable read-only dataset probe evidence from a local ROS 2 bag."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.bag_probe import (  # noqa: E402
    PROBE_SCHEMA,
    build_bag_identity,
    classify_candidate_roles,
    classify_sensor_layout,
    normalize_topic_evidence,
    validate_probe_payload,
)
from benchmark_base.lib.rosbag_inspection import inspect_ros2_bag  # noqa: E402


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def default_output(bag: Path) -> Path:
    resolved = bag.expanduser().resolve()
    return resolved.parent / f"{resolved.name}.lio_benchmark_probe.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    bag = args.bag.expanduser().resolve()
    if not bag.is_dir():
        raise SystemExit(f"bag path is not a directory: {bag}")
    output = (args.output.expanduser().resolve() if args.output else default_output(bag))
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing probe: {output}")

    inspection = inspect_ros2_bag(bag)
    topics = normalize_topic_evidence(inspection.get("topics", {}))
    payload = {
        "schema": "lio_benchmark_dataset_probe/v1",
        "created_at": now_iso(),
        "source": {
            "bag_dir": str(bag),
            "mode": "READ_ONLY_EVIDENCE",
        },
        "bag_identity": build_bag_identity(bag),
        "topics": topics,
        "candidate_roles": classify_candidate_roles(topics),
        "timestamp_evidence": {
            "lidar_minus_nearest_imu_header_s": inspection.get(
                "lidar_minus_nearest_imu_header_s", {}
            )
        },
        "imu_evidence": inspection.get("imu", {}),
        "sensor_layout_candidates": classify_sensor_layout(topics),
        "limitations": list(inspection.get("limitations", [])),
    }
    if payload["schema"] != PROBE_SCHEMA:
        raise RuntimeError("internal dataset probe schema mismatch")
    validate_probe_payload(payload)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
