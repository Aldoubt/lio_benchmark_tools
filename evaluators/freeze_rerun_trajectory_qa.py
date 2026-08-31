from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

import freeze_rerun_visual_qa as map_qa_adapter
from freeze_experiment import write_json_atomic


DEFAULT_TRAJECTORY_WARNING_RATIO = 3.0
DEFAULT_TRAJECTORY_SUSPECT_RATIO = 5.0
DEFAULT_TRAJECTORY_REFERENCE_FLOOR_M = (5.0, 5.0, 5.0)


def classify_trajectory_extent_xyz(
    extent_xyz_m: list[float] | tuple[float, float, float] | np.ndarray,
    baseline_extent_xyz_m: list[float] | tuple[float, float, float] | np.ndarray,
    *,
    reference_floor_m: tuple[float, float, float] = DEFAULT_TRAJECTORY_REFERENCE_FLOOR_M,
    warning_ratio: float = DEFAULT_TRAJECTORY_WARNING_RATIO,
    suspect_ratio: float = DEFAULT_TRAJECTORY_SUSPECT_RATIO,
) -> dict[str, Any]:
    """Classify aligned trajectory extent without overreacting to planar baseline Z.

    The baseline extent is floored per axis before ratio calculation. This makes
    the Native display policy robust when the baseline trajectory is nearly flat
    while still hiding clear tens-of-meters vertical or kilometer-scale failures.
    """
    extent = np.asarray(extent_xyz_m, dtype=np.float64).reshape(-1)
    baseline = np.asarray(baseline_extent_xyz_m, dtype=np.float64).reshape(-1)
    floor = np.asarray(reference_floor_m, dtype=np.float64).reshape(-1)
    if extent.shape != (3,) or baseline.shape != (3,) or floor.shape != (3,):
        raise ValueError("trajectory extents/reference floor must contain x/y/z values")
    if not np.isfinite(extent).all() or not np.isfinite(baseline).all() or not np.isfinite(floor).all():
        raise ValueError("trajectory extents/reference floor must be finite")
    if np.any(extent < 0) or np.any(baseline < 0) or np.any(floor <= 0):
        raise ValueError("trajectory extents must be nonnegative and reference floor positive")
    if warning_ratio <= 1 or suspect_ratio <= warning_ratio:
        raise ValueError("trajectory QA thresholds must satisfy 1 < warning < suspect")

    reference = np.maximum(baseline, floor)
    ratios = extent / reference
    maximum = float(np.max(ratios))
    if maximum >= float(suspect_ratio):
        status = "suspect_trajectory_extent"
    elif maximum >= float(warning_ratio):
        status = "warning_trajectory_extent"
    else:
        status = "ok"
    return {
        "status": status,
        "extent_xyz_m": extent.tolist(),
        "baseline_extent_xyz_m": baseline.tolist(),
        "reference_floor_xyz_m": floor.tolist(),
        "reference_extent_xyz_m": reference.tolist(),
        "ratio_xyz": ratios.tolist(),
        "max_ratio": maximum,
        "warning_ratio": float(warning_ratio),
        "suspect_ratio": float(suspect_ratio),
    }


def collect_trajectory_extent_qa(
    run: Path,
    *,
    algorithms: list[str],
    baseline: str,
) -> dict[str, dict[str, Any]]:
    """Inspect already-standardized aligned trajectories for Native display QA."""
    import rerun_diagnostic_viewer as viewer

    run = Path(run).resolve()
    trajectories, alignments, origin = viewer._projection_context(run, algorithms, baseline)
    extents: dict[str, np.ndarray] = {}
    for algorithm in algorithms:
        trajectory = trajectories[algorithm]
        rotation, translation = alignments[algorithm]
        aligned = viewer.apply_alignment(trajectory.positions, rotation, translation) - origin
        finite = aligned[np.isfinite(aligned).all(axis=1)]
        if len(finite) == 0:
            extents[algorithm] = np.zeros(3, dtype=np.float64)
        else:
            extents[algorithm] = np.ptp(finite, axis=0)

    if baseline not in extents:
        raise ValueError(f"baseline trajectory is unavailable for extent QA: {baseline}")
    baseline_extent = extents[baseline]
    result: dict[str, dict[str, Any]] = {}
    for algorithm in algorithms:
        item = classify_trajectory_extent_xyz(extents[algorithm], baseline_extent)
        item["is_baseline"] = algorithm == baseline
        if algorithm == baseline:
            item["status"] = "ok"
        result[algorithm] = item
    return result


def default_spatial_visibility(
    algorithms: list[str],
    *,
    baseline: str,
    visible_algorithms: set[str] | None,
    map_qa: dict[str, dict[str, Any]],
    trajectory_qa: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Combine map QA with trajectory QA while preserving all recorded evidence."""
    policy = map_qa_adapter.default_spatial_visibility(
        algorithms,
        baseline=baseline,
        visible_algorithms=visible_algorithms,
        map_qa=map_qa,
    )
    trajectory_qa = trajectory_qa or {}
    for algorithm in algorithms:
        if algorithm == baseline:
            continue
        status = str((trajectory_qa.get(algorithm) or {}).get("status") or "qa_unavailable")
        if status == "suspect_trajectory_extent":
            policy[algorithm] = {
                "algorithm_visible": False,
                "map_visible": False,
                "reason": "suspect_trajectory_extent",
            }
    return policy


def _unavailable_trajectory_qa(
    algorithms: list[str], baseline: str, exc: Exception
) -> dict[str, dict[str, Any]]:
    return {
        algorithm: {
            "status": "qa_unavailable",
            "is_baseline": algorithm == baseline,
            "reason": f"{type(exc).__name__}: {exc}",
        }
        for algorithm in algorithms
    }


def build_frozen_rerun(frozen: Path) -> dict[str, Any]:
    """Add aligned-trajectory QA around the already verified map QA adapter."""
    frozen = Path(frozen).resolve()
    payload = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    algorithms = [str(item) for item in payload.get("algorithms") or []]
    baseline = str(payload.get("baseline") or "")
    if not algorithms or not baseline:
        raise ValueError("freeze manifest is missing algorithms/baseline for trajectory QA")

    state: dict[str, Any] = {"trajectory_qa": {}}
    original_collect_map = map_qa_adapter.collect_map_extent_qa
    original_visibility = map_qa_adapter.default_spatial_visibility

    def collect_map_with_trajectory(
        run: Path, *, algorithms: list[str], baseline: str
    ) -> dict[str, dict[str, Any]]:
        map_qa = original_collect_map(run, algorithms=algorithms, baseline=baseline)
        try:
            state["trajectory_qa"] = collect_trajectory_extent_qa(
                run,
                algorithms=algorithms,
                baseline=baseline,
            )
        except Exception as exc:
            state["trajectory_qa"] = _unavailable_trajectory_qa(
                algorithms, baseline, exc
            )
        return map_qa

    def visibility_with_trajectory(
        algorithms: list[str],
        *,
        baseline: str,
        visible_algorithms: set[str] | None,
        map_qa: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        return default_spatial_visibility(
            algorithms,
            baseline=baseline,
            visible_algorithms=visible_algorithms,
            map_qa=map_qa,
            trajectory_qa=state["trajectory_qa"],
        )

    map_qa_adapter.collect_map_extent_qa = collect_map_with_trajectory
    map_qa_adapter.default_spatial_visibility = visibility_with_trajectory
    try:
        result = map_qa_adapter.build_frozen_rerun(frozen)
    finally:
        map_qa_adapter.collect_map_extent_qa = original_collect_map
        map_qa_adapter.default_spatial_visibility = original_visibility

    manifest = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    recording = manifest.get("rerun_recording") or {}
    summary = recording.get("builder_summary") or {}
    summary["trajectory_extent_qa"] = state["trajectory_qa"]
    policy = summary.get("spatial_qa_policy") or {}
    policy["trajectory_warning_ratio"] = DEFAULT_TRAJECTORY_WARNING_RATIO
    policy["trajectory_suspect_ratio"] = DEFAULT_TRAJECTORY_SUSPECT_RATIO
    policy["trajectory_reference_floor_xyz_m"] = list(DEFAULT_TRAJECTORY_REFERENCE_FLOOR_M)
    policy["suspect_trajectory_default_visibility"] = "hidden"
    summary["spatial_qa_policy"] = policy
    recording["builder_summary"] = summary
    recording["trajectory_evidence"] = {
        "extent_qa": state["trajectory_qa"],
        "policy": {
            "warning_ratio": DEFAULT_TRAJECTORY_WARNING_RATIO,
            "suspect_ratio": DEFAULT_TRAJECTORY_SUSPECT_RATIO,
            "reference_floor_xyz_m": list(DEFAULT_TRAJECTORY_REFERENCE_FLOOR_M),
            "suspect_default_visibility": "hidden",
        },
    }
    manifest["rerun_recording"] = recording
    write_json_atomic(frozen / "freeze_manifest.json", manifest)

    if isinstance(result, dict):
        result_recording = result.get("recording")
        if isinstance(result_recording, dict):
            result_recording["builder_summary"] = summary
            result_recording["trajectory_evidence"] = recording["trajectory_evidence"]
    return result
