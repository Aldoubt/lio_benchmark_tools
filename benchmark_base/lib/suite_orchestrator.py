#!/usr/bin/env python3
"""Execution helpers for Benchmark Suite Orchestrator V1."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
from typing import Any, Literal

from benchmark_base.lib.bag_probe import build_bag_identity


DATASET_IDENTITY_SCHEMA = "lio_benchmark_suite_dataset_identity/v1"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class SuiteOrchestratorError(RuntimeError):
    """Typed fail-closed orchestration error."""

    def __init__(self, reason_code: str, detail: str):
        self.reason_code = str(reason_code)
        self.detail = str(detail)
        super().__init__(f"{self.reason_code}: {self.detail}")


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
