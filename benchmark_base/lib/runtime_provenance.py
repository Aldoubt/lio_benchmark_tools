#!/usr/bin/env python3
"""Runtime implementation provenance classification for benchmark baselines.

The helpers here do not discover a local workspace themselves.  They classify
facts collected by an evaluator so a formal run cannot silently mix a declared
implementation with a different package/source tree or frame contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse


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
    if not ros_package_prefix:
        unresolved.append("ROS package prefix is unavailable")
    if expected is not None and actual is None:
        unresolved.append("runtime GitHub source repository is unavailable")
    if unresolved:
        return ProvenanceClassification(ProvenanceStatus.UNRESOLVED, tuple(unresolved))

    if expected is not None and actual != expected:
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
