#!/usr/bin/env python3
"""Collect a true upstream native map without reconstructing or relabeling it."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.artifacts import (  # noqa: E402
    build_native_map_metadata,
    map_artifact_paths,
    write_json,
)
from benchmark_base.lib.manifest import load_json  # noqa: E402


def collect(
    run: Path,
    algorithm_id: str,
    source: Path | None,
    source_role: str,
    coordinate_frame: str | None,
) -> dict:
    run = run.resolve()
    manifest = load_json(run / "manifest.json")
    dataset_id = manifest["dataset"].get("dataset_id", "legacy_v1_dataset")
    paths = map_artifact_paths(run, algorithm_id)
    paths.native_dir.mkdir(parents=True, exist_ok=True)
    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()

    if source is None:
        metadata = build_native_map_metadata(
            algorithm_id=algorithm_id,
            dataset_id=dataset_id,
            status="NOT_PROVIDED",
            source_output=None,
            source_role=source_role,
            generated_at=generated_at,
            coordinate_frame=coordinate_frame,
        )
        write_json(paths.native_metadata, metadata)
        return metadata

    source = source.expanduser().resolve()
    if not source.is_file():
        metadata = build_native_map_metadata(
            algorithm_id=algorithm_id,
            dataset_id=dataset_id,
            status="FAILED",
            source_output=str(source),
            source_role=source_role,
            generated_at=generated_at,
            coordinate_frame=coordinate_frame,
            source_format=source.suffix.lower().lstrip(".") or None,
        )
        write_json(paths.native_metadata, metadata)
        return metadata

    suffix = source.suffix.lower() or ".bin"
    destination = paths.native_dir / f"map{suffix}"
    shutil.copy2(source, destination)
    metadata = build_native_map_metadata(
        algorithm_id=algorithm_id,
        dataset_id=dataset_id,
        status="AVAILABLE",
        source_output=str(source),
        source_role=source_role,
        generated_at=generated_at,
        coordinate_frame=coordinate_frame,
        source_format=suffix.lstrip("."),
    )
    metadata["collected_output"] = str(destination)
    write_json(paths.native_metadata, metadata)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithm", required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--source-role", default="ODOMETRY")
    parser.add_argument("--coordinate-frame")
    args = parser.parse_args()
    result = collect(args.run, args.algorithm, args.source, args.source_role, args.coordinate_frame)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
