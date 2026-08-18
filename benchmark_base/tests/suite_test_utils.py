from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from benchmark_base.lib.trajectory import PoseSample, Trajectory


ALGORITHMS = ["fast_livo2", "fast_lio2", "kiss_icp"]
DATASET_SHA = "a" * 64
LIDAR_TOPIC = "/livox/lidar"


def frozen_manifest(
    run: Path,
    *,
    dataset_sha: str | None = DATASET_SHA,
    algorithms: list[str] | None = None,
) -> dict[str, Any]:
    selected = list(algorithms or ALGORITHMS)
    dataset: dict[str, Any] = {
        "dataset_id": "suite_test_dataset",
        "bag_dir": str((run / "fixture_bag").resolve()),
        "topics": {"lidar": LIDAR_TOPIC, "imu": "/livox/imu"},
    }
    if dataset_sha is not None:
        dataset["sha256"] = dataset_sha
    return {
        "schema_version": 2,
        "name": "suite_test_experiment",
        "run_id": run.name,
        "dataset": dataset,
        "algorithms": {
            algorithm_id: {
                "algorithm_id": algorithm_id,
                "display_name": algorithm_id,
            }
            for algorithm_id in selected
        },
        "replay": {
            "rate": 1.0,
            "start_offset_s": 0.0,
            "duration_s": 45.0,
        },
        "standardization": {
            "trajectory_time_tolerance_s": 0.05,
            "map_scan_step": 5,
            "map_point_step": 8,
            "map_voxel_m": 0.12,
            "near_range_m": 0.5,
        },
    }


def create_frozen_run(
    root: Path,
    *,
    dataset_sha: str | None = DATASET_SHA,
    algorithms: list[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    run = root / "suite_run"
    run.mkdir(parents=True)
    (run / "fixture_bag").mkdir()
    manifest = frozen_manifest(run, dataset_sha=dataset_sha, algorithms=algorithms)
    (run / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run, manifest


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_valid_trajectory(run: Path, algorithm_id: str) -> Path:
    samples = [
        PoseSample(
            timestamp_s=value,
            x_m=value,
            y_m=0.0,
            z_m=0.0,
            qx=0.0,
            qy=0.0,
            qz=0.0,
            qw=1.0,
            roll_rad=0.0,
            pitch_rad=0.0,
            yaw_rad=0.0,
            source_topic="/trajectory",
        )
        for value in (-0.1, 0.0, 1.0, 2.0, 3.0, 3.1)
    ]
    path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
    Trajectory(samples).write_csv(path)
    write_json(
        run / "metadata" / "algorithms" / algorithm_id / "trajectory_standardization.json",
        {
            "schema_version": 1,
            "algorithm_id": algorithm_id,
            "sample_count": len(samples),
            "output": path.relative_to(run).as_posix(),
        },
    )
    return path
