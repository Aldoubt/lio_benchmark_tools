#!/usr/bin/env python3
"""Append-only operational lineage and executor lock for benchmark suites."""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
from typing import Any


SUITE_EVENT_SCHEMA = "lio_benchmark_suite_event/v1"
EVENT_TYPES = frozenset(
    {
        "SUITE_INVOCATION_STARTED",
        "STAGE_STARTED",
        "STAGE_FINISHED",
        "STAGE_SKIPPED_VALID",
        "STAGE_BLOCKED",
        "SUITE_STOP_REQUESTED",
        "SUITE_INVOCATION_FINISHED",
    }
)
_EVENT_FILE_RE = re.compile(r"^(\d{6})\.json$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class SuiteEventError(ValueError):
    """Raised when event lineage or executor-lock contracts are violated."""


@dataclass(frozen=True)
class LockObservation:
    locked: bool
    active_invocation_id: str | None
    active_stage_id: str | None


def validate_event_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise SuiteEventError("suite event root must be an object")
    if payload.get("schema") != SUITE_EVENT_SCHEMA:
        raise SuiteEventError("invalid suite event schema")
    event_id = payload.get("event_id")
    if not isinstance(event_id, int) or event_id <= 0:
        raise SuiteEventError("suite event_id must be a positive integer")
    invocation_id = payload.get("invocation_id")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise SuiteEventError("suite invocation_id is required")
    event_type = payload.get("event_type")
    if event_type not in EVENT_TYPES:
        raise SuiteEventError(f"unsupported suite event_type: {event_type}")
    stage_id = payload.get("stage_id")
    if event_type.startswith("STAGE_") and (not isinstance(stage_id, str) or not stage_id):
        raise SuiteEventError(f"{event_type} requires stage_id")
    if stage_id is not None and not isinstance(stage_id, str):
        raise SuiteEventError("suite event stage_id must be string or null")
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        raise SuiteEventError("suite event timestamp is required")
    plan_sha = payload.get("plan_sha256")
    if not isinstance(plan_sha, str) or not _SHA256_RE.fullmatch(plan_sha):
        raise SuiteEventError("suite event plan_sha256 must be 64 hex characters")
    command = payload.get("command")
    if command is not None and (
        not isinstance(command, list) or any(not isinstance(value, str) for value in command)
    ):
        raise SuiteEventError("suite event command must be a string list or null")
    returncode = payload.get("returncode")
    if returncode is not None and not isinstance(returncode, int):
        raise SuiteEventError("suite event returncode must be integer or null")
    observed_state = payload.get("observed_state")
    if observed_state is not None and not isinstance(observed_state, str):
        raise SuiteEventError("suite event observed_state must be string or null")
    reason_code = payload.get("reason_code")
    if reason_code is not None and not isinstance(reason_code, str):
        raise SuiteEventError("suite event reason_code must be string or null")


def _event_directory(run: Path) -> Path:
    return Path(run).resolve() / "metadata" / "suite" / "events"


def read_events(run: Path) -> tuple[dict[str, Any], ...]:
    directory = _event_directory(run)
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise SuiteEventError(f"suite event path is not a directory: {directory}")
    files = sorted(directory.glob("*.json"))
    events: list[dict[str, Any]] = []
    for expected_id, path in enumerate(files, start=1):
        match = _EVENT_FILE_RE.fullmatch(path.name)
        if match is None:
            raise SuiteEventError(f"invalid suite event filename: {path.name}")
        filename_id = int(match.group(1))
        if filename_id != expected_id:
            raise SuiteEventError(
                f"suite event ledger is not contiguous: expected {expected_id:06d}.json, got {path.name}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SuiteEventError(f"invalid suite event JSON: {path}: {exc}") from exc
        validate_event_payload(payload)
        if payload["event_id"] != filename_id:
            raise SuiteEventError(
                f"suite event filename/event_id mismatch: {path.name} != {payload['event_id']}"
            )
        events.append(payload)
    return tuple(events)


def append_event(
    run: Path,
    *,
    invocation_id: str,
    event_type: str,
    stage_id: str | None,
    plan_sha256: str,
    command: list[str] | None = None,
    returncode: int | None = None,
    observed_state: str | None = None,
    reason_code: str | None = None,
    timestamp: str | None = None,
) -> Path:
    """Append one event with exclusive-create semantics; never rewrite history."""
    if timestamp is None:
        import datetime as dt

        timestamp = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
    existing = read_events(run)
    event_id = len(existing) + 1
    payload = {
        "schema": SUITE_EVENT_SCHEMA,
        "event_id": event_id,
        "invocation_id": invocation_id,
        "event_type": event_type,
        "stage_id": stage_id,
        "timestamp": timestamp,
        "plan_sha256": plan_sha256,
        "command": command,
        "returncode": returncode,
        "observed_state": observed_state,
        "reason_code": reason_code,
    }
    validate_event_payload(payload)
    directory = _event_directory(run)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{event_id:06d}.json"
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise SuiteEventError(f"refusing to overwrite suite event: {target}") from exc
    return target


class SuiteExecutionLock:
    """One nonblocking kernel flock for a suite executor invocation."""

    def __init__(self, run: Path):
        self.run = Path(run).resolve()
        self.path = self.run / "metadata" / "suite" / "suite.lock"
        self._stream = None

    def __enter__(self) -> "SuiteExecutionLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.close()
            raise SuiteEventError(
                f"BLOCKED_EXECUTOR_LOCKED: another suite executor owns {self.path}"
            ) from exc
        self._stream = stream
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._stream is None:
            return
        try:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._stream.close()
            self._stream = None


def _active_lineage(events: tuple[dict[str, Any], ...]) -> tuple[str | None, str | None]:
    active_invocation: str | None = None
    active_stage: str | None = None
    for event in events:
        event_type = event["event_type"]
        invocation_id = event["invocation_id"]
        if event_type == "SUITE_INVOCATION_STARTED":
            active_invocation = invocation_id
            active_stage = None
            continue
        if invocation_id != active_invocation:
            continue
        if event_type == "STAGE_STARTED":
            active_stage = event["stage_id"]
        elif event_type in {"STAGE_FINISHED", "STAGE_BLOCKED", "STAGE_SKIPPED_VALID"}:
            if event.get("stage_id") == active_stage:
                active_stage = None
        elif event_type == "SUITE_INVOCATION_FINISHED":
            active_invocation = None
            active_stage = None
    return active_invocation, active_stage


def observe_execution(run: Path) -> LockObservation:
    """Probe an existing lock without creating or mutating it."""
    run = Path(run).resolve()
    path = run / "metadata" / "suite" / "suite.lock"
    if not path.exists():
        return LockObservation(False, None, None)
    try:
        descriptor = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return LockObservation(False, None, None)
    locked = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            locked = True
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
    if not locked:
        return LockObservation(False, None, None)
    invocation_id, stage_id = _active_lineage(read_events(run))
    return LockObservation(True, invocation_id, stage_id)
