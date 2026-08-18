#!/usr/bin/env python3
"""Execution engine for Benchmark Suite Orchestrator V1."""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from typing import Any, Callable, Literal, Sequence
import uuid

from benchmark_base.lib.bag_probe import build_bag_identity
from benchmark_base.lib.manifest import sha256_file
from benchmark_base.lib.suite_events import SuiteEventError, SuiteExecutionLock, append_event
from benchmark_base.lib.suite_plan import build_stage_definitions, load_and_validate_suite_plan
from benchmark_base.lib.suite_status import (
    BLOCKED,
    BLOCKED_ENVIRONMENT,
    FAIL,
    FAIL_ALGORITHM,
    PASS,
    READY,
    derive_suite_status,
)


MODULE_ROOT = Path(__file__).resolve().parents[2]
DATASET_IDENTITY_SCHEMA = "lio_benchmark_suite_dataset_identity/v1"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class SuiteOrchestratorError(RuntimeError):
    """Typed fail-closed orchestration error."""

    def __init__(self, reason_code: str, detail: str):
        self.reason_code = str(reason_code)
        self.detail = str(detail)
        super().__init__(f"{self.reason_code}: {self.detail}")


@dataclass(frozen=True)
class StageCommand:
    stage_id: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class OrchestratorResult:
    run: Path
    state: str
    exit_code: int
    started_stage_ids: tuple[str, ...]
    stop_reason: str | None


class StopController:
    """Record only the first graceful-stop request."""

    def __init__(self) -> None:
        self._signum: int | None = None

    @property
    def requested(self) -> bool:
        return self._signum is not None

    @property
    def signum(self) -> int | None:
        return self._signum

    @property
    def exit_code(self) -> int | None:
        return None if self._signum is None else 128 + int(self._signum)

    def request(self, signum: int) -> None:
        if self._signum is None:
            self._signum = int(signum)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def _identity_path(run: Path, phase: Literal["pre", "post"]) -> Path:
    return Path(run).resolve() / "metadata" / "suite" / f"dataset_identity_{phase}.json"


def _expected_identity(plan: dict[str, Any]) -> tuple[Path, str]:
    dataset = plan.get("dataset")
    if not isinstance(dataset, dict):
        raise SuiteOrchestratorError("BLOCKED_INPUT_IDENTITY_UNAVAILABLE", "suite plan dataset is missing")
    bag_dir = Path(str(dataset.get("bag_dir", ""))).expanduser()
    expected = str(dataset.get("expected_bag_content_sha256", ""))
    if not bag_dir.is_absolute() or not _SHA256_RE.fullmatch(expected):
        raise SuiteOrchestratorError(
            "BLOCKED_INPUT_IDENTITY_UNAVAILABLE",
            "suite plan requires absolute bag_dir and frozen 64-hex content SHA-256",
        )
    return bag_dir.resolve(), expected.lower()


def _write_identity_once(path: Path, payload: dict[str, Any]) -> Path:
    if path.exists():
        raise SuiteOrchestratorError(
            "FAIL_PARTIAL_ARTIFACT",
            f"refusing to overwrite existing suite dataset identity evidence: {path}",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    if pending.exists():
        raise SuiteOrchestratorError(
            "FAIL_PARTIAL_ARTIFACT",
            f"stale pending suite dataset identity artifact exists: {pending}",
        )
    try:
        with pending.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if path.exists():
            raise SuiteOrchestratorError(
                "FAIL_PARTIAL_ARTIFACT",
                f"suite dataset identity target appeared during write: {path}",
            )
        os.replace(pending, path)
    except Exception:
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SuiteOrchestratorError("BLOCKED_DEPENDENCY", f"missing dataset identity evidence: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", f"invalid dataset identity JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", f"dataset identity root is not an object: {path}")
    return value


def validate_dataset_identity_record(
    run: Path,
    plan: dict[str, Any],
    phase: Literal["pre", "post"],
) -> dict[str, Any]:
    """Validate one already-frozen identity record without rehashing the bag."""
    path = _identity_path(run, phase)
    payload = _load_object(path)
    bag_dir, expected = _expected_identity(plan)
    if payload.get("schema") != DATASET_IDENTITY_SCHEMA:
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", "invalid dataset identity schema")
    if payload.get("phase") != phase:
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", "dataset identity phase mismatch")
    if payload.get("bag_dir") != str(bag_dir):
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", "dataset identity bag_dir differs from suite plan")
    if payload.get("expected_bag_content_sha256") != expected:
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", "dataset identity expected SHA differs from suite plan")
    observed = payload.get("observed_bag_content_sha256")
    if not isinstance(observed, str) or not _SHA256_RE.fullmatch(observed):
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", "dataset identity observed SHA is invalid")
    if not isinstance(payload.get("storage_files"), list):
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", "dataset identity storage fingerprints are missing")
    metadata = payload.get("metadata_yaml")
    if metadata is not None and not isinstance(metadata, dict):
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", "dataset identity metadata fingerprint is invalid")
    status = payload.get("status")
    if status == "PASS":
        if observed != expected:
            raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", "PASS identity record does not match expected SHA")
        if phase == "post":
            pre = validate_dataset_identity_record(run, plan, "pre")
            pre_observed = pre["observed_bag_content_sha256"]
            if payload.get("pre_observed_bag_content_sha256") != pre_observed or observed != pre_observed:
                raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", "post identity does not match frozen pre identity")
    elif status == "FAIL":
        if payload.get("reason_code") != "FAIL_INPUT_MUTATION":
            raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", "failed identity record lacks FAIL_INPUT_MUTATION")
    else:
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", f"unsupported dataset identity status: {status}")
    return payload


def capture_dataset_identity(
    run: Path,
    plan: dict[str, Any],
    phase: Literal["pre", "post"],
    *,
    captured_at: str | None = None,
) -> Path:
    """Hash the source bag with P1 semantics and freeze one pre/post gate record."""
    if phase not in ("pre", "post"):
        raise SuiteOrchestratorError("FAIL_ARTIFACT_INVALID", f"unsupported dataset identity phase: {phase}")
    path = _identity_path(run, phase)
    if path.exists():
        raise SuiteOrchestratorError(
            "FAIL_PARTIAL_ARTIFACT",
            f"refusing to overwrite existing suite dataset identity evidence: {path}",
        )
    bag_dir, expected = _expected_identity(plan)
    pre_observed: str | None = None
    if phase == "post":
        pre = validate_dataset_identity_record(run, plan, "pre")
        if pre.get("status") != "PASS":
            raise SuiteOrchestratorError("BLOCKED_DEPENDENCY", "post identity requires a PASS pre identity")
        pre_observed = str(pre["observed_bag_content_sha256"])

    try:
        identity = build_bag_identity(bag_dir)
    except ValueError as exc:
        raise SuiteOrchestratorError("FAIL_INPUT_MUTATION", str(exc)) from exc
    observed = str(identity["bag_content_sha256"])
    matches_expected = observed == expected
    matches_pre = phase == "pre" or observed == pre_observed
    passed = matches_expected and matches_pre
    payload: dict[str, Any] = {
        "schema": DATASET_IDENTITY_SCHEMA,
        "phase": phase,
        "captured_at": str(captured_at or _now_iso()),
        "bag_dir": str(bag_dir),
        "expected_bag_content_sha256": expected,
        "observed_bag_content_sha256": observed,
        "metadata_yaml": identity.get("metadata_yaml"),
        "storage_files": identity.get("storage_files", []),
        "status": "PASS" if passed else "FAIL",
        "reason_code": None if passed else "FAIL_INPUT_MUTATION",
    }
    if phase == "post":
        payload["pre_observed_bag_content_sha256"] = pre_observed
    _write_identity_once(path, payload)
    if not passed:
        raise SuiteOrchestratorError(
            "FAIL_INPUT_MUTATION",
            "source bag content identity differs from the frozen suite dataset contract",
        )
    validate_dataset_identity_record(run, plan, phase)
    return path


def build_stage_command(
    run: Path,
    plan: dict[str, Any],
    stage_id: str,
    cli_path: Path,
) -> StageCommand | None:
    """Map one suite stage to the already-public benchmark CLI without overrides."""
    run = Path(run).resolve()
    cli = str(Path(cli_path))
    prefix = (sys.executable, cli)
    algorithms = tuple(str(value) for value in plan["selected_algorithms"])
    if stage_id == "snapshot":
        argv = prefix + ("snapshot", "--run", str(run))
    elif stage_id == "analyze_bag":
        argv = prefix + ("analyze-bag", "--run", str(run))
    elif stage_id.startswith("preflight/"):
        algorithm_id = stage_id.split("/", 1)[1]
        argv = prefix + ("preflight", "--run", str(run), "--algorithm", algorithm_id)
    elif stage_id in {"dataset_identity/pre", "dataset_identity/post"}:
        return None
    elif stage_id.startswith("runtime/"):
        algorithm_id = stage_id.split("/", 1)[1]
        argv = prefix + ("run", "--run", str(run), "--algorithm", algorithm_id)
    elif stage_id.startswith("trajectory/"):
        algorithm_id = stage_id.split("/", 1)[1]
        argv = prefix + (
            "standardize",
            "trajectory-from-run",
            "--run",
            str(run),
            "--algorithm",
            algorithm_id,
        )
    elif stage_id == "audit/trajectory_timestamps":
        argv = prefix + ("audit", "trajectory-timestamps", "--run", str(run), "--algorithms", *algorithms)
    elif stage_id == "audit/trajectory_frames":
        argv = prefix + ("audit", "trajectory-frames", "--run", str(run), "--algorithms", *algorithms)
    elif stage_id == "audit/runtime_provenance":
        argv = prefix + ("audit", "runtime-provenance", "--run", str(run), "--algorithms", *algorithms)
    elif stage_id == "audit/trajectory_coverage":
        argv = prefix + ("audit", "trajectory-coverage", "--run", str(run), "--algorithms", *algorithms)
    elif stage_id == "scan_manifest":
        argv = prefix + ("standardize", "scan-manifest", "--run", str(run))
    elif stage_id == "common_map_manifest":
        argv = prefix + ("standardize", "common-map-manifest", "--run", str(run))
    elif stage_id.startswith("unified_map/"):
        algorithm_id = stage_id.split("/", 1)[1]
        argv = prefix + ("standardize", "map", "--run", str(run), "--algorithm", algorithm_id)
    elif stage_id == "relative_se3":
        argv = prefix + ("compare", "relative-se3", "--run", str(run), "--algorithms", *algorithms)
    elif stage_id == "same_bag_summary":
        argv = prefix + ("summarize", "same-bag", "--run", str(run))
    else:
        raise SuiteOrchestratorError("FAIL_COMMAND", f"no command contract for suite stage: {stage_id}")
    return StageCommand(stage_id=stage_id, argv=tuple(str(value) for value in argv))


def _default_command_runner(argv: Sequence[str]) -> int:
    return subprocess.run(list(argv), cwd=MODULE_ROOT, check=False).returncode


def _stage_state(status, stage_id: str):
    return next(stage for stage in status.stages if stage.stage_id == stage_id)


def _has_terminal_preflight_failure(status) -> bool:
    preflights = [stage for stage in status.stages if stage.stage_id.startswith("preflight/")]
    return any(stage.state == FAIL for stage in preflights)


def _has_terminal_runtime_failure(status) -> bool:
    runtimes = [stage for stage in status.stages if stage.stage_id.startswith("runtime/")]
    return any(stage.state == FAIL and stage.reason_code == FAIL_ALGORITHM for stage in runtimes)


def _next_safe_stage(
    run: Path,
    plan: dict[str, Any],
    status,
    attempted: set[str],
) -> str | None:
    states = {stage.stage_id: stage for stage in status.stages}
    definitions = build_stage_definitions(list(plan["selected_algorithms"]))

    # A terminal preflight contract failure permits the remaining preflight observations,
    # but no input hash/runtime work is started afterward.
    terminal_preflight = _has_terminal_preflight_failure(status)
    terminal_runtime = _has_terminal_runtime_failure(status)
    post_state = states["dataset_identity/post"]

    for definition in definitions:
        stage_id = definition.stage_id
        state = states[stage_id]
        if stage_id in attempted:
            continue
        if terminal_preflight and not stage_id.startswith("preflight/"):
            return None
        if terminal_runtime and post_state.state == PASS and not stage_id.startswith("runtime/"):
            return None
        if state.state == READY:
            return stage_id
        if (
            definition.recovery_policy == "RECHECKABLE_BEFORE_RUNTIME"
            and state.state == BLOCKED
            and state.reason_code == BLOCKED_ENVIRONMENT
        ):
            algorithm_id = stage_id.split("/", 1)[1]
            identity = run / "metadata" / "algorithms" / algorithm_id / "runtime_identity.json"
            if not identity.exists():
                return stage_id
    return None


def _execute_one_stage(
    run: Path,
    plan: dict[str, Any],
    stage_id: str,
    cli_path: Path,
    runner: Callable[[Sequence[str]], int],
) -> tuple[int, list[str] | None, SuiteOrchestratorError | None]:
    if stage_id == "dataset_identity/pre":
        try:
            capture_dataset_identity(run, plan, "pre")
            return 0, None, None
        except SuiteOrchestratorError as exc:
            return 1, None, exc
    if stage_id == "dataset_identity/post":
        try:
            capture_dataset_identity(run, plan, "post")
            return 0, None, None
        except SuiteOrchestratorError as exc:
            return 1, None, exc
    command = build_stage_command(run, plan, stage_id, cli_path)
    if command is None:
        return 1, None, SuiteOrchestratorError("FAIL_COMMAND", f"stage has no executor: {stage_id}")
    try:
        return int(runner(command.argv)), list(command.argv), None
    except (OSError, RuntimeError, ValueError) as exc:
        return 1, list(command.argv), SuiteOrchestratorError("FAIL_COMMAND", str(exc))


def execute_suite(
    run: Path,
    *,
    cli_path: Path,
    command_runner: Callable[[Sequence[str]], int] | None = None,
    install_signal_handlers: bool = True,
    stop_controller: StopController | None = None,
) -> OrchestratorResult:
    """Execute only artifact-ready safe work and preserve append-only lineage."""
    run = Path(run).resolve()
    plan = load_and_validate_suite_plan(run)
    plan_sha = sha256_file(run / "metadata" / "suite" / "plan.json")
    runner = command_runner or _default_command_runner
    controller = stop_controller or StopController()
    started: list[str] = []
    attempted: set[str] = set()
    invocation_id = str(uuid.uuid4())
    invocation_error: SuiteOrchestratorError | None = None
    interrupted_stage: str | None = None

    previous_handlers: dict[int, Any] = {}

    def _handler(signum: int, _frame: object) -> None:
        controller.request(signum)

    if install_signal_handlers:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[int(signum)] = signal.getsignal(signum)
            signal.signal(signum, _handler)

    try:
        with SuiteExecutionLock(run):
            append_event(
                run,
                invocation_id=invocation_id,
                event_type="SUITE_INVOCATION_STARTED",
                stage_id=None,
                plan_sha256=plan_sha,
            )
            while True:
                status = derive_suite_status(run)
                stage_id = _next_safe_stage(run, plan, status, attempted)
                if controller.requested or stage_id is None:
                    break
                attempted.add(stage_id)
                command = build_stage_command(run, plan, stage_id, cli_path)
                command_list = None if command is None else list(command.argv)
                append_event(
                    run,
                    invocation_id=invocation_id,
                    event_type="STAGE_STARTED",
                    stage_id=stage_id,
                    plan_sha256=plan_sha,
                    command=command_list,
                )
                started.append(stage_id)
                returncode, _, error = _execute_one_stage(run, plan, stage_id, cli_path, runner)
                if error is not None:
                    invocation_error = error
                observed_status = derive_suite_status(run)
                observed = _stage_state(observed_status, stage_id)
                append_event(
                    run,
                    invocation_id=invocation_id,
                    event_type="STAGE_FINISHED",
                    stage_id=stage_id,
                    plan_sha256=plan_sha,
                    command=command_list,
                    returncode=returncode,
                    observed_state=observed.state,
                    reason_code=observed.reason_code or (error.reason_code if error else None),
                )
                if controller.requested:
                    interrupted_stage = stage_id
                    append_event(
                        run,
                        invocation_id=invocation_id,
                        event_type="SUITE_STOP_REQUESTED",
                        stage_id=stage_id,
                        plan_sha256=plan_sha,
                        reason_code="INTERRUPTED_AT_STAGE_BOUNDARY",
                    )
                    break
                # If a command returned without creating any authoritative evidence,
                # never spin/retry it inside the same invocation. Other safe stages may continue.

            final_status = derive_suite_status(run)
            stop_reason = "INTERRUPTED_AT_STAGE_BOUNDARY" if controller.requested else None
            append_event(
                run,
                invocation_id=invocation_id,
                event_type="SUITE_INVOCATION_FINISHED",
                stage_id=None,
                plan_sha256=plan_sha,
                observed_state=final_status.state,
                reason_code=stop_reason or (invocation_error.reason_code if invocation_error else None),
            )
    except SuiteEventError as exc:
        if "BLOCKED_EXECUTOR_LOCKED" not in str(exc):
            raise
        return OrchestratorResult(
            run=run,
            state=BLOCKED,
            exit_code=2,
            started_stage_ids=(),
            stop_reason="BLOCKED_EXECUTOR_LOCKED",
        )
    finally:
        if install_signal_handlers:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)

    final_status = derive_suite_status(run)
    if controller.requested:
        exit_code = controller.exit_code or 1
        stop_reason = f"INTERRUPTED_AT_STAGE_BOUNDARY:{interrupted_stage or 'between_stages'}"
    elif invocation_error is not None and final_status.state not in {PASS, BLOCKED, FAIL}:
        exit_code = 1
        stop_reason = invocation_error.reason_code
    elif final_status.state == PASS:
        exit_code = 0
        stop_reason = None
    elif final_status.state == BLOCKED:
        exit_code = 2
        stop_reason = "BLOCKED"
    elif final_status.state == FAIL:
        exit_code = 1
        stop_reason = invocation_error.reason_code if invocation_error else "FAIL"
    else:
        exit_code = 2
        stop_reason = final_status.state
    return OrchestratorResult(
        run=run,
        state=final_status.state,
        exit_code=exit_code,
        started_stage_ids=tuple(started),
        stop_reason=stop_reason,
    )
