#!/usr/bin/env python3
"""Portable diagnostic bundle creation for LIO benchmark runs.

This module is intentionally ROS-independent. It packages existing small run
artifacts and generated provenance metadata without modifying the scientific
artifacts that already exist in the run directory.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import datetime as dt
import io
import json
from pathlib import Path
import subprocess
import tarfile
from typing import Any

from benchmark_base.lib.run_status import refresh_run_status


BUNDLE_SCHEMA = "lio_benchmark_diagnostic_bundle/v1"
GENERATED_MEMBERS = (
    "metadata/bundle/SUMMARY.txt",
    "metadata/bundle/bundle_manifest.json",
    "metadata/bundle/benchmark_git_head.txt",
    "metadata/bundle/benchmark_git_status.txt",
    "metadata/bundle/benchmark_local.patch",
)
EXCLUDED_LARGE_ARTIFACTS = (
    "raw/**",
    "**/*.db3",
    "**/*.mcap",
    "**/*.ply",
    "**/*.pcd",
)
LEGACY_OPTIONAL_ARTIFACTS = (
    "metrics/smoke_diagnostics.csv",
    "metrics/pairwise_disagreement.csv",
)
RELATIVE_SE3_ARTIFACTS = (
    "metrics/relative_se3/metadata.json",
    "metrics/relative_se3/normalized_motion.csv",
    "metrics/relative_se3/pairwise_samples.csv",
    "metrics/relative_se3/pairwise_summary.csv",
    "metrics/relative_se3/onset_thresholds.csv",
)
TRAJECTORY_COVERAGE_ARTIFACT = "metrics/trajectory_coverage.csv"
TRAJECTORY_COVERAGE_METADATA_GLOB = "metadata/trajectory_coverage/*.json"


@dataclass(frozen=True)
class BundleSelection:
    included: tuple[str, ...]
    missing: tuple[str, ...]


def _algorithm_ids(manifest: dict[str, Any]) -> tuple[str, ...]:
    algorithms = manifest.get("algorithms", {})
    if isinstance(algorithms, dict):
        return tuple(str(value) for value in algorithms)
    if isinstance(algorithms, list):
        return tuple(str(value) for value in algorithms)
    raise ValueError("manifest algorithms must be an object or list")


def _safe_relative_file(run: Path, relative: str) -> bool:
    return (run / relative).is_file()


def _existing_glob(run: Path, pattern: str) -> tuple[str, ...]:
    values = []
    for path in run.glob(pattern):
        if not path.is_file():
            continue
        relative = path.relative_to(run).as_posix()
        if _is_forbidden(relative):
            continue
        values.append(relative)
    return tuple(sorted(set(values)))


def _is_forbidden(relative: str) -> bool:
    path = Path(relative)
    if not path.parts:
        return True
    if path.parts[0] == "raw":
        return True
    if "build" in path.parts or "install" in path.parts:
        return True
    if path.suffix.lower() in {".db3", ".mcap", ".ply", ".pcd"}:
        return True
    return False


def collect_bundle_files(
    run: Path,
    manifest: dict[str, Any],
    include_reports: bool,
) -> BundleSelection:
    """Return deterministic run-relative files plus expected missing evidence."""
    run = run.resolve()
    included: set[str] = set()
    missing: set[str] = set()

    always_candidates = (
        "manifest.json",
        "RUN_STATUS.md",
        "metrics/runtime_provenance.csv",
        "metrics/trajectory_frame_audit.csv",
        "standardized/map_sampling/metadata.json",
        "standardized/map_sampling/selected_scans.csv",
    )
    for relative in always_candidates:
        if _safe_relative_file(run, relative):
            included.add(relative)
        else:
            missing.add(relative)

    for relative in LEGACY_OPTIONAL_ARTIFACTS:
        if _safe_relative_file(run, relative):
            included.add(relative)
    for pattern in (
        "metrics/smoke_diagnostics_warmup_*.csv",
        "metrics/pairwise_disagreement_warmup_*.csv",
    ):
        included.update(_existing_glob(run, pattern))

    for relative in RELATIVE_SE3_ARTIFACTS:
        if _safe_relative_file(run, relative):
            included.add(relative)

    # Coverage diagnostics are additive evidence for new runs and remain
    # optional for historical bundles.
    if _safe_relative_file(run, TRAJECTORY_COVERAGE_ARTIFACT):
        included.add(TRAJECTORY_COVERAGE_ARTIFACT)
    included.update(_existing_glob(run, TRAJECTORY_COVERAGE_METADATA_GLOB))

    for algorithm_id in _algorithm_ids(manifest):
        for relative in (
            f"metadata/algorithms/{algorithm_id}/runtime_identity.json",
            f"metadata/algorithms/{algorithm_id}/trajectory_standardization.json",
            f"metadata/frame_audit/{algorithm_id}.json",
            f"metadata/runtime_provenance/{algorithm_id}.json",
            f"standardized/maps/{algorithm_id}/unified/metadata.json",
        ):
            if _safe_relative_file(run, relative):
                included.add(relative)
            else:
                missing.add(relative)

    if include_reports:
        report_matches = _existing_glob(run, "reports/*.md") + _existing_glob(run, "reports/*.html")
        figure_matches = _existing_glob(run, "figures/*.png")
        included.update(report_matches)
        included.update(figure_matches)
        if not report_matches:
            missing.add("reports/*.{md,html}")
        if not figure_matches:
            missing.add("figures/*.png")

    included = {relative for relative in included if not _is_forbidden(relative)}
    return BundleSelection(tuple(sorted(included)), tuple(sorted(missing)))


def _capture(command: list[str], cwd: Path) -> str | None:
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
    return result.stdout


def capture_git_provenance(repository_root: Path) -> dict[str, str]:
    """Capture read-only benchmark repository state."""
    repository_root = repository_root.resolve()
    head = _capture(["git", "rev-parse", "HEAD"], repository_root)
    status = _capture(["git", "status", "--short"], repository_root)
    patch = _capture(["git", "diff"], repository_root)
    return {
        "head": head if head is not None else "UNAVAILABLE\n",
        "status": status if status is not None else "UNAVAILABLE\n",
        "patch": patch if patch is not None else "UNAVAILABLE\n",
    }


def _load_json_if_available(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_csv_field(path: Path, field: str) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except OSError:
        return {}
    values: dict[str, str] = {}
    for row in rows:
        algorithm_id = row.get("algorithm_id")
        value = row.get(field)
        if algorithm_id and value:
            values[str(algorithm_id)] = str(value)
    return values


def _summary_text(run: Path, manifest: dict[str, Any], selection: BundleSelection) -> str:
    algorithms = _algorithm_ids(manifest)
    provenance_path = run / "metrics/runtime_provenance.csv"
    provenance = _read_csv_field(provenance_path, "status")
    source_reproducibility = _read_csv_field(
        provenance_path, "source_reproducibility_status"
    )
    frame_contract = _read_csv_field(provenance_path, "frame_contract_status")
    frame_evidence = _read_csv_field(run / "metrics/trajectory_frame_audit.csv", "status")
    lines = [
        "LIO Benchmark Diagnostic Bundle",
        "================================",
        f"run: {run}",
        f"run_id: {manifest.get('run_id', run.name)}",
        f"dataset: {manifest.get('dataset', {}).get('dataset_id', 'UNKNOWN') if isinstance(manifest.get('dataset'), dict) else 'UNKNOWN'}",
        f"algorithms: {', '.join(algorithms)}",
        "",
        "Evidence status",
        "---------------",
    ]
    for algorithm_id in algorithms:
        identity = _load_json_if_available(
            run / "metadata" / "algorithms" / algorithm_id / "runtime_identity.json"
        )
        identity_status = (
            str(identity.get("identity_status", "UNKNOWN")) if identity is not None else "UNAVAILABLE"
        )
        lines.append(
            f"{algorithm_id}: runtime identity: {identity_status}; "
            f"runtime provenance: {provenance.get(algorithm_id, 'UNAVAILABLE')}; "
            f"source reproducibility: {source_reproducibility.get(algorithm_id, 'UNAVAILABLE')}; "
            f"frame evidence: {frame_evidence.get(algorithm_id, 'UNAVAILABLE')}; "
            f"frame contract: {frame_contract.get(algorithm_id, 'UNAVAILABLE')}"
        )
    lines.extend(
        [
            "",
            "Bundle contents",
            "---------------",
            f"included files: {len(selection.included)}",
            f"missing expected evidence: {len(selection.missing)}",
        ]
    )
    if selection.missing:
        lines.append("")
        lines.append("Missing evidence")
        lines.append("----------------")
        lines.extend(f"- {value}" for value in selection.missing)
    return "\n".join(lines) + "\n"


def _add_bytes(stream: tarfile.TarFile, name: str, content: str, created_at: int) -> None:
    payload = content.encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mtime = created_at
    info.mode = 0o644
    stream.addfile(info, io.BytesIO(payload))


def _default_output(run: Path, manifest: dict[str, Any]) -> Path:
    run_id = str(manifest.get("run_id", run.name))
    return run / "reports" / "bundles" / f"{run_id}_diagnostic_bundle.tar.gz"


def create_diagnostic_bundle(
    run: str | Path,
    *,
    repository_root: str | Path,
    include_reports: bool = False,
    output: str | Path | None = None,
) -> Path:
    run = Path(run).resolve()
    manifest_path = run / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"missing run manifest: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid run manifest: {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("run manifest root must be an object")

    refresh_run_status(run, manifest, bundle_will_exist=True)
    selection = collect_bundle_files(run, manifest, include_reports)
    repository_root = Path(repository_root).resolve()
    git = capture_git_provenance(repository_root)
    archive = Path(output).expanduser().resolve() if output else _default_output(run, manifest)
    archive.parent.mkdir(parents=True, exist_ok=True)

    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    created_at = int(generated_at.timestamp())
    generated = {
        "metadata/bundle/SUMMARY.txt": _summary_text(run, manifest, selection),
        "metadata/bundle/benchmark_git_head.txt": git["head"],
        "metadata/bundle/benchmark_git_status.txt": git["status"],
        "metadata/bundle/benchmark_local.patch": git["patch"],
    }
    bundle_manifest = {
        "schema": BUNDLE_SCHEMA,
        "generated_at": generated_at.isoformat(),
        "run": str(run),
        "output": str(archive),
        "include_reports": bool(include_reports),
        "included": list(selection.included) + sorted(generated) + ["metadata/bundle/bundle_manifest.json"],
        "missing": list(selection.missing),
        "excluded_large_patterns": list(EXCLUDED_LARGE_ARTIFACTS),
    }
    generated["metadata/bundle/bundle_manifest.json"] = (
        json.dumps(bundle_manifest, ensure_ascii=False, indent=2) + "\n"
    )

    with tarfile.open(archive, "w:gz") as stream:
        for relative in selection.included:
            stream.add(run / relative, arcname=relative, recursive=False)
        for name in GENERATED_MEMBERS:
            _add_bytes(stream, name, generated[name], created_at)
    return archive
