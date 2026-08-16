#!/usr/bin/env python3
"""Runtime implementation provenance classification for benchmark baselines.

The helpers here classify facts collected by an evaluator so a formal run
cannot silently mix a declared implementation with a different package/source
tree or frame contract. New runs prefer the identity frozen immediately before
estimator startup; historical runs retain explicit reconstructed provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
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


def workspace_from_package_prefix(prefix: str | None) -> Path | None:
    """Recover a colcon workspace root from an install-space package prefix."""
    if not prefix:
        return None
    path = Path(prefix).expanduser()
    for candidate in (path, *path.parents):
        if candidate.name == "install":
            return candidate.parent
    return None


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


def source_relationship(
    expected_repository: str | None,
    actual_repository: str | None,
) -> str:
    expected = _normalize_expected_repository(expected_repository)
    actual = normalize_github_repository(actual_repository)
    if expected is None or actual is None:
        return "UNKNOWN_SOURCE"
    return "REGISTRY_MATCH" if expected == actual else "REGISTRY_MISMATCH"


def classify_runtime_provenance(
    *,
    expected_repository: str | None,
    actual_repository: str | None,
    frame_status: str,
    ros_package_prefix: str | None,
) -> ProvenanceClassification:
    """Classify legacy reconstructed runtime evidence against registry contract."""
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


def _frozen_identity_classification(
    *,
    identity: dict[str, Any],
    frame_status: str,
    relationship: str,
) -> ProvenanceClassification:
    if str(identity.get("identity_status", "")) != "FROZEN":
        return ProvenanceClassification(
            ProvenanceStatus.UNRESOLVED,
            (f"runtime identity status is {identity.get('identity_status', 'UNKNOWN')}",),
        )
    if not identity.get("executable_sha256") and not identity.get("resolved_executable"):
        # Registry launch identities may not have a hash if no package executable was
        # resolvable. Exact launch command alone is useful, but not sufficient to call
        # the implementation identity resolved.
        return ProvenanceClassification(
            ProvenanceStatus.UNRESOLVED,
            ("frozen runtime identity has no resolved executable fingerprint",),
        )
    if frame_status != "MATCH":
        return ProvenanceClassification(
            ProvenanceStatus.FRAME_CONTRACT_MISMATCH,
            (f"runtime frame contract status is {frame_status}",),
        )
    method = str(identity.get("resolution_method", ""))
    if method == "EXPLICIT_EXECUTABLE_OVERRIDE":
        # A user-selected binary is valid when it is exactly fingerprinted. Its
        # relationship to the registry remains a separate descriptive dimension.
        return ProvenanceClassification(ProvenanceStatus.MATCH, ())
    if relationship == "REGISTRY_MISMATCH":
        return ProvenanceClassification(
            ProvenanceStatus.SOURCE_MISMATCH,
            ("registry-default execution resolved to a different source repository",),
        )
    if relationship == "UNKNOWN_SOURCE":
        return ProvenanceClassification(
            ProvenanceStatus.UNRESOLVED,
            ("registry-default execution source relationship is unknown",),
        )
    return ProvenanceClassification(ProvenanceStatus.MATCH, ())


def build_runtime_provenance_record(
    *,
    algorithm: dict[str, Any],
    frame_audit: dict[str, Any],
    ros_package_prefix: str | None,
    source_state: dict[str, Any] | None,
    runtime_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine algorithm semantics with highest-confidence runtime evidence."""
    implementation = algorithm.get("execution_implementation", {})
    if not isinstance(implementation, dict):
        implementation = {}
    contract = algorithm.get("trajectory_contract", {})
    frame_result = classify_frame_audit(contract, frame_audit)
    expected_repository = implementation.get("repository")

    frozen = (
        runtime_identity
        if isinstance(runtime_identity, dict)
        and str(runtime_identity.get("identity_status", "")) == "FROZEN"
        else None
    )
    if frozen is not None:
        identity_source = frozen.get("source", {})
        identity_source = identity_source if isinstance(identity_source, dict) else {}
        remote_origin = identity_source.get("remote_origin")
        relationship = str(frozen.get("source_relationship", "")).strip() or source_relationship(
            str(expected_repository) if expected_repository else None,
            str(remote_origin) if remote_origin else None,
        )
        runtime_prefix = (
            frozen.get("runtime_package_prefix")
            or frozen.get("ros_package_prefix")
            or ros_package_prefix
        )
        classification = _frozen_identity_classification(
            identity=frozen,
            frame_status=frame_result.status.value,
            relationship=relationship,
        )
        effective_source = identity_source
        evidence_source = "RUNTIME_IDENTITY"
        resolution_method = frozen.get("resolution_method")
        resolved_executable = frozen.get("resolved_executable")
        executable_sha256 = frozen.get("executable_sha256")
        runtime_package = frozen.get("runtime_package") or frozen.get("ros_package")
    else:
        effective_source = source_state or {}
        remote_origin = effective_source.get("remote_origin")
        relationship = source_relationship(
            str(expected_repository) if expected_repository else None,
            str(remote_origin) if remote_origin else None,
        )
        runtime_prefix = ros_package_prefix
        classification = classify_runtime_provenance(
            expected_repository=str(expected_repository) if expected_repository else None,
            actual_repository=str(remote_origin) if remote_origin else None,
            frame_status=frame_result.status.value,
            ros_package_prefix=runtime_prefix,
        )
        evidence_source = "LEGACY_RECONSTRUCTED"
        resolution_method = None
        resolved_executable = None
        executable_sha256 = None
        runtime_package = implementation.get("package")

    return {
        "algorithm_id": str(algorithm.get("algorithm_id", "")),
        "status": classification.status.value,
        "reasons": list(classification.reasons),
        "identity_evidence_source": evidence_source,
        "runtime_identity_status": frozen.get("identity_status") if frozen else None,
        "resolution_method": resolution_method,
        "resolved_executable": resolved_executable,
        "executable_sha256": executable_sha256,
        "source_relationship": relationship,
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
        "runtime_package": runtime_package,
        "execution_executable": implementation.get("executable"),
        "ros_package_prefix": runtime_prefix,
        "source_path": effective_source.get("path"),
        "source_remote_origin": remote_origin,
        "source_commit": effective_source.get("commit"),
        "source_branch": effective_source.get("branch"),
        "source_dirty": effective_source.get("dirty"),
    }
