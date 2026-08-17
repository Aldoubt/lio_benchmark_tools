"""Read-only Same-Bag Mapping Benchmark V1 artifact summary."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from benchmark_base.lib.artifacts import map_artifact_paths


SCHEMA = "lio_benchmark_same_bag_mapping/v1"
FINALIZATION_SCHEMA = "lio_benchmark_same_bag_mapping_finalization/v1"
ROW_FIELDS = (
    "algorithm_id",
    "display_name",
    "evaluation_roles",
    "effective_modalities",
    "input_topics",
    "declared_outputs",
    "run_status",
    "runtime_identity_status",
    "execution_resolution_method",
    "resolved_executable",
    "executable_sha256",
    "trajectory_status",
    "native_map_status",
    "native_map_point_count",
    "unified_map_status",
    "unified_map_point_count",
    "strict_common_scan_policy",
    "matched_scan_count",
    "selected_scan_count",
    "unmatched_scan_count",
    "matched_scan_ratio",
    "runtime_measurement_method",
    "wall_time_s",
    "cpu_user_s",
    "cpu_system_s",
    "cpu_total_s",
    "max_rss_kib",
)
PERFORMANCE_FIELDS = (
    "algorithm_id",
    "run_status",
    "runtime_measurement_method",
    "wall_time_s",
    "cpu_user_s",
    "cpu_system_s",
    "cpu_total_s",
    "max_rss_kib",
)
_MODALITY_ORDER = (
    "lidar",
    "imu",
    "camera",
    "gnss",
    "wheel_odometry",
    "kinematics",
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _format_mapping(value: Any) -> str:
    if not isinstance(value, dict):
        return "UNKNOWN"
    parts = [f"{key}={item}" for key, item in value.items() if item is not None and str(item) != ""]
    return ";".join(parts) if parts else "NONE"


def _inputs(algorithm: dict[str, Any]) -> dict[str, Any]:
    direct = algorithm.get("inputs")
    if isinstance(direct, dict):
        return direct
    topics = algorithm.get("topics")
    if isinstance(topics, dict) and isinstance(topics.get("inputs"), dict):
        return topics["inputs"]
    return {}


def _outputs(algorithm: dict[str, Any]) -> dict[str, Any]:
    direct = algorithm.get("outputs")
    if isinstance(direct, dict):
        return direct
    topics = algorithm.get("topics")
    if isinstance(topics, dict) and isinstance(topics.get("outputs"), dict):
        return topics["outputs"]
    return {}


def _modalities(algorithm: dict[str, Any]) -> str:
    profile = algorithm.get("sensor_profile")
    if not isinstance(profile, dict):
        required = algorithm.get("required_modalities")
        if isinstance(required, list) and required:
            return "+".join(str(item) for item in required)
        return "UNKNOWN"
    enabled = [name for name in _MODALITY_ORDER if profile.get(name) is True]
    return "+".join(enabled) if enabled else "UNKNOWN"


def _declared_native_status(algorithm: dict[str, Any]) -> str | None:
    native = algorithm.get("native_map")
    if isinstance(native, dict):
        status = native.get("default_status")
        if isinstance(status, str) and status:
            return status
    preprocessing = algorithm.get("preprocessing")
    if isinstance(preprocessing, dict):
        status = preprocessing.get("native_global_map")
        if isinstance(status, str) and status:
            return status
    return None


def _first_value(mapping: dict[str, Any] | None, keys: Iterable[str]) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _native_evidence(run: Path, algorithm_id: str, algorithm: dict[str, Any]) -> tuple[str, int | None]:
    paths = map_artifact_paths(run, algorithm_id)
    metadata = _load_json(paths.native_metadata)
    if metadata is not None:
        status = str(metadata.get("status", "UNKNOWN"))
        point_count = metadata.get("point_count")
        return status, int(point_count) if isinstance(point_count, int) else None
    if paths.native_map.is_file():
        return "AVAILABLE", None
    declared = _declared_native_status(algorithm)
    if declared == "NOT_PROVIDED":
        return "NOT_PROVIDED", None
    if declared == "FAILED":
        return "FAILED", None
    return "MISSING", None


def _unified_evidence(run: Path, algorithm_id: str) -> tuple[str, int | None, dict[str, Any] | None]:
    paths = map_artifact_paths(run, algorithm_id)
    metadata_path = paths.unified_metadata if paths.unified_metadata.is_file() else paths.compat_unified_metadata
    map_path = paths.unified_map if paths.unified_map.is_file() else paths.compat_unified_map
    metadata = _load_json(metadata_path)
    if not map_path.is_file() or metadata is None:
        return "MISSING", None, metadata
    point_count = metadata.get("point_count")
    return "AVAILABLE", int(point_count) if isinstance(point_count, int) else None, metadata


def _row_for_algorithm(run: Path, algorithm_id: str, algorithm: dict[str, Any]) -> dict[str, Any]:
    runtime_identity = _load_json(run / "metadata" / "algorithms" / algorithm_id / "runtime_identity.json")
    run_status = _load_json(run / "metadata" / f"run_{algorithm_id}.json")
    runtime = _load_json(run / "metrics" / "runtime" / f"{algorithm_id}.json")
    native_status, native_points = _native_evidence(run, algorithm_id, algorithm)
    unified_status, unified_points, unified_metadata = _unified_evidence(run, algorithm_id)
    matching = unified_metadata.get("timestamp_matching") if isinstance(unified_metadata, dict) else None
    matching = matching if isinstance(matching, dict) else {}

    roles = algorithm.get("evaluation_roles")
    role_text = "+".join(str(item) for item in roles) if isinstance(roles, list) and roles else "UNKNOWN"
    trajectory = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"

    return {
        "algorithm_id": algorithm_id,
        "display_name": str(algorithm.get("display_name", algorithm_id)),
        "evaluation_roles": role_text,
        "effective_modalities": _modalities(algorithm),
        "input_topics": _format_mapping(_inputs(algorithm)),
        "declared_outputs": _format_mapping(_outputs(algorithm)),
        "run_status": str(run_status.get("status", "MISSING")) if run_status else "MISSING",
        "runtime_identity_status": str(runtime_identity.get("identity_status", "UNKNOWN")) if runtime_identity else "MISSING",
        "execution_resolution_method": str(runtime_identity.get("resolution_method", "UNKNOWN")) if runtime_identity else "UNKNOWN",
        "resolved_executable": runtime_identity.get("resolved_executable") if runtime_identity else None,
        "executable_sha256": runtime_identity.get("executable_sha256") if runtime_identity else None,
        "trajectory_status": "AVAILABLE" if trajectory.is_file() else "MISSING",
        "native_map_status": native_status,
        "native_map_point_count": native_points,
        "unified_map_status": unified_status,
        "unified_map_point_count": unified_points,
        "strict_common_scan_policy": (
            unified_metadata.get("scan_set_policy") if isinstance(unified_metadata, dict) else None
        ),
        "matched_scan_count": _first_value(matching, ("matched_scan_count", "matched_manifest_scan_count", "matched_scans")),
        "selected_scan_count": _first_value(matching, ("selected_scan_count", "manifest_scan_count", "selected_scans")),
        "unmatched_scan_count": _first_value(matching, ("unmatched_scan_count", "unmatched_scans")),
        "matched_scan_ratio": _first_value(matching, ("matched_scan_ratio", "match_ratio", "matched_ratio")),
        "runtime_measurement_method": runtime.get("measurement_method") if runtime else None,
        "wall_time_s": runtime.get("wall_time_s") if runtime else None,
        "cpu_user_s": runtime.get("cpu_user_s") if runtime else None,
        "cpu_system_s": runtime.get("cpu_system_s") if runtime else None,
        "cpu_total_s": runtime.get("cpu_total_s") if runtime else None,
        "max_rss_kib": runtime.get("max_rss_kib") if runtime else None,
    }


def _summary_readiness_reasons(rows: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for row in rows:
        algorithm_id = str(row["algorithm_id"])
        if row["run_status"] != "PASS":
            reasons.append(f"{algorithm_id}: run_status={row['run_status']}")
        if row["runtime_identity_status"] != "FROZEN":
            reasons.append(
                f"{algorithm_id}: runtime_identity_status={row['runtime_identity_status']}"
            )
        if row["trajectory_status"] != "AVAILABLE":
            reasons.append(f"{algorithm_id}: trajectory_status={row['trajectory_status']}")
        if row["runtime_measurement_method"] is None or row["wall_time_s"] is None or row["max_rss_kib"] is None:
            reasons.append(f"{algorithm_id}: runtime performance evidence is incomplete")
        if row["unified_map_status"] != "AVAILABLE":
            reasons.append(f"{algorithm_id}: unified_map_status={row['unified_map_status']}")
            continue
        if row["strict_common_scan_policy"] != "STRICT_COMMON_INTERSECTION":
            reasons.append(
                f"{algorithm_id}: strict_common_scan_policy={row['strict_common_scan_policy']}"
            )
        selected = row["selected_scan_count"]
        matched = row["matched_scan_count"]
        unmatched = row["unmatched_scan_count"]
        point_count = row["unified_map_point_count"]
        if not isinstance(selected, int) or selected <= 0:
            reasons.append(f"{algorithm_id}: selected_scan_count={selected}")
        if matched != selected:
            reasons.append(
                f"{algorithm_id}: matched_scan_count={matched} selected_scan_count={selected}"
            )
        if unmatched != 0:
            reasons.append(f"{algorithm_id}: unmatched_scan_count={unmatched}")
        if not isinstance(point_count, int) or point_count <= 0:
            reasons.append(f"{algorithm_id}: unified_map_point_count={point_count}")
    return reasons


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Same-Bag Mapping Benchmark V1 — Algorithm I/O Matrix",
        "",
        "Scientific status: `DESCRIPTIVE_NO_GROUND_TRUTH`",
        "",
        "Performance status: `SINGLE_RUN_DESCRIPTIVE`",
        "",
        "| Algorithm | Modalities | Inputs | Declared outputs | Run | Trajectory | Native Map | Unified Map | Wall [s] | CPU [s] | Peak RSS [KiB] |",
        "|---|---|---|---|---|---|---|---|---:|---:|---:|",
    ]
    for row in rows:
        def cell(value: Any) -> str:
            if value is None:
                return "—"
            return str(value).replace("|", "\\|")

        lines.append(
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    row["display_name"],
                    row["effective_modalities"],
                    row["input_topics"],
                    row["declared_outputs"],
                    row["run_status"],
                    row["trajectory_status"],
                    row["native_map_status"],
                    row["unified_map_status"],
                    row["wall_time_s"],
                    row["cpu_total_s"],
                    row["max_rss_kib"],
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Native Map availability describes upstream/default artifacts only. Unified Map uses the benchmark reconstruction contract. No field in this summary is a ground-truth map-accuracy score.",
            "",
        ]
    )
    return "\n".join(lines)


def _build_payload(
    *,
    run: Path,
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    artifact_role: str,
    source_canonical_summary_sha256: str | None = None,
) -> dict[str, Any]:
    dataset = manifest.get("dataset") if isinstance(manifest.get("dataset"), dict) else {}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "scientific_status": "DESCRIPTIVE_NO_GROUND_TRUTH",
        "performance_status": "SINGLE_RUN_DESCRIPTIVE",
        "benchmark_profile": "DEFAULT_ADAPTED",
        "artifact_role": artifact_role,
        "generated_at": _now_iso(),
        "run_id": manifest.get("run_id", run.name),
        "dataset_id": dataset.get("dataset_id", "UNKNOWN"),
        "replay": manifest.get("replay", {}),
        "algorithms": rows,
    }
    if source_canonical_summary_sha256 is not None:
        payload["source_canonical_summary_sha256"] = source_canonical_summary_sha256
    return payload


def _canonical_outputs(run: Path) -> tuple[Path, Path, Path, Path]:
    return (
        run / "reports" / "algorithm_io_matrix.csv",
        run / "reports" / "algorithm_io_matrix.md",
        run / "metrics" / "runtime_performance.csv",
        run / "reports" / "same_bag_mapping_v1.json",
    )


def _write_summary_package(
    *,
    outputs: tuple[Path, Path, Path, Path],
    rows: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    _write_csv(outputs[0], ROW_FIELDS, rows)
    outputs[1].parent.mkdir(parents=True, exist_ok=True)
    outputs[1].write_text(_markdown(rows), encoding="utf-8")
    _write_csv(outputs[2], PERFORMANCE_FIELDS, rows)
    outputs[3].write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_manifest_and_rows(run: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _load_json(run / "manifest.json")
    if manifest is None:
        raise ValueError(f"missing frozen run manifest: {run / 'manifest.json'}")
    algorithms = manifest.get("algorithms")
    if not isinstance(algorithms, dict) or not algorithms:
        raise ValueError("frozen manifest algorithms must be a non-empty object")
    rows = [_row_for_algorithm(run, algorithm_id, algorithm) for algorithm_id, algorithm in algorithms.items()]
    return manifest, rows


def summarize_same_bag(run: str | Path) -> dict[str, Any]:
    """Summarize final run artifacts without running ROS or rebuilding maps."""
    run = Path(run).resolve()
    outputs = _canonical_outputs(run)
    existing = [path for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(
            "refusing to overwrite same-bag summary output: "
            + ", ".join(str(path) for path in existing)
        )

    manifest, rows = _load_manifest_and_rows(run)
    readiness_reasons = _summary_readiness_reasons(rows)
    if readiness_reasons:
        raise ValueError(
            "Same-Bag summary is not ready; refusing to freeze an intermediate state: "
            + "; ".join(readiness_reasons)
        )

    payload = _build_payload(
        run=run,
        manifest=manifest,
        rows=rows,
        artifact_role="CANONICAL_FINAL_SUMMARY",
    )
    _write_summary_package(outputs=outputs, rows=rows, payload=payload)
    return payload


def finalize_stale_same_bag(run: str | Path) -> dict[str, Any]:
    """Append a final summary package without modifying a premature immutable summary."""
    run = Path(run).resolve()
    canonical_outputs = _canonical_outputs(run)
    missing = [path for path in canonical_outputs if not path.is_file()]
    if missing:
        raise ValueError(
            "cannot finalize without the complete canonical stale summary package: "
            + ", ".join(str(path) for path in missing)
        )

    canonical_summary = _load_json(canonical_outputs[3])
    if canonical_summary is None or canonical_summary.get("schema") != SCHEMA:
        raise ValueError("canonical summary schema is missing or unsupported")
    old_rows = canonical_summary.get("algorithms")
    if not isinstance(old_rows, list) or not old_rows:
        raise ValueError("canonical summary algorithms are missing")
    if not any(
        not isinstance(row, dict) or row.get("unified_map_status") != "AVAILABLE"
        for row in old_rows
    ):
        raise ValueError("canonical summary is not stale; append-only finalization is not applicable")

    final_dir = run / "reports" / "same_bag_mapping_v1_finalization"
    if final_dir.exists():
        raise FileExistsError(f"refusing to overwrite same-bag finalization output: {final_dir}")

    manifest, rows = _load_manifest_and_rows(run)
    readiness_reasons = _summary_readiness_reasons(rows)
    if readiness_reasons:
        raise ValueError(
            "Same-Bag finalization is not ready: " + "; ".join(readiness_reasons)
        )

    source_summary_sha = _sha256_file(canonical_outputs[3])
    payload = _build_payload(
        run=run,
        manifest=manifest,
        rows=rows,
        artifact_role="APPEND_ONLY_FINALIZATION",
        source_canonical_summary_sha256=source_summary_sha,
    )

    final_outputs = (
        final_dir / "algorithm_io_matrix.csv",
        final_dir / "algorithm_io_matrix.md",
        final_dir / "runtime_performance.csv",
        final_dir / "same_bag_mapping_v1.json",
    )
    final_dir.mkdir(parents=True, exist_ok=False)
    _write_summary_package(outputs=final_outputs, rows=rows, payload=payload)

    source_artifacts = {
        path.relative_to(run).as_posix(): _sha256_file(path) for path in canonical_outputs
    }
    final_inputs: dict[str, str] = {
        "manifest.json": _sha256_file(run / "manifest.json"),
    }
    common_metadata = run / "standardized" / "map_sampling" / "common_matched_metadata.json"
    if common_metadata.is_file():
        final_inputs[common_metadata.relative_to(run).as_posix()] = _sha256_file(common_metadata)
    for row in rows:
        algorithm_id = str(row["algorithm_id"])
        paths = map_artifact_paths(run, algorithm_id)
        metadata_path = (
            paths.unified_metadata
            if paths.unified_metadata.is_file()
            else paths.compat_unified_metadata
        )
        runtime_path = run / "metrics" / "runtime" / f"{algorithm_id}.json"
        trajectory_path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
        for path in (metadata_path, runtime_path, trajectory_path):
            final_inputs[path.relative_to(run).as_posix()] = _sha256_file(path)

    lineage = {
        "schema": FINALIZATION_SCHEMA,
        "reason": "PREMATURE_IMMUTABLE_SUMMARY",
        "created_at": _now_iso(),
        "source_summary_sha256": source_summary_sha,
        "source_artifacts": source_artifacts,
        "final_inputs": final_inputs,
        "final_summary": final_outputs[3].relative_to(run).as_posix(),
        "mutation_policy": "APPEND_ONLY_NO_SOURCE_OVERWRITE",
    }
    (final_dir / "lineage.json").write_text(
        json.dumps(lineage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload
