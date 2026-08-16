#!/usr/bin/env python3
"""Audit raw ROS2 trajectory frame semantics against standardized trajectories.

This tool is read-only. It never rewrites a raw bag, standardized trajectory,
map, or display-alignment artifact.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.frame_audit import build_frame_audit  # noqa: E402
from benchmark_base.lib.registry import Registry  # noqa: E402
from benchmark_base.lib.rosbag_trajectory import (  # noqa: E402
    find_bag_for_topic,
    normalize_topic,
    read_pose_observations,
)
from benchmark_base.lib.trajectory import Trajectory  # noqa: E402
from benchmark_base.lib.trajectory_semantics import audit_semantic_labels  # noqa: E402


REGISTRY = Registry()


def declared_semantics(algorithm_id: str, algorithm: dict[str, Any]) -> tuple[str, str, str]:
    contract = algorithm.get("trajectory_contract")
    if isinstance(contract, dict):
        tracked, world = audit_semantic_labels(contract)
        return tracked, world, "FROZEN_MANIFEST"
    try:
        current = REGISTRY.load_algorithm(algorithm_id)
    except Exception:
        current = {}
    tracked, world = audit_semantic_labels(current.get("trajectory_contract"))
    return tracked, world, "CURRENT_REGISTRY_FALLBACK"


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
    observations = read_pose_observations(bag, actual_topic, message_type)
    pose_represents, world_semantics, semantics_source = declared_semantics(algorithm_id, algorithm)
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
    payload = audit.to_dict()
    payload["trajectory_semantics_source"] = semantics_source
    return payload


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
