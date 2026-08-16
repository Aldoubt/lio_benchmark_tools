#!/usr/bin/env python3
"""Runtime implementation provenance classification for benchmark baselines.

The helpers here do not discover a local workspace themselves. They classify
facts collected by an evaluator so a formal run cannot silently mix a declared
implementation with a different package/source tree or frame contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from benchmark_base.lib.trajectory_semantics import classify_frame_audit


class ProvenanceStatus(str, Enum):
    MATCH = "MATCH"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"
    FRAME_CONTRACT_MISMATCH = "FRAME_CONTRACT_MISMATCH"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ProvenanceClassification:
    status: ProvenanceStatus
    reasons: tuple[str, ...]


def normalize_github_repository(remote: str | None) -> str | None:
    """Normalize common GitHub remote forms to ``owner/repository``."""
    if remote is None:
        return None
    value = remote.strip()
    if not value:
        return None

    if value.startswith("git@github.com:"):
        path = value.split(":", 1)[1]
    elif value.startswith("ssh://git@github.com/"):
        path = value[len("ssh://git@github.com/") :]
    else:
        parsed = urlparse(value)
        if parsed.hostname not in {"github.com", "www.github.com"}:
            return None
        path = parsed.path.lstrip("/")

    if path.endswith(".git"):
        path = path[:-4]
    parts = [part for part in path.split("/") if part]
    if len(parts) != 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def _normalize_expected_repository(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_github_repository(value)
    if normalized is not None:
        return normalized
    stripped = value.strip().strip("/")
    if stripped.count("/") == 1 and all(stripped.split("/")):
        return stripped.removesuffix(".git")
    return None


def classify_runtime_provenance(
    *,
    expected_repository: str | None,
    actual_repository: str | None,
    frame_status: str,
    ros_package_prefix: str | None,
) -> ProvenanceClassification:
    """Classify whether a runtime implementation matches the frozen contract."""
    expected = _normalize_expected_repository(expected_repository)
    actual = normalize_github_repository(actual_repository)

    unresolved: list[str] = []
    if expected is None:
        unresolved.append("declared execution repository is unavailable")
    if not ros_package_prefix:
        unresolved.append("ROS package prefix is unavailable")
    if expected is not None and actual is None:
        unresolved.append("runtime GitHub source repository is unavailable")
    if unresolved:
        return ProvenanceClassification(ProvenanceStatus.UNRESOLVED, tuple(unresolved))

    if actual != expected:
        return ProvenanceClassification(
            ProvenanceStatus.SOURCE_MISMATCH,
            (f"source repository mismatch: expected={expected} actual={actual}",),
        )

    if frame_status != "MATCH":
        return ProvenanceClassification(
            ProvenanceStatus.FRAME_CONTRACT_MISMATCH,
            (f"runtime frame contract status is {frame_status}",),
        )

    return ProvenanceClassification(ProvenanceStatus.MATCH, ())


def build_runtime_provenance_record(
    *,
    algorithm: dict[str, Any],
    frame_audit: dict[str, Any],
    ros_package_prefix: str | None,
    source_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Combine frozen algorithm semantics with runtime facts into one record."""
    implementation = algorithm.get("execution_implementation", {})
    if not isinstance(implementation, dict):
        implementation = {}
    contract = algorithm.get("trajectory_contract", {})
    frame_result = classify_frame_audit(contract, frame_audit)
    source_state = source_state or {}

    expected_repository = implementation.get("repository")
    remote_origin = source_state.get("remote_origin")
    classification = classify_runtime_provenance(
        expected_repository=str(expected_repository) if expected_repository else None,
        actual_repository=str(remote_origin) if remote_origin else None,
        frame_status=frame_result.status.value,
        ros_package_prefix=ros_package_prefix,
    )

    return {
        "algorithm_id": str(algorithm.get("algorithm_id", "")),
        "status": classification.status.value,
        "reasons": list(classification.reasons),
        "frame_contract_status": frame_result.status.value,
        "frame_contract_reasons": list(frame_result.reasons),
        "tracked_frame_physical": contract.get("tracked_frame_physical", "UNKNOWN"),
        "world_gauge": contract.get("world_gauge", "UNKNOWN"),
        "expected_execution_repository": _normalize_expected_repository(
            str(expected_repository) if expected_repository else None
        ),
        "actual_execution_repository": normalize_github_repository(
            str(remote_origin) if remote_origin else None
        ),
        "execution_package": implementation.get("package"),
        "execution_executable": implementation.get("executable"),
        "ros_package_prefix": ros_package_prefix,
        "source_path": source_state.get("path"),
        "source_remote_origin": remote_origin,
        "source_commit": source_state.get("commit"),
        "source_branch": source_state.get("branch"),
        "source_dirty": source_state.get("dirty"),
    }
