#!/usr/bin/env python3
"""Audit the exact runtime implementation behind benchmark trajectory artifacts.

This is a read-only diagnostic. It combines current source-backed registry
contracts with run-local frame-audit evidence and local ROS/git provenance. It
never edits algorithm sources, raw bags, standardized trajectories, or maps.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.registry import Registry, RegistryError  # noqa: E402
from benchmark_base.lib.runtime_provenance import (  # noqa: E402
    build_runtime_provenance_record,
    workspace_from_package_prefix,
)


REGISTRY = Registry()


def capture(command: list[str], *, cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def package_prefix(package: str | None) -> str | None:
    if not package:
        return None
    return capture(["ros2", "pkg", "prefix", package])


def colcon_package_sources(workspace: Path | None) -> dict[str, Path]:
    if workspace is None or not workspace.is_dir():
        return {}
    text = capture(["colcon", "list"], cwd=workspace)
    if not text:
        return {}
    rows: dict[str, Path] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        package, raw_path = parts[0], parts[1]
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = workspace / path
        rows[package] = path.resolve()
    return rows


def source_candidate(
    workspace: Path,
    algorithm: dict[str, Any],
    package_sources: dict[str, Path],
    runtime_package_sources: dict[str, Path],
) -> Path | None:
    implementation = algorithm.get("execution_implementation", {})
    implementation = implementation if isinstance(implementation, dict) else {}
    package = str(implementation.get("package", ""))
    if package and package in runtime_package_sources:
        return runtime_package_sources[package]
    if package and package in package_sources:
        return package_sources[package]

    for container in (implementation, algorithm.get("source", {})):
        if not isinstance(container, dict):
            continue
        hint = container.get("local_path_hint")
        if not hint:
            continue
        path = Path(str(hint)).expanduser()
        if not path.is_absolute():
            path = workspace / path
        if path.exists():
            return path.resolve()
    return None


def git_root(path: Path | None) -> Path | None:
    if path is None:
        return None
    root = capture(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
    return Path(root).resolve() if root else None


def git_state(path: Path | None) -> dict[str, Any]:
    root = git_root(path)
    if root is None:
        return {"path": str(path) if path else None}
    return {
        "path": str(root),
        "remote_origin": capture(["git", "-C", str(root), "remote", "get-url", "origin"]),
        "commit": capture(["git", "-C", str(root), "rev-parse", "HEAD"]),
        "branch": capture(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(capture(["git", "-C", str(root), "status", "--porcelain"])),
    }


def load_frame_audit(run: Path, algorithm_id: str) -> dict[str, Any]:
    path = run / "metadata" / "frame_audit" / f"{algorithm_id}.json"
    if not path.is_file():
        return {"status": "MISSING", "error": f"frame audit missing: {path}"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "AUDIT_FAILED", "error": str(exc)}
    return value if isinstance(value, dict) else {"status": "AUDIT_FAILED", "error": "frame audit is not an object"}


def audit_algorithm(
    run: Path,
    workspace: Path,
    algorithm_id: str,
    package_sources: dict[str, Path],
) -> dict[str, Any]:
    algorithm = REGISTRY.load_algorithm(algorithm_id)
    implementation = algorithm.get("execution_implementation", {})
    implementation = implementation if isinstance(implementation, dict) else {}
    package = str(implementation.get("package", "")) or None
    prefix = package_prefix(package)
    runtime_workspace = workspace_from_package_prefix(prefix)
    runtime_package_sources = colcon_package_sources(runtime_workspace)
    source = source_candidate(
        workspace,
        algorithm,
        package_sources,
        runtime_package_sources,
    )
    row = build_runtime_provenance_record(
        algorithm=algorithm,
        frame_audit=load_frame_audit(run, algorithm_id),
        ros_package_prefix=prefix,
        source_state=git_state(source),
    )
    row["runtime_workspace"] = str(runtime_workspace) if runtime_workspace else None
    row["contract_source"] = "CURRENT_REGISTRY"
    row["registry_algorithm_generation"] = algorithm.get("algorithm_generation")
    return row


def write_outputs(run: Path, rows: list[dict[str, Any]]) -> Path:
    output_dir = run / "metadata" / "runtime_provenance"
    output_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        (output_dir / f"{row['algorithm_id']}.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    path = run / "metrics" / "runtime_provenance.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: ";".join(str(v) for v in value) if isinstance(value, list) else value
                    for key, value in ((key, row.get(key, "")) for key in fieldnames)
                }
            )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithms", nargs="+")
    args = parser.parse_args()

    run = args.run.resolve()
    manifest_path = run / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"missing run manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    workspace = Path(str(manifest.get("workspace", "."))).expanduser().resolve()
    selected = args.algorithms or list(manifest.get("algorithms", {}))
    package_sources = colcon_package_sources(workspace)

    rows: list[dict[str, Any]] = []
    for algorithm_id in selected:
        try:
            rows.append(audit_algorithm(run, workspace, algorithm_id, package_sources))
        except (RegistryError, ValueError) as exc:
            rows.append(
                {
                    "algorithm_id": algorithm_id,
                    "status": "UNRESOLVED",
                    "reasons": [str(exc)],
                    "contract_source": "CURRENT_REGISTRY",
                }
            )

    path = write_outputs(run, rows)
    print(path)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
