#!/usr/bin/env python3
"""Read-only artifact-derived state for Benchmark Suite Orchestrator V1."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Sequence

from benchmark_base.lib.artifacts import map_artifact_paths
from benchmark_base.lib.common_map_manifest import sha256_file, validate_common_map_manifest
from benchmark_base.lib.map_sampling import read_scan_manifest
from benchmark_base.lib.suite_plan import StageDefinition, build_stage_definitions, load_and_validate_suite_plan
from benchmark_base.lib.trajectory import Trajectory


PENDING = "PENDING"
READY = "READY"
RUNNING = "RUNNING"
PASS = "PASS"
BLOCKED = "BLOCKED"
FAIL = "FAIL"

BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
BLOCKED_INPUT_IDENTITY_UNAVAILABLE = "BLOCKED_INPUT_IDENTITY_UNAVAILABLE"
BLOCKED_EXECUTOR_LOCKED = "BLOCKED_EXECUTOR_LOCKED"
FAIL_ALGORITHM = "FAIL_ALGORITHM"
FAIL_INPUT_MUTATION = "FAIL_INPUT_MUTATION"
FAIL_MANIFEST_MUTATION = "FAIL_MANIFEST_MUTATION"
FAIL_PARTIAL_ARTIFACT = "FAIL_PARTIAL_ARTIFACT"
FAIL_ARTIFACT_INVALID = "FAIL_ARTIFACT_INVALID"
FAIL_ARTIFACT_STALE = "FAIL_ARTIFACT_STALE"
FAIL_COMMAND = "FAIL_COMMAND"


@dataclass(frozen=True)
class StageState:
    stage_id: str
    state: str
    reason_code: str | None = None
    detail: str | None = None
    artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class SuiteStatus:
    run: Path
    profile: str
    dataset_id: str
    selected_algorithms: tuple[str, ...]
    state: str
    stages: tuple[StageState, ...]


def _artifact_set(paths: Sequence[Path]) -> str:
    present = sum(path.exists() for path in paths)
    if present == 0:
        return "ABSENT"
    if present == len(paths):
        return "COMPLETE"
    return "PARTIAL"


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"CSV has no data rows: {path}")
    return rows


def _state(
    stage: StageDefinition,
    state: str,
    *,
    reason: str | None = None,
    detail: str | None = None,
    artifacts: Sequence[Path] = (),
) -> StageState:
    return StageState(
        stage_id=stage.stage_id,
        state=state,
        reason_code=reason,
        detail=detail,
        artifacts=tuple(str(path) for path in artifacts),
    )


def _invalid(stage: StageDefinition, detail: str, artifacts: Sequence[Path]) -> StageState:
    return _state(stage, FAIL, reason=FAIL_ARTIFACT_INVALID, detail=detail, artifacts=artifacts)


def _partial(stage: StageDefinition, artifacts: Sequence[Path]) -> StageState:
    return _state(
        stage,
        FAIL,
        reason=FAIL_PARTIAL_ARTIFACT,
        detail="canonical stage artifact set is partial",
        artifacts=artifacts,
    )


def _simple_json_stage(run: Path, stage: StageDefinition, relative: str) -> StageState | None:
    path = run / relative
    if not path.exists():
        return None
    try:
        _load_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), (path,))
    return _state(stage, PASS, artifacts=(path,))


def _preflight_state(run: Path, stage: StageDefinition, algorithm_id: str) -> StageState | None:
    path = run / "metadata" / "algorithms" / algorithm_id / "preflight.json"
    if not path.exists():
        return None
    try:
        payload = _load_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), (path,))
    if payload.get("algorithm_id") not in (None, algorithm_id):
        return _invalid(stage, "preflight algorithm_id mismatch", (path,))
    if payload.get("runnable") is True and payload.get("status") == "PASS":
        return _state(stage, PASS, artifacts=(path,))
    status = str(payload.get("status", ""))
    if status == BLOCKED_ENVIRONMENT and payload.get("runnable") is False:
        identity = run / "metadata" / "algorithms" / algorithm_id / "runtime_identity.json"
        if identity.exists():
            return _invalid(stage, "blocked preflight conflicts with existing runtime identity", (path, identity))
        return _state(stage, BLOCKED, reason=BLOCKED_ENVIRONMENT, artifacts=(path,))
    return _invalid(stage, f"preflight is not formal PASS or recoverable BLOCKED_ENVIRONMENT: {status}", (path,))


def _runtime_state(run: Path, stage: StageDefinition, algorithm_id: str) -> StageState | None:
    identity = run / "metadata" / "algorithms" / algorithm_id / "runtime_identity.json"
    run_status = run / "metadata" / f"run_{algorithm_id}.json"
    performance = run / "metrics" / "runtime" / f"{algorithm_id}.json"
    identity_exists = identity.exists()
    status_exists = run_status.exists()
    performance_exists = performance.exists()
    if not identity_exists and not status_exists and not performance_exists:
        return None
    if not identity_exists or not status_exists:
        return _invalid(
            stage,
            "runtime identity and run status must exist together after a runtime attempt",
            (identity, run_status, performance),
        )
    try:
        identity_payload = _load_object(identity)
        status_payload = _load_object(run_status)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), (identity, run_status, performance))
    if identity_payload.get("identity_status") != "FROZEN":
        return _invalid(stage, "runtime identity is not FROZEN", (identity, run_status, performance))
    if identity_payload.get("algorithm_id") not in (None, algorithm_id):
        return _invalid(stage, "runtime identity algorithm_id mismatch", (identity, run_status, performance))
    status = str(status_payload.get("status", ""))
    if status == FAIL_ALGORITHM:
        return _state(
            stage,
            FAIL,
            reason=FAIL_ALGORITHM,
            detail="estimator runtime attempt failed and is non-rerunnable in this run",
            artifacts=(identity, run_status, performance),
        )
    if status != PASS:
        return _invalid(stage, f"unsupported runtime status with frozen identity: {status}", (identity, run_status, performance))
    if not performance_exists:
        return _partial(stage, (identity, run_status, performance))
    try:
        perf = _load_object(performance)
        if perf.get("measurement_method") is None or perf.get("wall_time_s") is None or perf.get("max_rss_kib") is None:
            raise ValueError("runtime performance evidence is incomplete")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), (identity, run_status, performance))
    return _state(stage, PASS, artifacts=(identity, run_status, performance))


def _identity_state(run: Path, stage: StageDefinition, phase: str) -> StageState | None:
    path = run / "metadata" / "suite" / f"dataset_identity_{phase}.json"
    if not path.exists():
        return None
    try:
        payload = _load_object(path)
        plan = _load_object(run / "metadata" / "suite" / "plan.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), (path,))
    if payload.get("schema") != "lio_benchmark_suite_dataset_identity/v1":
        return _invalid(stage, "invalid suite dataset identity schema", (path,))
    if payload.get("phase") != phase:
        return _invalid(stage, "dataset identity phase mismatch", (path,))
    plan_dataset = plan.get("dataset")
    plan_expected = (
        plan_dataset.get("expected_bag_content_sha256") if isinstance(plan_dataset, dict) else None
    )
    if payload.get("status") == PASS:
        expected = payload.get("expected_bag_content_sha256")
        observed = payload.get("observed_bag_content_sha256")
        if not isinstance(expected, str) or observed != expected:
            return _invalid(stage, "PASS dataset identity record does not match expected hash", (path,))
        if expected != plan_expected:
            return _invalid(stage, "dataset identity expected hash does not match immutable suite plan", (path,))
        if phase == "post":
            pre_path = run / "metadata" / "suite" / "dataset_identity_pre.json"
            try:
                pre = _load_object(pre_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return _invalid(stage, f"post identity cannot validate pre evidence: {exc}", (path, pre_path))
            pre_observed = pre.get("observed_bag_content_sha256")
            if pre.get("status") != PASS or pre.get("expected_bag_content_sha256") != plan_expected:
                return _invalid(stage, "post identity requires valid PASS pre identity bound to plan", (path, pre_path))
            if payload.get("pre_observed_bag_content_sha256") != pre_observed or observed != pre_observed:
                return _invalid(stage, "post identity does not match frozen pre observed hash", (path, pre_path))
        return _state(stage, PASS, artifacts=(path,))
    reason = str(payload.get("reason_code", FAIL_INPUT_MUTATION))
    return _state(stage, FAIL, reason=reason, detail="dataset identity gate failed", artifacts=(path,))


def _trajectory_state(run: Path, stage: StageDefinition, algorithm_id: str) -> StageState | None:
    trajectory = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
    metadata = run / "metadata" / "algorithms" / algorithm_id / "trajectory_standardization.json"
    paths = (trajectory, metadata)
    presence = _artifact_set(paths)
    if presence == "ABSENT":
        return None
    if presence == "PARTIAL":
        return _partial(stage, paths)
    try:
        value = _load_object(metadata)
        parsed = Trajectory.from_csv(trajectory)
        if value.get("algorithm_id") not in (None, algorithm_id):
            raise ValueError("trajectory metadata algorithm_id mismatch")
        sample_count = value.get("sample_count")
        if not isinstance(sample_count, int) or sample_count != len(parsed.samples) or sample_count <= 0:
            raise ValueError("trajectory metadata sample_count does not match CSV")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), paths)
    return _state(stage, PASS, artifacts=paths)


def _per_algorithm_pair_stage(
    run: Path,
    stage: StageDefinition,
    algorithms: Sequence[str],
    csv_root: Path,
    metadata_root: Path,
) -> StageState | None:
    csvs = tuple(csv_root / f"{algorithm_id}.csv" for algorithm_id in algorithms)
    metadata = tuple(metadata_root / f"{algorithm_id}.json" for algorithm_id in algorithms)
    paths = csvs + metadata
    presence = _artifact_set(paths)
    if presence == "ABSENT":
        return None
    if presence == "PARTIAL":
        return _partial(stage, paths)
    try:
        for algorithm_id, csv_path, metadata_path in zip(algorithms, csvs, metadata):
            _csv_rows(csv_path)
            payload = _load_object(metadata_path)
            if payload.get("algorithm_id") != algorithm_id:
                raise ValueError(f"audit metadata algorithm_id mismatch: {algorithm_id}")
            summary = payload.get("summary")
            if not isinstance(summary, dict):
                raise ValueError(f"timestamp audit summary is missing: {algorithm_id}")
            regressions = summary.get("effective_regression_count")
            if not isinstance(regressions, int) or regressions != 0:
                raise ValueError(
                    f"timestamp audit effective regression count must be zero: "
                    f"{algorithm_id}={regressions}"
                )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), paths)
    return _state(stage, PASS, artifacts=paths)


def _frame_audit_state(run: Path, stage: StageDefinition, algorithms: Sequence[str]) -> StageState | None:
    csv_path = run / "metrics" / "trajectory_frame_audit.csv"
    metadata = tuple(run / "metadata" / "frame_audit" / f"{algorithm_id}.json" for algorithm_id in algorithms)
    paths = metadata + (csv_path,)
    presence = _artifact_set(paths)
    if presence == "ABSENT":
        return None
    if presence == "PARTIAL":
        return _partial(stage, paths)
    try:
        rows = {row.get("algorithm_id"): row for row in _csv_rows(csv_path)}
        for algorithm_id, path in zip(algorithms, metadata):
            payload = _load_object(path)
            if payload.get("algorithm_id") != algorithm_id or payload.get("status") != "AVAILABLE":
                raise ValueError(f"frame audit evidence is not AVAILABLE for {algorithm_id}")
            if rows.get(algorithm_id, {}).get("status") != "AVAILABLE":
                raise ValueError(f"frame audit CSV evidence is not AVAILABLE for {algorithm_id}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), paths)
    return _state(stage, PASS, artifacts=paths)


def _runtime_provenance_state(run: Path, stage: StageDefinition, algorithms: Sequence[str]) -> StageState | None:
    csv_path = run / "metrics" / "runtime_provenance.csv"
    metadata = tuple(run / "metadata" / "runtime_provenance" / f"{algorithm_id}.json" for algorithm_id in algorithms)
    paths = metadata + (csv_path,)
    presence = _artifact_set(paths)
    if presence == "ABSENT":
        return None
    if presence == "PARTIAL":
        return _partial(stage, paths)
    required = {
        "status": "MATCH",
        "frame_contract_status": "MATCH",
        "identity_evidence_source": "RUNTIME_IDENTITY",
        "runtime_identity_status": "FROZEN",
    }
    try:
        rows = {row.get("algorithm_id"): row for row in _csv_rows(csv_path)}
        for algorithm_id, path in zip(algorithms, metadata):
            payload = _load_object(path)
            if payload.get("algorithm_id") != algorithm_id:
                raise ValueError(f"runtime provenance algorithm_id mismatch: {algorithm_id}")
            row = rows.get(algorithm_id)
            if row is None:
                raise ValueError(f"runtime provenance CSV row missing: {algorithm_id}")
            for key, expected in required.items():
                if str(payload.get(key)) != expected or str(row.get(key)) != expected:
                    raise ValueError(f"runtime provenance {key} is not {expected}: {algorithm_id}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), paths)
    return _state(stage, PASS, artifacts=paths)


def _coverage_state(run: Path, stage: StageDefinition, algorithms: Sequence[str]) -> StageState | None:
    csv_path = run / "metrics" / "trajectory_coverage.csv"
    metadata = tuple(run / "metadata" / "trajectory_coverage" / f"{algorithm_id}.json" for algorithm_id in algorithms)
    paths = metadata + (csv_path,)
    presence = _artifact_set(paths)
    if presence == "ABSENT":
        return None
    if presence == "PARTIAL":
        return _partial(stage, paths)
    try:
        rows = {row.get("algorithm_id"): row for row in _csv_rows(csv_path)}
        for algorithm_id, path in zip(algorithms, metadata):
            payload = _load_object(path)
            if payload.get("algorithm_id") != algorithm_id or algorithm_id not in rows:
                raise ValueError(f"trajectory coverage evidence missing: {algorithm_id}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), paths)
    return _state(stage, PASS, artifacts=paths)


def _scan_manifest_state(run: Path, stage: StageDefinition, plan: dict[str, Any]) -> StageState | None:
    selected = run / "standardized" / "map_sampling" / "selected_scans.csv"
    metadata = selected.parent / "metadata.json"
    paths = (selected, metadata)
    presence = _artifact_set(paths)
    if presence == "ABSENT":
        return None
    if presence == "PARTIAL":
        return _partial(stage, paths)
    try:
        rows = read_scan_manifest(selected)
        payload = _load_object(metadata)
        if not rows:
            raise ValueError("selected scan manifest is empty")
        if payload.get("selected_scan_count") != len(rows):
            raise ValueError("selected scan metadata count mismatch")
        frozen_lidar = _load_object(run / "manifest.json").get("dataset", {}).get("topics", {}).get("lidar")
        if payload.get("lidar_topic") != frozen_lidar:
            raise ValueError("selected scan LiDAR topic differs from frozen dataset")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), paths)
    return _state(stage, PASS, artifacts=paths)


def _common_map_state(run: Path, stage: StageDefinition) -> StageState | None:
    root = run / "standardized" / "map_sampling"
    paths = (root / "common_matched_scans.csv", root / "common_matched_metadata.json")
    presence = _artifact_set(paths)
    if presence == "ABSENT":
        return None
    if presence == "PARTIAL":
        return _partial(stage, paths)
    try:
        validate_common_map_manifest(run)
    except ValueError as exc:
        text = str(exc)
        reason = FAIL_ARTIFACT_STALE if "stale or incomplete" in text or "create a new run" in text else FAIL_ARTIFACT_INVALID
        return _state(stage, FAIL, reason=reason, detail=text, artifacts=paths)
    return _state(stage, PASS, artifacts=paths)


def _unified_map_state(run: Path, stage: StageDefinition, algorithm_id: str) -> StageState | None:
    paths_obj = map_artifact_paths(run, algorithm_id)
    paths = (
        paths_obj.unified_map,
        paths_obj.unified_metadata,
        paths_obj.compat_unified_map,
        paths_obj.compat_unified_metadata,
    )
    presence = _artifact_set(paths)
    if presence == "ABSENT":
        return None
    if presence == "PARTIAL":
        return _partial(stage, paths)
    common = run / "standardized" / "map_sampling" / "common_matched_scans.csv"
    try:
        metadata = _load_object(paths_obj.unified_metadata)
        compat = _load_object(paths_obj.compat_unified_metadata)
        if metadata != compat:
            raise ValueError("Unified Map canonical and compatibility metadata differ")
        if metadata.get("algorithm_id") != algorithm_id:
            raise ValueError("Unified Map algorithm_id mismatch")
        if metadata.get("scan_set_policy") != "STRICT_COMMON_INTERSECTION":
            raise ValueError("Unified Map scan_set_policy is not STRICT_COMMON_INTERSECTION")
        if not isinstance(metadata.get("point_count"), int) or metadata["point_count"] <= 0:
            raise ValueError("Unified Map point_count must be positive")
        matching = metadata.get("timestamp_matching")
        if not isinstance(matching, dict):
            raise ValueError("Unified Map timestamp_matching is missing")
        selected = matching.get("selected_scan_count")
        matched = matching.get("matched_scan_count")
        unmatched = matching.get("unmatched_scan_count")
        if not isinstance(selected, int) or selected <= 0 or matched != selected or unmatched != 0:
            raise ValueError("Unified Map strict matched-scan counts are invalid")
        if not common.is_file() or metadata.get("common_manifest_sha256") != sha256_file(common):
            raise ValueError("Unified Map common manifest fingerprint is stale")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        reason = FAIL_ARTIFACT_STALE if "stale" in str(exc) else FAIL_ARTIFACT_INVALID
        return _state(stage, FAIL, reason=reason, detail=str(exc), artifacts=paths)
    return _state(stage, PASS, artifacts=paths)


def _relative_se3_state(run: Path, stage: StageDefinition, algorithms: Sequence[str]) -> StageState | None:
    root = run / "metrics" / "relative_se3"
    paths = tuple(
        root / name
        for name in (
            "metadata.json",
            "normalized_motion.csv",
            "pairwise_samples.csv",
            "pairwise_summary.csv",
            "onset_thresholds.csv",
        )
    )
    presence = _artifact_set(paths)
    if presence == "ABSENT":
        return None
    if presence == "PARTIAL":
        return _partial(stage, paths)
    try:
        metadata = _load_object(paths[0])
        for path in paths[1:]:
            _csv_rows(path)
        if metadata.get("requested_algorithms") != list(algorithms):
            raise ValueError("Relative SE(3) requested algorithm set/order differs from frozen suite")
        if metadata.get("terminology") != "PAIRWISE_DISAGREEMENT":
            raise ValueError("Relative SE(3) terminology is not PAIRWISE_DISAGREEMENT")
        if metadata.get("blocked_algorithms") not in ({}, None):
            raise ValueError("Relative SE(3) contains blocked algorithms")
        eligible = metadata.get("eligible_algorithms")
        if eligible is not None and set(eligible) != set(algorithms):
            raise ValueError("Relative SE(3) eligible set differs from frozen suite")
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        return _invalid(stage, str(exc), paths)
    return _state(stage, PASS, artifacts=paths)


def _summary_state(run: Path, stage: StageDefinition, algorithms: Sequence[str]) -> StageState | None:
    paths = (
        run / "reports" / "algorithm_io_matrix.csv",
        run / "reports" / "algorithm_io_matrix.md",
        run / "metrics" / "runtime_performance.csv",
        run / "reports" / "same_bag_mapping_v1.json",
    )
    presence = _artifact_set(paths)
    if presence == "ABSENT":
        return None
    if presence == "PARTIAL":
        return _partial(stage, paths)
    try:
        _csv_rows(paths[0])
        if not paths[1].read_text(encoding="utf-8").strip():
            raise ValueError("Same-Bag markdown summary is empty")
        _csv_rows(paths[2])
        payload = _load_object(paths[3])
        if payload.get("artifact_role") != "CANONICAL_FINAL_SUMMARY":
            raise ValueError("Same-Bag summary is not CANONICAL_FINAL_SUMMARY")
        rows = payload.get("algorithms")
        if not isinstance(rows, list) or [row.get("algorithm_id") for row in rows if isinstance(row, dict)] != list(algorithms):
            raise ValueError("Same-Bag summary algorithm set/order differs from frozen suite")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid(stage, str(exc), paths)
    return _state(stage, PASS, artifacts=paths)


def _inspect_artifacts(run: Path, plan: dict[str, Any], stage: StageDefinition) -> StageState | None:
    stage_id = stage.stage_id
    algorithms = tuple(str(value) for value in plan["selected_algorithms"])
    if stage_id == "snapshot":
        return _simple_json_stage(run, stage, "metadata/environment_snapshot.json")
    if stage_id == "analyze_bag":
        return _simple_json_stage(run, stage, "metrics/bag_analysis.json")
    if stage_id.startswith("preflight/"):
        return _preflight_state(run, stage, stage_id.split("/", 1)[1])
    if stage_id == "dataset_identity/pre":
        return _identity_state(run, stage, "pre")
    if stage_id.startswith("runtime/"):
        return _runtime_state(run, stage, stage_id.split("/", 1)[1])
    if stage_id == "dataset_identity/post":
        return _identity_state(run, stage, "post")
    if stage_id.startswith("trajectory/"):
        return _trajectory_state(run, stage, stage_id.split("/", 1)[1])
    if stage_id == "audit/trajectory_timestamps":
        return _per_algorithm_pair_stage(
            run,
            stage,
            algorithms,
            run / "metrics" / "trajectory_timestamp_audit",
            run / "metadata" / "trajectory_timestamp_audit",
        )
    if stage_id == "audit/trajectory_frames":
        return _frame_audit_state(run, stage, algorithms)
    if stage_id == "audit/runtime_provenance":
        return _runtime_provenance_state(run, stage, algorithms)
    if stage_id == "audit/trajectory_coverage":
        return _coverage_state(run, stage, algorithms)
    if stage_id == "scan_manifest":
        return _scan_manifest_state(run, stage, plan)
    if stage_id == "common_map_manifest":
        return _common_map_state(run, stage)
    if stage_id.startswith("unified_map/"):
        return _unified_map_state(run, stage, stage_id.split("/", 1)[1])
    if stage_id == "relative_se3":
        return _relative_se3_state(run, stage, algorithms)
    if stage_id == "same_bag_summary":
        return _summary_state(run, stage, algorithms)
    return _invalid(stage, f"unknown suite stage: {stage_id}", ())


def _dependency_gate(stage: StageDefinition, states: dict[str, StageState]) -> StageState:
    dependencies = [states[stage_id] for stage_id in stage.dependencies]
    if stage.stage_id == "dataset_identity/post":
        terminal = all(
            dependency.state == PASS
            or (dependency.state == FAIL and dependency.reason_code == FAIL_ALGORITHM)
            for dependency in dependencies
        )
        if terminal:
            return _state(stage, READY)
        if any(dependency.state in {BLOCKED, FAIL} for dependency in dependencies):
            return _state(stage, BLOCKED, reason=BLOCKED_DEPENDENCY)
        return _state(stage, PENDING)
    if any(dependency.state in {BLOCKED, FAIL} for dependency in dependencies):
        return _state(stage, BLOCKED, reason=BLOCKED_DEPENDENCY)
    if all(dependency.state == PASS for dependency in dependencies):
        return _state(stage, READY)
    return _state(stage, PENDING)


def _derive_one(
    run: Path,
    plan: dict[str, Any],
    stage: StageDefinition,
    states: dict[str, StageState],
) -> StageState:
    observed = _inspect_artifacts(run, plan, stage)
    gate = _dependency_gate(stage, states)
    if observed is None:
        return gate
    if observed.state != PASS:
        return observed
    if gate.state == READY:
        return observed
    return _state(
        stage,
        FAIL,
        reason=FAIL_ARTIFACT_STALE,
        detail="stage artifact exists but dependency contract is no longer satisfied",
        artifacts=tuple(Path(path) for path in observed.artifacts),
    )


def _all_states(run: Path, plan: dict[str, Any]) -> tuple[StageState, ...]:
    definitions = build_stage_definitions(list(plan["selected_algorithms"]))
    states: dict[str, StageState] = {}
    ordered: list[StageState] = []
    for stage in definitions:
        state = _derive_one(run, plan, stage, states)
        states[stage.stage_id] = state
        ordered.append(state)
    return tuple(ordered)


def derive_stage_state(run: Path, plan: dict[str, Any], stage: StageDefinition) -> StageState:
    run = Path(run).resolve()
    states = _all_states(run, plan)
    for row in states:
        if row.stage_id == stage.stage_id:
            return row
    raise ValueError(f"unknown suite stage: {stage.stage_id}")


def _overall_state(stages: Sequence[StageState]) -> str:
    if any(stage.state == RUNNING for stage in stages):
        return RUNNING
    by_id = {stage.stage_id: stage for stage in stages}
    if by_id.get("same_bag_summary") and by_id["same_bag_summary"].state == PASS:
        return PASS
    if any(stage.state == FAIL for stage in stages):
        return FAIL
    if any(stage.state == READY for stage in stages):
        return READY
    if any(stage.state == BLOCKED for stage in stages):
        return BLOCKED
    return PENDING


def _apply_execution_observation(
    stages: tuple[StageState, ...],
    execution: Any | None,
) -> tuple[StageState, ...]:
    if execution is None or not bool(getattr(execution, "locked", False)):
        return stages
    active = getattr(execution, "active_stage_id", None)
    if not isinstance(active, str) or not active:
        return stages
    replaced: list[StageState] = []
    matched = False
    for stage in stages:
        if stage.stage_id == active:
            matched = True
            replaced.append(
                StageState(
                    stage_id=stage.stage_id,
                    state=RUNNING,
                    reason_code=None,
                    detail="live suite executor owns lock and has an unmatched STAGE_STARTED event",
                    artifacts=stage.artifacts,
                )
            )
        else:
            replaced.append(stage)
    return tuple(replaced) if matched else stages


def derive_suite_status(run: Path, *, execution: Any | None = None) -> SuiteStatus:
    """Derive suite state without creating, repairing, or rewriting any artifact."""
    run = Path(run).resolve()
    plan = load_and_validate_suite_plan(run)
    stages = _apply_execution_observation(_all_states(run, plan), execution)
    return SuiteStatus(
        run=run,
        profile=str(plan["profile"]),
        dataset_id=str(plan["dataset"]["dataset_id"]),
        selected_algorithms=tuple(str(value) for value in plan["selected_algorithms"]),
        state=_overall_state(stages),
        stages=stages,
    )


def status_to_dict(status: SuiteStatus) -> dict[str, Any]:
    return {
        "run": str(status.run),
        "profile": status.profile,
        "dataset_id": status.dataset_id,
        "selected_algorithms": list(status.selected_algorithms),
        "state": status.state,
        "stages": [
            {
                "stage_id": stage.stage_id,
                "state": stage.state,
                "reason_code": stage.reason_code,
                "detail": stage.detail,
                "artifacts": list(stage.artifacts),
            }
            for stage in status.stages
        ],
    }
