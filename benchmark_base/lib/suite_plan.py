#!/usr/bin/env python3
"""Immutable plan contract for Benchmark Suite Orchestrator V1."""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import json
from pathlib import Path
import re
from typing import Any, Iterable

from benchmark_base.lib.manifest import sha256_file


SUITE_PLAN_SCHEMA = "lio_benchmark_suite_plan/v1"
SUITE_PROFILE = "SAME_BAG_MAPPING_V1"
REUSABLE_IF_VALID = "REUSABLE_IF_VALID"
RECHECKABLE_BEFORE_RUNTIME = "RECHECKABLE_BEFORE_RUNTIME"
SINGLE_RUNTIME_ATTEMPT = "SINGLE_RUNTIME_ATTEMPT"

EXECUTION_POLICY = "SEQUENTIAL_ESTIMATORS"
FAILURE_POLICY = "CONTINUE_INDEPENDENT_BLOCK_DEPENDENTS"
STATE_POLICY = "ARTIFACT_DERIVED"
EVENT_POLICY = "APPEND_ONLY"
LOCK_POLICY = "PROCESS_EXCLUSIVE_FLOCK"

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class SuitePlanError(ValueError):
    """Raised when the immutable suite-plan contract cannot be satisfied."""


@dataclass(frozen=True)
class StageDefinition:
    stage_id: str
    dependencies: tuple[str, ...]
    recovery_policy: str
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "dependencies": list(self.dependencies),
            "recovery_policy": self.recovery_policy,
            "priority": self.priority,
        }


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def _algorithm_ids(values: Iterable[str]) -> list[str]:
    result = [str(value) for value in values]
    if not result or any(not value for value in result):
        raise SuitePlanError("suite requires a non-empty ordered algorithm set")
    if len(result) != len(set(result)):
        raise SuitePlanError("suite algorithm set contains duplicates")
    return result


def build_stage_definitions(algorithm_ids: list[str]) -> tuple[StageDefinition, ...]:
    """Materialize the fixed SAME_BAG_MAPPING_V1 stage graph and priority."""
    algorithms = _algorithm_ids(algorithm_ids)
    stages: list[tuple[str, tuple[str, ...], str]] = []

    stages.append(("snapshot", (), REUSABLE_IF_VALID))
    stages.append(("analyze_bag", (), REUSABLE_IF_VALID))

    setup_dependencies = ("snapshot", "analyze_bag")
    for algorithm_id in algorithms:
        stages.append(
            (
                f"preflight/{algorithm_id}",
                setup_dependencies,
                RECHECKABLE_BEFORE_RUNTIME,
            )
        )

    stages.append(("dataset_identity/pre", setup_dependencies, REUSABLE_IF_VALID))

    for algorithm_id in algorithms:
        stages.append(
            (
                f"runtime/{algorithm_id}",
                ("dataset_identity/pre", f"preflight/{algorithm_id}"),
                SINGLE_RUNTIME_ATTEMPT,
            )
        )

    runtime_ids = tuple(f"runtime/{algorithm_id}" for algorithm_id in algorithms)
    stages.append(("dataset_identity/post", runtime_ids, REUSABLE_IF_VALID))

    for algorithm_id in algorithms:
        stages.append(
            (
                f"trajectory/{algorithm_id}",
                ("dataset_identity/post", f"runtime/{algorithm_id}"),
                REUSABLE_IF_VALID,
            )
        )

    trajectory_ids = tuple(f"trajectory/{algorithm_id}" for algorithm_id in algorithms)
    stages.append(("audit/trajectory_timestamps", trajectory_ids, REUSABLE_IF_VALID))
    stages.append(("audit/trajectory_frames", trajectory_ids, REUSABLE_IF_VALID))
    stages.append(
        (
            "audit/runtime_provenance",
            runtime_ids + trajectory_ids + ("audit/trajectory_frames",),
            REUSABLE_IF_VALID,
        )
    )
    stages.append(("audit/trajectory_coverage", trajectory_ids, REUSABLE_IF_VALID))
    stages.append(
        (
            "scan_manifest",
            trajectory_ids + ("dataset_identity/post",),
            REUSABLE_IF_VALID,
        )
    )
    stages.append(
        (
            "common_map_manifest",
            ("scan_manifest",) + trajectory_ids,
            REUSABLE_IF_VALID,
        )
    )

    for algorithm_id in algorithms:
        stages.append(
            (
                f"unified_map/{algorithm_id}",
                ("common_map_manifest", f"trajectory/{algorithm_id}"),
                REUSABLE_IF_VALID,
            )
        )

    stages.append(
        (
            "relative_se3",
            trajectory_ids
            + (
                "audit/trajectory_timestamps",
                "audit/trajectory_frames",
                "audit/runtime_provenance",
            ),
            REUSABLE_IF_VALID,
        )
    )

    unified_ids = tuple(f"unified_map/{algorithm_id}" for algorithm_id in algorithms)
    stages.append(
        (
            "same_bag_summary",
            runtime_ids
            + trajectory_ids
            + unified_ids
            + (
                "relative_se3",
                "audit/trajectory_timestamps",
                "audit/trajectory_frames",
                "audit/runtime_provenance",
                "audit/trajectory_coverage",
            ),
            REUSABLE_IF_VALID,
        )
    )

    return tuple(
        StageDefinition(stage_id, dependencies, recovery_policy, index)
        for index, (stage_id, dependencies, recovery_policy) in enumerate(stages, start=1)
    )


def _require_sha256(value: Any, *, reason: str) -> str:
    text = str(value or "")
    if not _SHA256_RE.fullmatch(text):
        raise SuitePlanError(reason)
    return text.lower()


def build_suite_plan(
    run: Path,
    manifest: dict[str, Any],
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic immutable plan from one already-frozen run manifest."""
    run = Path(run).resolve()
    manifest_path = run / "manifest.json"
    if not manifest_path.is_file():
        raise SuitePlanError(f"missing frozen run manifest: {manifest_path}")
    if not isinstance(manifest, dict):
        raise SuitePlanError("frozen run manifest must be an object")

    algorithms_value = manifest.get("algorithms")
    if not isinstance(algorithms_value, dict):
        raise SuitePlanError("frozen run manifest algorithms must be an object")
    algorithms = _algorithm_ids(algorithms_value.keys())

    dataset = manifest.get("dataset")
    if not isinstance(dataset, dict):
        raise SuitePlanError("frozen run manifest dataset must be an object")
    bag_dir = str(dataset.get("bag_dir", "")).strip()
    if not bag_dir:
        raise SuitePlanError("frozen run dataset bag_dir is required")
    dataset_sha = _require_sha256(
        dataset.get("sha256"),
        reason="BLOCKED_INPUT_IDENTITY_UNAVAILABLE: dataset.sha256 must be a frozen 64-hex SHA-256",
    )

    stages = build_stage_definitions(algorithms)
    plan = {
        "schema": SUITE_PLAN_SCHEMA,
        "profile": SUITE_PROFILE,
        "created_at": str(created_at or _now_iso()),
        "run_id": str(manifest.get("run_id", run.name)),
        "run_dir": str(run),
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "dataset": {
            "dataset_id": str(dataset.get("dataset_id", "UNKNOWN")),
            "bag_dir": str(Path(bag_dir).expanduser().resolve()),
            "expected_bag_content_sha256": dataset_sha,
        },
        "selected_algorithms": algorithms,
        "execution_policy": EXECUTION_POLICY,
        "failure_policy": FAILURE_POLICY,
        "state_policy": STATE_POLICY,
        "event_policy": EVENT_POLICY,
        "lock_policy": LOCK_POLICY,
        "stages": [stage.to_dict() for stage in stages],
    }
    validate_suite_plan_payload(plan)
    return plan


def validate_suite_plan_payload(payload: dict[str, Any]) -> None:
    """Validate plan structure and that the expanded DAG matches selected order."""
    if not isinstance(payload, dict):
        raise SuitePlanError("suite plan root must be an object")
    if payload.get("schema") != SUITE_PLAN_SCHEMA:
        raise SuitePlanError("invalid suite plan schema")
    if payload.get("profile") != SUITE_PROFILE:
        raise SuitePlanError("invalid suite profile")

    for key, expected in (
        ("execution_policy", EXECUTION_POLICY),
        ("failure_policy", FAILURE_POLICY),
        ("state_policy", STATE_POLICY),
        ("event_policy", EVENT_POLICY),
        ("lock_policy", LOCK_POLICY),
    ):
        if payload.get(key) != expected:
            raise SuitePlanError(f"invalid suite plan {key}")

    created_at = payload.get("created_at")
    run_id = payload.get("run_id")
    if not isinstance(created_at, str) or not created_at:
        raise SuitePlanError("suite plan created_at is required")
    if not isinstance(run_id, str) or not run_id:
        raise SuitePlanError("suite plan run_id is required")

    run_dir = Path(str(payload.get("run_dir", "")))
    manifest_path = Path(str(payload.get("manifest_path", "")))
    if not run_dir.is_absolute():
        raise SuitePlanError("suite plan run_dir must be absolute")
    if not manifest_path.is_absolute() or manifest_path != run_dir / "manifest.json":
        raise SuitePlanError("suite plan manifest_path must be the run-local manifest")
    _require_sha256(payload.get("manifest_sha256"), reason="invalid suite plan manifest_sha256")

    dataset = payload.get("dataset")
    if not isinstance(dataset, dict):
        raise SuitePlanError("suite plan dataset must be an object")
    if not str(dataset.get("dataset_id", "")):
        raise SuitePlanError("suite plan dataset_id is required")
    bag_dir = Path(str(dataset.get("bag_dir", "")))
    if not bag_dir.is_absolute():
        raise SuitePlanError("suite plan dataset bag_dir must be absolute")
    _require_sha256(
        dataset.get("expected_bag_content_sha256"),
        reason="BLOCKED_INPUT_IDENTITY_UNAVAILABLE: suite plan dataset identity is invalid",
    )

    selected = payload.get("selected_algorithms")
    if not isinstance(selected, list):
        raise SuitePlanError("suite plan selected_algorithms must be an ordered list")
    algorithms = _algorithm_ids(selected)

    stages = payload.get("stages")
    if not isinstance(stages, list):
        raise SuitePlanError("suite plan stages must be a list")
    expected_stages = [stage.to_dict() for stage in build_stage_definitions(algorithms)]
    if stages != expected_stages:
        raise SuitePlanError("suite plan stages do not match the frozen selected-algorithm order")


def write_suite_plan(run: Path, payload: dict[str, Any]) -> Path:
    """Write a validated plan exactly once."""
    validate_suite_plan_payload(payload)
    run = Path(run).resolve()
    if payload.get("run_dir") != str(run):
        raise SuitePlanError("suite plan run_dir does not match output run")
    path = run / "metadata" / "suite" / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise SuitePlanError(f"refusing to overwrite existing suite plan: {path}") from exc
    return path


def validate_manifest_fingerprint(run: Path, plan: dict[str, Any]) -> None:
    """Fail closed if the frozen run manifest changed after plan creation."""
    run = Path(run).resolve()
    manifest_path = run / "manifest.json"
    expected = _require_sha256(
        plan.get("manifest_sha256"),
        reason="FAIL_MANIFEST_MUTATION: suite plan manifest fingerprint is invalid",
    )
    if not manifest_path.is_file():
        raise SuitePlanError(f"FAIL_MANIFEST_MUTATION: missing frozen run manifest: {manifest_path}")
    observed = sha256_file(manifest_path)
    if observed != expected:
        raise SuitePlanError(
            "FAIL_MANIFEST_MUTATION: frozen run manifest SHA-256 no longer matches suite plan"
        )


def load_and_validate_suite_plan(run: Path) -> dict[str, Any]:
    """Load one suite-managed run plan and validate its immutable lineage."""
    run = Path(run).resolve()
    path = run / "metadata" / "suite" / "plan.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SuitePlanError(f"not a suite-managed run; missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise SuitePlanError(f"invalid suite plan JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SuitePlanError("suite plan root must be an object")
    validate_suite_plan_payload(payload)
    if payload.get("run_dir") != str(run):
        raise SuitePlanError("suite plan run_dir does not match current run")
    validate_manifest_fingerprint(run, payload)
    return payload
