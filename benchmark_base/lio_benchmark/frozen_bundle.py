"""Open and export immutable frozen benchmark bundles without live-run access."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid or missing JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_complete_manifest(frozen: Path) -> tuple[Path, dict[str, Any]]:
    frozen = Path(frozen).expanduser().resolve()
    if not frozen.is_dir():
        raise ValueError(f"frozen bundle directory does not exist: {frozen}")
    manifest = _load_json(frozen / "freeze_manifest.json")
    if manifest.get("freeze_state") != "COMPLETE":
        raise ValueError(f"frozen bundle is not COMPLETE: {frozen}")
    return frozen, manifest


def _safe_relative_file(frozen: Path, relative_path: str) -> tuple[str, Path]:
    relative = Path(str(relative_path))
    if relative.is_absolute() or ".." in relative.parts or str(relative) in {"", "."}:
        raise ValueError(f"invalid frozen artifact path: {relative_path}")
    target = (frozen / relative).resolve()
    try:
        target.relative_to(frozen)
    except ValueError as exc:
        raise ValueError(f"frozen artifact path escapes bundle: {relative_path}") from exc
    if not target.is_file():
        raise FileNotFoundError(relative.as_posix())
    return relative.as_posix(), target


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def verify_registered_artifact(frozen: Path, relative_path: str) -> dict[str, Any]:
    frozen = Path(frozen).expanduser().resolve()
    manifest = _load_json(frozen / "freeze_manifest.json")
    normalized, target = _safe_relative_file(frozen, relative_path)
    records = manifest.get("generated_artifacts") or []
    record = next(
        (
            item
            for item in records
            if isinstance(item, dict) and item.get("path") == normalized
        ),
        None,
    )
    if record is None:
        raise ValueError(f"frozen artifact is not registered: {normalized}")
    digest, size = _sha256_file(target)
    if record.get("sha256") != digest or record.get("size_bytes") != size:
        raise ValueError(f"frozen artifact hash or size mismatch: {normalized}")
    return dict(record)


def open_frozen_recording(
    frozen: Path,
    *,
    executable_resolver: Callable[[str], str | None] = shutil.which,
    run_process: Callable[..., Any] = subprocess.run,
) -> int:
    frozen, _ = _load_complete_manifest(frozen)
    verify_registered_artifact(frozen, "viewer/diagnostic.rrd")
    executable = executable_resolver("rerun")
    if not executable:
        raise RuntimeError(
            "Native Rerun executable is unavailable. Install the tested Rerun SDK/runtime."
        )
    result = run_process(
        [str(executable), str((frozen / "viewer/diagnostic.rrd").resolve())],
        check=False,
    )
    return int(getattr(result, "returncode", 0) or 0)


def _summary_rows(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    health = report_data.get("runtime_health") or {}
    trajectories = report_data.get("trajectory_summary") or {}
    resources = report_data.get("resource_summary") or {}
    relative = report_data.get("baseline_relative_diagnostics") or {}
    diagnostics = report_data.get("trajectory_diagnostics") or {}
    rows: list[dict[str, Any]] = []
    for algorithm in health if isinstance(health, dict) else []:
        h = dict(health.get(algorithm) or {})
        t = dict(trajectories.get(algorithm) or {}) if isinstance(trajectories, dict) else {}
        r = dict(resources.get(algorithm) or {}) if isinstance(resources, dict) else {}
        rel = dict(relative.get(algorithm) or {}) if isinstance(relative, dict) else {}
        diag = dict(diagnostics.get(algorithm) or {}) if isinstance(diagnostics, dict) else {}
        rows.append(
            {
                "algorithm": algorithm,
                "status": h.get("status"),
                "trajectory_health_pass": bool(h.get("trajectory_health_pass")),
                "recommendation_eligible": bool(h.get("recommendation_eligible")),
                "path_length_m": t.get("path_length_m"),
                "z_range_m": t.get("z_range_m"),
                "mean_cpu_percent": r.get("mean_cpu_percent"),
                "peak_rss_mib": r.get("peak_rss_mib"),
                "relative_rmse_m": rel.get("rmse_m"),
                "relative_p95_m": rel.get("p95_m"),
                "position_jump_count": diag.get("position_jump_count"),
                "yaw_jump_count": diag.get("yaw_jump_count"),
            }
        )
    return rows


def _figure_sources(frozen: Path, evidence: dict[str, Any]) -> list[tuple[Path, Path]]:
    output: list[tuple[Path, Path]] = []
    for item in evidence.get("static_figures") or []:
        if not isinstance(item, dict) or not item.get("bundle_path"):
            continue
        bundle_path = str(item["bundle_path"])
        verify_registered_artifact(frozen, bundle_path)
        relative, source = _safe_relative_file(frozen, bundle_path)
        rel = Path(relative)
        try:
            nested = rel.relative_to("evidence")
        except ValueError as exc:
            raise ValueError(
                f"static figure is not stored below evidence/: {relative}"
            ) from exc
        output.append((source, nested))
    return output


def export_frozen_bundle(frozen: Path, *, output: Path | None = None) -> Path:
    frozen, manifest = _load_complete_manifest(frozen)
    for relative in (
        "report/index.html",
        "report/report.pdf",
        "report_data.json",
        "evidence/evidence_manifest.json",
    ):
        verify_registered_artifact(frozen, relative)

    report_data = _load_json(frozen / "report_data.json")
    evidence = _load_json(frozen / "evidence/evidence_manifest.json")
    figures = _figure_sources(frozen, evidence)
    rows = _summary_rows(report_data)

    target = (
        Path(output).expanduser().resolve()
        if output is not None
        else frozen.with_name(f"{frozen.name}_export").resolve()
    )
    if target.exists():
        raise FileExistsError(f"refusing to overwrite export directory: {target}")
    staging = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    if staging.exists():
        raise FileExistsError(f"staging export directory already exists: {staging}")

    fields = [
        "algorithm",
        "status",
        "trajectory_health_pass",
        "recommendation_eligible",
        "path_length_m",
        "z_range_m",
        "mean_cpu_percent",
        "peak_rss_mib",
        "relative_rmse_m",
        "relative_p95_m",
        "position_jump_count",
        "yaw_jump_count",
    ]
    try:
        (staging / "figures").mkdir(parents=True)
        (staging / "metrics").mkdir(parents=True)
        (staging / "provenance").mkdir(parents=True)

        shutil.copy2(frozen / "report/index.html", staging / "report.html")
        shutil.copy2(frozen / "report/report.pdf", staging / "report.pdf")
        shutil.copy2(frozen / "report_data.json", staging / "metrics/summary.json")
        shutil.copy2(
            frozen / "freeze_manifest.json",
            staging / "provenance/freeze_manifest.json",
        )
        for source, nested in figures:
            destination = staging / "figures" / nested
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        with (staging / "metrics/summary.csv").open(
            "w", newline="", encoding="utf-8"
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in fields})

        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target
