from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ALGORITHMS = ["fast_livo2", "fast_lio2", "kiss_icp"]
DATASET_SHA = "a" * 64


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
    }


def create_frozen_run(
    root: Path,
    *,
    dataset_sha: str | None = DATASET_SHA,
    algorithms: list[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    run = root / "suite_run"
    run.mkdir(parents=True)
    manifest = frozen_manifest(run, dataset_sha=dataset_sha, algorithms=algorithms)
    (run / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run, manifest
