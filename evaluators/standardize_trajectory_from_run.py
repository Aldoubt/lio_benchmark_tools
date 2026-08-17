#!/usr/bin/env python3
"""Standardize one algorithm's run-local raw ROS 2 trajectory bag."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.rosbag_trajectory import (  # noqa: E402
    find_bag_for_topic,
    normalize_topic,
    read_pose_observations,
)
from benchmark_base.lib.trajectory_from_run import (  # noqa: E402
    build_trajectory_standardization_metadata,
    canonicalize_pose_observations,
    ensure_standardized_trajectory_absent,
    trajectory_from_observations,
    trajectory_output_paths,
    trajectory_topic_from_algorithm,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithm", required=True)
    args = parser.parse_args()

    run = args.run.resolve()
    manifest_path = run / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"missing run manifest: {manifest_path}")
    manifest = load_json(manifest_path)

    algorithms = manifest.get("algorithms", {})
    algorithm = algorithms.get(args.algorithm) if isinstance(algorithms, dict) else None
    if not isinstance(algorithm, dict):
        raise SystemExit(f"algorithm is not selected in frozen run: {args.algorithm}")

    try:
        declared_topic = trajectory_topic_from_algorithm(algorithm)
        output, metadata_path = trajectory_output_paths(run, args.algorithm)
        ensure_standardized_trajectory_absent(output)
        raw_dir = run / "raw" / args.algorithm
        bag, actual_topic, message_type = find_bag_for_topic(raw_dir, declared_topic)
        observations = read_pose_observations(bag, actual_topic, message_type)
        canonical_observations, timestamp_canonicalization = canonicalize_pose_observations(observations)
        trajectory = trajectory_from_observations(
            canonical_observations,
            source_topic=normalize_topic(actual_topic),
        )
    except (ValueError, FileExistsError) as exc:
        raise SystemExit(str(exc)) from exc

    trajectory.write_csv(output)
    relative_output = output.relative_to(run).as_posix()
    metadata = build_trajectory_standardization_metadata(
        algorithm_id=args.algorithm,
        source_bag=str(bag),
        source_topic=normalize_topic(actual_topic),
        source_message_type=message_type,
        sample_count=len(trajectory.samples),
        start_timestamp_s=trajectory.timestamps[0],
        end_timestamp_s=trajectory.timestamps[-1],
        output=relative_output,
        timestamp_canonicalization=timestamp_canonicalization,
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata, ensure_ascii=False))
    print(metadata_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
