from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

CHUNK_BYTES = 1024 * 1024


def _stream_file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def sha256_path(path: Path) -> tuple[str, int]:
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"freeze hashing does not follow symlinks: {path}")
    if path.is_file():
        return _stream_file_digest(path)
    if not path.is_dir():
        raise FileNotFoundError(path)

    digest = hashlib.sha256()
    total = 0
    files = sorted(p for p in path.rglob("*") if p.is_file())
    for item in files:
        if item.is_symlink():
            raise ValueError(f"freeze hashing does not follow symlinks: {item}")
        rel = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        with item.open("rb") as stream:
            while True:
                chunk = stream.read(CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
        digest.update(b"\0")
    return digest.hexdigest(), total


def freeze_directory_name(run_id: str, created_at: dt.datetime, git_short_sha: str) -> str:
    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    safe_run = re.sub(r"[^A-Za-z0-9._-]+", "_", str(run_id)).strip("_") or "run"
    stamp = created_at.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_sha = re.sub(r"[^0-9A-Za-z]+", "", str(git_short_sha))
    if not safe_sha:
        raise ValueError("git_short_sha must not be empty")
    return f"{safe_run}_{stamp}_{safe_sha}"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _load_json(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _schema_version_at_least(payload: dict[str, Any], minimum: int) -> bool:
    try:
        return int(payload.get("schema_version") or 0) >= int(minimum)
    except (TypeError, ValueError):
        return False


def _fallback_algorithm_order(
    run: Path,
    manifest: dict[str, Any],
    comparison: dict[str, Any],
) -> tuple[list[str], str, list[str]]:
    comparison_order = [
        str(item.get("algorithm"))
        for item in (comparison.get("algorithms") or [])
        if isinstance(item, dict) and item.get("algorithm")
    ]
    manifest_algorithms = manifest.get("algorithms")
    manifest_order = (
        [str(item) for item in manifest_algorithms]
        if isinstance(manifest_algorithms, dict)
        else []
    )
    candidates = comparison_order or manifest_order
    source = "full_comparison" if comparison_order else "manifest"
    available = [
        algorithm
        for algorithm in candidates
        if (run / "standardized" / "trajectories" / f"{algorithm}.csv").is_file()
    ]
    omitted = [algorithm for algorithm in candidates if algorithm not in available]
    if not available:
        discovered = sorted(
            path.stem
            for path in (run / "standardized" / "trajectories").glob("*.csv")
        )
        if discovered:
            return discovered, "standardized_trajectories", omitted
        raise ValueError(
            "historical run has no algorithms with standardized trajectories for diagnostic rebuild"
        )
    return available, source, omitted


def discover_freeze_sources(run: Path) -> dict[str, Any]:
    run = Path(run).resolve()
    base_core_paths = [
        run / "manifest.json",
        run / "metadata/run_status.json",
        run / "metrics/full_comparison.json",
    ]
    for path in base_core_paths:
        if not path.is_file():
            raise FileNotFoundError(
                f"required freeze source artifact is missing: {path.relative_to(run).as_posix()}"
            )

    manifest = _load_json(run / "manifest.json")
    run_status = _load_json(run / "metadata/run_status.json")
    comparison = _load_json(run / "metrics/full_comparison.json")
    timeline_path = run / "metrics/diagnostic_timeline.json"
    timeline_present = timeline_path.is_file()
    diagnostic_timeline = _load_json(timeline_path) if timeline_present else {}
    raw_discontinuity = run / "metrics/trajectory_discontinuity.json"

    unified_timeline = timeline_present and _schema_version_at_least(
        diagnostic_timeline, 1
    )
    rebuild_required = not timeline_present
    core_paths = list(base_core_paths)
    omitted_algorithms: list[str] = []

    if timeline_present:
        core_paths.append(timeline_path)
        raw_algorithms = diagnostic_timeline.get("algorithm_order")
        if not isinstance(raw_algorithms, list) or not raw_algorithms:
            raise ValueError(
                "metrics/diagnostic_timeline.json must contain a non-empty algorithm_order"
            )
        algorithms = [str(item) for item in raw_algorithms]
        algorithm_source = "diagnostic_timeline"
        if not unified_timeline:
            core_paths.append(raw_discontinuity)
            if not raw_discontinuity.is_file():
                raise FileNotFoundError(
                    "required freeze source artifact is missing: metrics/trajectory_discontinuity.json"
                )
    else:
        algorithms, algorithm_source, omitted_algorithms = _fallback_algorithm_order(
            run, manifest, comparison
        )

    required_files = list(core_paths)
    for algorithm in algorithms:
        required_files.append(
            run / "standardized" / "trajectories" / f"{algorithm}.csv"
        )
        if timeline_present:
            required_files.append(
                run / "metrics" / "diagnostic_timeline" / f"{algorithm}.csv"
            )
    for path in required_files:
        if not path.is_file():
            raise FileNotFoundError(
                f"required freeze source artifact is missing: {path.relative_to(run).as_posix()}"
            )

    pointcloud_index = run / "metrics/pointcloud_frame_index.json"
    phase_analysis = run / "metrics/phase_analysis.json"
    bag_analysis = run / "metrics/bag_analysis.json"
    map_metrics = run / "figures/fast_livo2_baseline_maps/map_comparison_metrics.json"
    optional_candidates = [
        raw_discontinuity,
        pointcloud_index,
        phase_analysis,
        bag_analysis,
        map_metrics,
    ]
    resource_paths = [
        run / "metrics/diagnostic_timeline/resources" / f"{algorithm}.csv"
        for algorithm in algorithms
    ]
    optional_files = [
        path for path in optional_candidates + resource_paths if path.is_file()
    ]
    optional_evidence = {
        "maps": map_metrics.is_file(),
        "phase_analysis": phase_analysis.is_file(),
        "pointcloud_index": pointcloud_index.is_file(),
        "resource_timelines": timeline_present
        and all(path.is_file() for path in resource_paths),
    }
    if unified_timeline:
        optional_evidence["trajectory_discontinuity"] = raw_discontinuity.is_file()

    compatibility = {
        "source_timeline_present": timeline_present,
        "unified_diagnostic_timeline": unified_timeline,
        "diagnostic_timeline_schema_version": (
            diagnostic_timeline.get("schema_version") if timeline_present else None
        ),
        "rebuild_required": rebuild_required,
        "algorithm_source": algorithm_source,
        "omitted_algorithms_without_trajectory": omitted_algorithms,
        "raw_trajectory_discontinuity_present": raw_discontinuity.is_file(),
        "raw_trajectory_discontinuity_required": timeline_present
        and not unified_timeline,
    }
    return {
        "algorithms": algorithms,
        "required_files": required_files,
        "optional_files": optional_files,
        "optional_evidence": optional_evidence,
        "diagnostic_compatibility": compatibility,
        "run_status": run_status,
        "manifest": manifest,
        "diagnostic_timeline": diagnostic_timeline,
    }


def resolve_git_identity(repo_root: Path) -> dict[str, str]:
    repo_root = Path(repo_root).resolve()
    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, text=True
    ).strip()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
    ).strip()
    return {"branch": branch, "commit": commit, "short_sha": commit[:8]}


def _copy_source_artifact(run: Path, frozen: Path, source: Path) -> dict[str, Any]:
    relative = source.relative_to(run)
    target = frozen / "source" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, size = sha256_path(source)
    shutil.copy2(source, target)
    return {
        "source_path": relative.as_posix(),
        "bundle_path": (Path("source") / relative).as_posix(),
        "size_bytes": size,
        "sha256": digest,
    }


def _copy_algorithm_configs(
    repo_root: Path,
    frozen: Path,
    manifest_algorithms: dict[str, Any],
    algorithms: list[str],
) -> dict[str, dict[str, Any]]:
    repo_root = Path(repo_root).resolve()
    output: dict[str, dict[str, Any]] = {}
    for algorithm in algorithms:
        config = manifest_algorithms.get(algorithm) or {}
        if not isinstance(config, dict):
            config = {}
        declared = config.get("config")
        if not declared:
            output[algorithm] = {"declared": False}
            continue
        source = Path(str(declared)).expanduser()
        if not source.is_absolute():
            source = (repo_root / source).resolve()
        else:
            source = source.resolve()
        if not source.exists():
            raise FileNotFoundError(
                f"algorithm config does not exist for {algorithm}: {source}"
            )
        digest, size = sha256_path(source)
        target = frozen / "source" / "configs" / algorithm / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        output[algorithm] = {
            "declared": True,
            "source_path": str(source),
            "bundle_path": target.relative_to(frozen).as_posix(),
            "size_bytes": size,
            "sha256": digest,
        }
    return output


def _compatibility_artifact_record(
    frozen: Path, source_relative_path: str
) -> dict[str, Any]:
    bundle_relative = (Path("source") / source_relative_path).as_posix()
    target = frozen / bundle_relative
    digest, size = sha256_path(target)
    return {
        "bundle_path": bundle_relative,
        "role": "compatibility_derived_diagnostic_timeline",
        "derivation": "standardized-trajectories-fixed-rate-v1",
        "size_bytes": size,
        "sha256": digest,
    }


def _verify_captured_artifacts(frozen: Path, manifest: dict[str, Any]) -> None:
    for record in manifest.get("source_artifacts") or []:
        if not isinstance(record, dict) or not record.get("bundle_path"):
            continue
        relative, target = _resolve_bundle_relative(frozen, str(record["bundle_path"]))
        current_sha, current_size = sha256_path(target)
        if record.get("sha256") != current_sha or record.get("size_bytes") != current_size:
            raise ValueError(f"source artifact changed after capture: {relative}")
    for record in manifest.get("compatibility_artifacts") or []:
        if not isinstance(record, dict) or not record.get("bundle_path"):
            continue
        relative, target = _resolve_bundle_relative(frozen, str(record["bundle_path"]))
        current_sha, current_size = sha256_path(target)
        if record.get("sha256") != current_sha or record.get("size_bytes") != current_size:
            raise ValueError(
                f"compatibility artifact changed after derivation: {relative}"
            )
    configs = manifest.get("config_sources") or {}
    if isinstance(configs, dict):
        for algorithm, record in configs.items():
            if not isinstance(record, dict) or not record.get("declared"):
                continue
            relative, target = _resolve_bundle_relative(frozen, str(record["bundle_path"]))
            current_sha, current_size = sha256_path(target)
            if record.get("sha256") != current_sha or record.get("size_bytes") != current_size:
                raise ValueError(
                    f"algorithm config changed after capture: {algorithm}: {relative}"
                )


def prepare_freeze(
    run: Path,
    *,
    baseline: str,
    language: str,
    repo_root: Path,
    created_at: dt.datetime | None = None,
) -> Path:
    run = Path(run).resolve()
    repo_root = Path(repo_root).resolve()
    sources = discover_freeze_sources(run)
    run_status = sources["run_status"]
    run_id = str(run_status.get("run_id") or run.name)
    run_state = str(run_status.get("state") or "UNKNOWN")

    if baseline not in sources["algorithms"]:
        raise FileNotFoundError(
            f"freeze baseline standardized trajectory is unavailable: {baseline}"
        )

    if created_at is None:
        created_at = dt.datetime.now(dt.timezone.utc)
    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    created_at = created_at.astimezone(dt.timezone.utc)

    git_identity = resolve_git_identity(repo_root)
    identity = freeze_directory_name(run_id, created_at, git_identity["short_sha"])
    frozen = run / "frozen" / identity
    frozen.mkdir(parents=True, exist_ok=False)
    for name in ("source", "viewer", "evidence", "report"):
        (frozen / name).mkdir()

    manifest = sources["manifest"]
    dataset = manifest.get("dataset")
    dataset_dict = dataset if isinstance(dataset, dict) else {}
    bag_dir = dataset_dict.get("bag_dir")
    bag_path: Path | None = None
    if bag_dir:
        candidate = Path(str(bag_dir)).expanduser()
        bag_path = (
            (run / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        )

    manifest_algorithms = manifest.get("algorithms")
    if not isinstance(manifest_algorithms, dict):
        manifest_algorithms = {}
    algorithms = sources["algorithms"]
    algorithm_provenance = {
        algorithm: manifest_algorithms.get(algorithm, {}) for algorithm in algorithms
    }

    evaluation = manifest.get("evaluation")
    if isinstance(evaluation, dict) and "ground_truth_available" in evaluation:
        ground_truth_available = bool(evaluation["ground_truth_available"])
    else:
        ground_truth_available = bool(dataset_dict.get("ground_truth"))

    payload = {
        "schema_version": 1,
        "freeze_state": "INCOMPLETE",
        "created_at_utc": created_at.isoformat(),
        "completed_at_utc": None,
        "source_run": {"path": str(run), "run_id": run_id, "state": run_state},
        "benchmark": git_identity,
        "baseline": baseline,
        "language": language,
        "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
        "ground_truth_available": ground_truth_available,
        "algorithms": algorithms,
        "algorithm_provenance": algorithm_provenance,
        "calibration": dict(manifest.get("calibration") or {}),
        "config_sources": {},
        "optional_evidence": sources["optional_evidence"],
        "diagnostic_compatibility": sources["diagnostic_compatibility"],
        "dataset_source": {
            "path": str(bag_path) if bag_path is not None else None,
            "size_bytes": None,
            "sha256": None,
        },
        "source_artifacts": [],
        "compatibility_artifacts": [],
        "generated_artifacts": [],
        "failure": None,
    }
    write_json_atomic(frozen / "freeze_manifest.json", payload)

    stage = "source_artifacts"
    try:
        payload["source_artifacts"] = [
            _copy_source_artifact(run, frozen, path)
            for path in sources["required_files"] + sources["optional_files"]
        ]

        if bool(sources["diagnostic_compatibility"].get("rebuild_required")):
            stage = "diagnostic_compatibility"
            from freeze_compat import build_compat_diagnostic_timeline

            derivation = build_compat_diagnostic_timeline(
                frozen / "source",
                algorithms=algorithms,
                baseline=baseline,
            )
            payload["compatibility_artifacts"] = [
                _compatibility_artifact_record(frozen, relative)
                for relative in derivation["artifacts"]
            ]
            payload["diagnostic_compatibility"] = {
                **dict(payload["diagnostic_compatibility"]),
                "rebuild_completed": True,
                "derivation": derivation,
            }
            write_json_atomic(frozen / "freeze_manifest.json", payload)

        stage = "config_sources"
        payload["config_sources"] = _copy_algorithm_configs(
            repo_root, frozen, manifest_algorithms, algorithms
        )
        write_json_atomic(frozen / "freeze_manifest.json", payload)

        stage = "dataset_source"
        if not isinstance(dataset, dict):
            raise ValueError("manifest.json dataset must be an object")
        if not bag_dir:
            raise ValueError("manifest.json dataset.bag_dir is required for freeze provenance")
        assert bag_path is not None
        if not bag_path.exists():
            raise FileNotFoundError(f"dataset bag_dir does not exist: {bag_path}")
        bag_sha, bag_size = sha256_path(bag_path)
        payload["dataset_source"] = {
            "path": str(bag_path),
            "size_bytes": bag_size,
            "sha256": bag_sha,
        }
        write_json_atomic(frozen / "freeze_manifest.json", payload)
        return frozen
    except Exception as exc:
        payload["failure"] = {
            "stage": stage,
            "type": type(exc).__name__,
            "message": str(exc),
        }
        write_json_atomic(frozen / "freeze_manifest.json", payload)
        raise


def _load_freeze_manifest(frozen: Path) -> dict[str, Any]:
    manifest_path = Path(frozen) / "freeze_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    return _load_json(manifest_path)


def _require_incomplete(manifest: dict[str, Any]) -> None:
    if manifest.get("freeze_state") == "COMPLETE":
        raise ValueError("frozen bundle is already COMPLETE")


def _resolve_bundle_relative(frozen: Path, relative_path: str) -> tuple[str, Path]:
    frozen = Path(frozen).resolve()
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts or str(relative) in {"", "."}:
        raise ValueError(f"generated artifact must use a safe relative path: {relative_path}")
    normalized = relative.as_posix()
    target = (frozen / relative).resolve()
    try:
        target.relative_to(frozen)
    except ValueError as exc:
        raise ValueError(
            f"generated artifact must stay under frozen bundle: {relative_path}"
        ) from exc
    return normalized, target


def register_generated_artifact(
    frozen: Path, relative_path: str, role: str
) -> dict[str, Any]:
    frozen = Path(frozen).resolve()
    manifest = _load_freeze_manifest(frozen)
    _require_incomplete(manifest)
    normalized, target = _resolve_bundle_relative(frozen, relative_path)
    digest, size = sha256_path(target)
    record = {
        "path": normalized,
        "role": str(role),
        "size_bytes": size,
        "sha256": digest,
    }
    existing = manifest.get("generated_artifacts")
    if not isinstance(existing, list):
        existing = []
    manifest["generated_artifacts"] = [
        item
        for item in existing
        if not isinstance(item, dict) or item.get("path") != normalized
    ] + [record]
    manifest["freeze_state"] = "INCOMPLETE"
    manifest["completed_at_utc"] = None
    write_json_atomic(frozen / "freeze_manifest.json", manifest)
    return record


def finalize_freeze(
    frozen: Path,
    *,
    required_generated_paths: tuple[str, ...],
    completed_at: dt.datetime | None = None,
) -> dict[str, Any]:
    frozen = Path(frozen).resolve()
    manifest = _load_freeze_manifest(frozen)
    _require_incomplete(manifest)
    records = manifest.get("generated_artifacts")
    if not isinstance(records, list):
        records = []

    _verify_captured_artifacts(frozen, manifest)

    for relative in required_generated_paths:
        normalized, target = _resolve_bundle_relative(frozen, relative)
        if not target.is_file():
            raise FileNotFoundError(normalized)
        current_sha, current_size = sha256_path(target)
        record = next(
            (
                item
                for item in records
                if isinstance(item, dict) and item.get("path") == normalized
            ),
            None,
        )
        if record is None:
            raise ValueError(f"generated artifact is not registered: {normalized}")
        if record.get("sha256") != current_sha or record.get("size_bytes") != current_size:
            raise ValueError(f"generated artifact changed after registration: {normalized}")

    if completed_at is None:
        completed_at = dt.datetime.now(dt.timezone.utc)
    if completed_at.tzinfo is None:
        raise ValueError("completed_at must be timezone-aware")
    completed_at = completed_at.astimezone(dt.timezone.utc)
    manifest["freeze_state"] = "COMPLETE"
    manifest["completed_at_utc"] = completed_at.isoformat()
    write_json_atomic(frozen / "freeze_manifest.json", manifest)
    return manifest
