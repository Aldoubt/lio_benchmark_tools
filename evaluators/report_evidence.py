from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from freeze_experiment import register_generated_artifact, sha256_path, write_json_atomic

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg"}
STATIC_SOURCES = (
    ("figures/comparison_dashboard", "evidence/overview/comparison_dashboard"),
    ("figures/trajectory_discontinuity", "evidence/trajectories/trajectory_discontinuity"),
    ("figures/resource_curves", "evidence/resources/resource_curves"),
    ("figures/fast_livo2_baseline_maps", "evidence/maps/fast_livo2_baseline_maps"),
    ("figures/phase_analysis", "evidence/overview/phase_analysis"),
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "case"


def _copy_static_figures(frozen: Path, source_run: Path | None) -> list[dict[str, Any]]:
    if source_run is None or not source_run.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for source_rel, bundle_rel in STATIC_SOURCES:
        source_dir = source_run / source_rel
        if not source_dir.is_dir():
            continue
        for source in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            if source.suffix.lower() not in IMAGE_SUFFIXES or source.is_symlink():
                continue
            nested = source.relative_to(source_dir)
            target_rel = (Path(bundle_rel) / nested).as_posix()
            target = frozen / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            source_sha, source_size = sha256_path(source)
            shutil.copy2(source, target)
            artifact = register_generated_artifact(
                frozen, target_rel, "static_report_evidence"
            )
            records.append(
                {
                    "source_path": str(source.resolve()),
                    "source_size_bytes": source_size,
                    "source_sha256": source_sha,
                    "bundle_path": target_rel,
                    "bundle_size_bytes": artifact["size_bytes"],
                    "bundle_sha256": artifact["sha256"],
                }
            )
    return records


def _write_anomaly_cases(
    frozen: Path, report_data: dict[str, Any]
) -> list[dict[str, Any]]:
    summary = report_data.get("anomaly_summary") or {}
    cases = summary.get("representative_cases") or []
    output: list[dict[str, Any]] = []
    for index, window in enumerate(cases, start=1):
        if not isinstance(window, dict):
            continue
        window_id = str(window.get("window_id") or f"case_{index:02d}")
        filename = f"case_{index:02d}_{_safe_name(window_id)}.json"
        relative = (Path("evidence/anomalies") / filename).as_posix()
        payload = {
            "schema_version": 1,
            "case_index": index,
            "window": window,
            "selection_policy": summary.get("selection_policy") or {},
        }
        write_json_atomic(frozen / relative, payload)
        artifact = register_generated_artifact(
            frozen, relative, "representative_anomaly_case"
        )
        output.append(
            {
                "window_id": window_id,
                "algorithm": window.get("algorithm"),
                "types": list(window.get("types") or []),
                "severity": window.get("severity"),
                "bundle_path": relative,
                "sha256": artifact["sha256"],
                "size_bytes": artifact["size_bytes"],
            }
        )
    return output


def build_report_evidence(frozen: Path) -> dict[str, Any]:
    frozen = Path(frozen).resolve()
    freeze_manifest_path = frozen / "freeze_manifest.json"
    freeze_manifest = _load_json(freeze_manifest_path)
    if freeze_manifest.get("freeze_state") == "COMPLETE":
        raise ValueError("frozen bundle is already COMPLETE")
    report_data = _load_json(frozen / "report_data.json")

    source_value = (freeze_manifest.get("source_run") or {}).get("path")
    source_run = (
        Path(str(source_value)).expanduser().resolve() if source_value else None
    )
    static_figures = _copy_static_figures(frozen, source_run)
    anomaly_cases = _write_anomaly_cases(frozen, report_data)

    rerun_pointcloud = (
        (report_data.get("optional_evidence") or {}).get("rerun_pointcloud") or {}
    )
    pointcloud_source_available = bool(rerun_pointcloud.get("enabled"))
    if pointcloud_source_available:
        pointcloud_case_reason = (
            "native_pointcloud_source_available; static case rendering not materialized"
        )
    else:
        pointcloud_case_reason = str(
            rerun_pointcloud.get("omission_reason")
            or "pointcloud_evidence_unavailable"
        )

    evidence_manifest = {
        "schema_version": 1,
        "static_figure_source": {
            "path": str(source_run) if source_run is not None else None,
            "available": bool(source_run is not None and source_run.is_dir()),
            "policy": "copy known pre-existing deterministic report figures only",
        },
        "static_figures": static_figures,
        "anomaly_cases": anomaly_cases,
        "pointcloud_case_evidence": {
            "available": False,
            "source_available": pointcloud_source_available,
            "reason": pointcloud_case_reason,
        },
    }
    output = frozen / "evidence/evidence_manifest.json"
    write_json_atomic(output, evidence_manifest)
    artifact = register_generated_artifact(
        frozen, "evidence/evidence_manifest.json", "report_evidence_manifest"
    )
    return {"manifest": evidence_manifest, "artifact": artifact}
