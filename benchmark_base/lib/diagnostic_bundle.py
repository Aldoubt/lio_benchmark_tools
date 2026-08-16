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
from typing import Any, Iterable


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
    path = run / relative
    return path.is_file()


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
        "metrics/smoke_diagnostics.csv",
        "metrics/pairwise_disagreement.csv",
        "standardized/map_sampling/metadata.json",
        "standardized/map_sampling/selected_scans.csv",
    )
    for relative in always_candidates:
        if _safe_relative_file(run, relative):
            included.add(relative)
        else:
            missing.add(relative)

    for pattern in (
        "metrics/smoke_diagnostics_warmup_*.csv",
        "metrics/pairwise_disagreement_warmup_*.csv",
    ):
        included.update(_existing_glob(run, pattern))

    for algorithm_id in _algorithm_ids(manifest):
        for relative in (
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


def _read_csv_statuses(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            rows = csv.DictReader(stream)
            return {
                str(row.get("algorithm_id", "")): str(row.get("status", ""))
                for row in rows
                if row.get("algorithm_id")
            }
    except OSError:
        return {}


def build_summary(
    run: Path,
    manifest: dict[str, Any],
    git_provenance: dict[str, str],
) -> str:
    """Build a compact human-readable evidence summary without inventing states."""
    run_id = str(manifest.get("run_id", run.name))
    dataset = manifest.get("dataset", {})
    dataset = dataset if isinstance(dataset, dict) else {}
    algorithms = _algorithm_ids(manifest)
    head = git_provenance.get("head", "UNAVAILABLE").strip() or "UNAVAILABLE"
    status_text = git_provenance.get("status", "UNAVAILABLE")
    dirty = "UNAVAILABLE" if status_text.strip() == "UNAVAILABLE" else ("yes" if status_text.strip() else "no")

    lines = [
        f"run_id: {run_id}",
        f"dataset_id: {dataset.get('dataset_id', 'UNAVAILABLE')}",
        f"bag_path: {dataset.get('bag_dir', 'UNAVAILABLE')}",
        f"benchmark_git_head: {head}",
        f"benchmark_git_dirty: {dirty}",
        f"algorithms: {', '.join(algorithms) if algorithms else 'UNAVAILABLE'}",
        "",
    ]

    provenance_statuses = _read_csv_statuses(run / "metrics/runtime_provenance.csv")
    if provenance_statuses:
        lines.append("runtime provenance:")
        for algorithm_id in algorithms:
            lines.append(f"  {algorithm_id}: {provenance_statuses.get(algorithm_id, 'UNAVAILABLE')}")
    else:
        lines.append("runtime provenance: UNAVAILABLE")

    frame_statuses = _read_csv_statuses(run / "metrics/trajectory_frame_audit.csv")
    if frame_statuses:
        lines.append("trajectory frame audit:")
        for algorithm_id in algorithms:
            lines.append(f"  {algorithm_id}: {frame_statuses.get(algorithm_id, 'UNAVAILABLE')}")
    else:
        lines.append("trajectory frame audit: UNAVAILABLE")

    scan_metadata = _load_json_if_available(run / "standardized/map_sampling/metadata.json")
    if scan_metadata:
        window = scan_metadata.get("window", {})
        window = window if isinstance(window, dict) else {}
        lines.extend(
            [
                "common scan manifest:",
                f"  selected_scan_count: {scan_metadata.get('selected_scan_count', 'UNAVAILABLE')}",
                f"  scan_step: {scan_metadata.get('scan_step', 'UNAVAILABLE')}",
                f"  window_duration_s: {window.get('duration_s', 'UNAVAILABLE')}",
            ]
        )
    else:
        lines.append("common scan manifest: UNAVAILABLE")

    lines.append("unified map contracts:")
    for algorithm_id in algorithms:
        metadata = _load_json_if_available(
            run / "standardized/maps" / algorithm_id / "unified" / "metadata.json"
        )
        if metadata is None:
            lines.append(f"  {algorithm_id}: UNAVAILABLE")
            continue
        lines.append(
            "  "
            + algorithm_id
            + ": tracked_frame="
            + str(metadata.get("tracked_frame_physical", "UNAVAILABLE"))
            + " world_gauge="
            + str(metadata.get("world_gauge", "UNAVAILABLE"))
            + " scan_transform="
            + str(metadata.get("scan_frame_transform", "UNAVAILABLE"))
        )

    return "\n".join(lines).rstrip() + "\n"


def build_bundle_manifest(
    *,
    run_id: str,
    archive_name: str,
    include_reports: bool,
    selection: BundleSelection,
    generated_members: Iterable[str] = GENERATED_MEMBERS,
) -> dict[str, Any]:
    included = sorted(set(selection.included).union(str(value) for value in generated_members))
    return {
        "schema": BUNDLE_SCHEMA,
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "include_reports": include_reports,
        "archive_name": archive_name,
        "included": included,
        "missing": list(selection.missing),
        "excluded_large_artifacts": list(EXCLUDED_LARGE_ARTIFACTS),
    }


def _add_bytes(stream: tarfile.TarFile, arcname: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.size = len(payload)
    info.mtime = 0
    info.mode = 0o644
    stream.addfile(info, io.BytesIO(payload))


def create_diagnostic_bundle(
    run: Path,
    repository_root: Path,
    include_reports: bool = False,
    output: Path | None = None,
) -> Path:
    """Create a portable `.tar.gz` containing small run diagnostics only."""
    run = run.expanduser().resolve()
    if not run.is_dir():
        raise ValueError(f"run directory does not exist: {run}")
    manifest_path = run / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"missing run manifest: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid run manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("run manifest must be a JSON object")

    run_id = str(manifest.get("run_id") or run.name)
    if output is None:
        archive = run / "reports" / "bundles" / f"{run_id}_diagnostic_bundle.tar.gz"
    else:
        archive = output.expanduser()
        if not archive.is_absolute():
            archive = archive.resolve()
    archive = archive.resolve()

    selection = collect_bundle_files(run, manifest, include_reports)
    physical_members = tuple(
        relative
        for relative in selection.included
        if (run / relative).resolve() != archive
    )
    if physical_members != selection.included:
        selection = BundleSelection(physical_members, selection.missing)

    git_provenance = capture_git_provenance(repository_root)
    summary = build_summary(run, manifest, git_provenance)
    bundle_manifest = build_bundle_manifest(
        run_id=run_id,
        archive_name=archive.name,
        include_reports=include_reports,
        selection=selection,
    )

    generated = {
        "metadata/bundle/SUMMARY.txt": summary.encode("utf-8"),
        "metadata/bundle/bundle_manifest.json": (
            json.dumps(bundle_manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "metadata/bundle/benchmark_git_head.txt": git_provenance["head"].encode("utf-8"),
        "metadata/bundle/benchmark_git_status.txt": git_provenance["status"].encode("utf-8"),
        "metadata/bundle/benchmark_local.patch": git_provenance["patch"].encode("utf-8"),
    }

    archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "w:gz") as stream:
            for relative in selection.included:
                path = run / relative
                if path.resolve() == archive:
                    continue
                stream.add(path, arcname=relative, recursive=False)
            for arcname in GENERATED_MEMBERS:
                _add_bytes(stream, arcname, generated[arcname])
    except (OSError, tarfile.TarError) as exc:
        raise ValueError(f"failed to create diagnostic bundle: {exc}") from exc
    return archive
