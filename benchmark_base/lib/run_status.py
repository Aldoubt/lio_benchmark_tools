#!/usr/bin/env python3
"""Render run status from run-local evidence instead of stale workflow text."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _algorithm_ids(manifest: dict[str, Any]) -> tuple[str, ...]:
    algorithms = manifest.get("algorithms", {})
    if isinstance(algorithms, dict):
        return tuple(str(value) for value in algorithms)
    if isinstance(algorithms, list):
        return tuple(str(value) for value in algorithms)
    return ()


def refresh_run_status(run: str | Path, manifest: dict[str, Any]) -> Path:
    """Rewrite ``RUN_STATUS.md`` from current run-local evidence.

    This is descriptive workflow state only. It never infers estimator accuracy
    or changes scientific artifacts.
    """
    run = Path(run).resolve()
    algorithms = _algorithm_ids(manifest)
    selected = len(algorithms)

    frontend_passed = 0
    trajectories_available = 0
    blocked = False
    for algorithm_id in algorithms:
        run_state = _load_json(run / "metadata" / f"run_{algorithm_id}.json")
        if run_state is not None and str(run_state.get("status", "")) == "PASS":
            frontend_passed += 1
        elif run_state is not None and str(run_state.get("status", "")):
            blocked = True

        trajectory = _load_json(
            run / "metadata" / "algorithms" / algorithm_id / "trajectory_standardization.json"
        )
        if trajectory is not None and int(trajectory.get("sample_count", 0) or 0) > 0:
            trajectories_available += 1

    frame_available = (run / "metrics" / "trajectory_frame_audit.csv").is_file()
    provenance_available = (run / "metrics" / "runtime_provenance.csv").is_file()
    relative_se3_available = (run / "metrics" / "relative_se3" / "metadata.json").is_file()
    bundle_dir = run / "reports" / "bundles"
    bundle_available = bundle_dir.is_dir() and any(bundle_dir.glob("*.tar.gz"))

    primary_complete = bool(selected) and all(
        (
            frontend_passed == selected,
            trajectories_available == selected,
            frame_available,
            provenance_available,
            relative_se3_available,
        )
    )
    status = "blocked" if blocked and not primary_complete else "complete" if primary_complete else "active"

    path = run / "RUN_STATUS.md"
    path.write_text(
        "\n".join(
            (
                f"# Run {manifest.get('run_id', run.name)}",
                "",
                f"- status: {status}",
                f"- frontends: {frontend_passed}/{selected}",
                f"- trajectories: {trajectories_available}/{selected}",
                f"- frame audit: {'AVAILABLE' if frame_available else 'MISSING'}",
                f"- runtime provenance: {'AVAILABLE' if provenance_available else 'MISSING'}",
                f"- relative se3: {'AVAILABLE' if relative_se3_available else 'MISSING'}",
                f"- bundle: {'AVAILABLE' if bundle_available else 'MISSING'}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path
