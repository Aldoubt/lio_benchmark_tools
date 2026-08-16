#!/usr/bin/env python3
"""Resolve run-time ROS package facts without coupling adapter core to ROS."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


PackageProbe = Callable[[str], str | None]


def _selected_algorithm(manifest: dict[str, Any], algorithm_id: str) -> dict[str, Any]:
    algorithms = manifest.get("algorithms", {})
    if not isinstance(algorithms, dict) or algorithm_id not in algorithms:
        raise ValueError(f"algorithm is not selected in manifest: {algorithm_id}")
    algorithm = algorithms[algorithm_id]
    if not isinstance(algorithm, dict):
        raise ValueError(f"algorithm manifest entry must be an object: {algorithm_id}")
    return algorithm


def _has_explicit_executable_override(manifest: dict[str, Any], algorithm_id: str) -> bool:
    overrides = manifest.get("execution_overrides", {})
    if not isinstance(overrides, dict):
        return False
    override = overrides.get(algorithm_id)
    if not isinstance(override, dict):
        return False
    executable = override.get("executable")
    return isinstance(executable, str) and bool(executable.strip())


def _runtime_package(algorithm: dict[str, Any]) -> str | None:
    implementation = algorithm.get("execution_implementation", {})
    if not isinstance(implementation, dict):
        return None
    package = implementation.get("package")
    value = str(package).strip() if package is not None else ""
    return value or None


def resolve_runtime_package_prefixes(
    manifest: dict[str, Any],
    algorithm_ids: Iterable[str],
    *,
    probe: PackageProbe,
) -> dict[str, str | None]:
    """Probe each registry-default ROS package at most once.

    Algorithms with explicit executable overrides are intentionally skipped:
    their execution identity is the explicit binary rather than a registry
    package lookup.
    """
    packages: list[str] = []
    seen: set[str] = set()
    for algorithm_id in algorithm_ids:
        algorithm_id = str(algorithm_id)
        algorithm = _selected_algorithm(manifest, algorithm_id)
        if _has_explicit_executable_override(manifest, algorithm_id):
            continue
        package = _runtime_package(algorithm)
        if package is None or package in seen:
            continue
        seen.add(package)
        packages.append(package)
    return {package: probe(package) for package in packages}
