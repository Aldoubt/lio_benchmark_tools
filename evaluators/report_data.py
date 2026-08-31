from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from freeze_experiment import register_generated_artifact, write_json_atomic

METRIC_CLASS = "relative-to-baseline/diagnostic/non-ground-truth"
NO_GT_DISCLAIMER = (
    "No independent ground truth is available. Accuracy-style metrics are "
    "relative-to-baseline diagnostics, not ATE/RPE or absolute accuracy rankings."
)


def _load_json_object(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if required:
            raise
        return None
    if not isinstance(payload, dict):
        if required:
            raise ValueError(f"expected JSON object: {path}")
        return None
    return payload


def _rank_window(window: dict[str, Any]) -> tuple[float, str, float, str]:
    return (
        -float(window.get("severity") or 0.0),
        str(window.get("algorithm") or ""),
        float(window.get("start_bag_time_s") or 0.0),
        str(window.get("window_id") or ""),
    )


def select_representative_anomalies(
    windows: list[dict[str, Any]],
    *,
    unhealthy_algorithms: set[str] | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    if limit < 0:
        raise ValueError("representative anomaly limit must be >= 0")
    if limit == 0:
        return []
    unhealthy = set(unhealthy_algorithms or set())

    deduplicated: dict[str, dict[str, Any]] = {}
    for raw in windows:
        if not isinstance(raw, dict):
            continue
        window_id = str(raw.get("window_id") or "")
        algorithm = str(raw.get("algorithm") or "")
        if not window_id or not algorithm:
            continue
        candidate = dict(raw)
        previous = deduplicated.get(window_id)
        if previous is None or _rank_window(candidate) < _rank_window(previous):
            deduplicated[window_id] = candidate
    ranked = sorted(deduplicated.values(), key=_rank_window)

    selected: dict[str, dict[str, Any]] = {}

    def add_best(predicate: Callable[[dict[str, Any]], bool]) -> None:
        if len(selected) >= limit:
            return
        candidate = next(
            (
                item
                for item in ranked
                if item["window_id"] not in selected and predicate(item)
            ),
            None,
        )
        if candidate is not None:
            selected[str(candidate["window_id"])] = candidate

    add_best(lambda item: "position_jump" in (item.get("types") or []))
    add_best(lambda item: "yaw_jump" in (item.get("types") or []))

    unhealthy_candidates = [
        item for item in ranked if str(item.get("algorithm")) in unhealthy
    ]
    represented_unhealthy: set[str] = set()
    for item in unhealthy_candidates:
        algorithm = str(item["algorithm"])
        if algorithm in represented_unhealthy:
            continue
        if len(selected) >= limit:
            break
        selected[str(item["window_id"])] = item
        represented_unhealthy.add(algorithm)

    for item in ranked:
        if len(selected) >= limit:
            break
        selected.setdefault(str(item["window_id"]), item)

    return sorted(selected.values(), key=_rank_window)


def _semantic_builder() -> Callable[..., dict[str, Any]]:
    from current_run_report import build_report

    return build_report


def _algorithm_index(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in report.get("algorithms") or []:
        if isinstance(item, dict) and item.get("algorithm"):
            result[str(item["algorithm"])] = item
    return result


def _registered_path(manifest: dict[str, Any], path: str) -> bool:
    return any(
        isinstance(item, dict) and item.get("path") == path
        for item in (manifest.get("generated_artifacts") or [])
    )


def build_report_data(
    frozen: Path,
    *,
    semantic_builder: Callable[..., dict[str, Any]] | None = None,
    representative_limit: int = 6,
) -> dict[str, Any]:
    frozen = Path(frozen).resolve()
    manifest_path = frozen / "freeze_manifest.json"
    manifest = _load_json_object(manifest_path)
    assert manifest is not None
    if manifest.get("freeze_state") == "COMPLETE":
        raise ValueError("frozen bundle is already COMPLETE")

    source = frozen / "source"
    source_manifest = _load_json_object(source / "manifest.json")
    timeline = _load_json_object(source / "metrics" / "diagnostic_timeline.json")
    assert source_manifest is not None and timeline is not None

    baseline = str(manifest.get("baseline") or "")
    if not baseline:
        raise ValueError("freeze manifest is missing baseline")
    builder = semantic_builder or _semantic_builder()
    semantic = builder(source, baseline=baseline)
    if not isinstance(semantic, dict):
        raise ValueError("current-run semantic builder returned a non-object")

    metric_class = str(manifest.get("metric_class") or "")
    if metric_class != METRIC_CLASS:
        raise ValueError(f"unsupported freeze metric class: {metric_class}")
    semantic_metric_class = str(semantic.get("metric_class") or metric_class)
    if semantic_metric_class != metric_class:
        raise ValueError(
            f"semantic report metric class differs from freeze manifest: {semantic_metric_class}"
        )

    indexed = _algorithm_index(semantic)
    declared_algorithms = [str(item) for item in (manifest.get("algorithms") or [])]
    missing_semantics = [
        algorithm for algorithm in declared_algorithms if algorithm not in indexed
    ]
    if missing_semantics:
        raise ValueError(
            "semantic report omitted frozen algorithms: " + ", ".join(missing_semantics)
        )

    unhealthy = {
        algorithm
        for algorithm, item in indexed.items()
        if not bool(item.get("trajectory_health_pass", item.get("health_pass", False)))
        or str(item.get("status") or "").upper() not in {"", "SUCCESS", "COMPLETED"}
    }
    windows = [
        dict(item)
        for item in (timeline.get("anomaly_windows") or [])
        if isinstance(item, dict)
    ]
    representatives = select_representative_anomalies(
        windows,
        unhealthy_algorithms=unhealthy,
        limit=representative_limit,
    )

    phase_payload = _load_json_object(
        source / "metrics" / "phase_analysis.json", required=False
    )
    phase_summary = {
        "available": phase_payload is not None,
        "data": phase_payload,
    }

    ground_truth_available = bool(manifest.get("ground_truth_available"))
    disclaimer = (
        "Independent ground truth is available; absolute metrics must still be read from the explicit ground-truth evaluation outputs."
        if ground_truth_available
        else NO_GT_DISCLAIMER
    )

    runtime_health = {
        algorithm: {
            "status": indexed[algorithm].get("status"),
            "health_flags": list(indexed[algorithm].get("health_flags") or []),
            "trajectory_health_pass": bool(
                indexed[algorithm].get(
                    "trajectory_health_pass",
                    indexed[algorithm].get("health_pass", False),
                )
            ),
            "recommendation_eligible": bool(
                indexed[algorithm].get("recommendation_eligible", False)
            ),
        }
        for algorithm in declared_algorithms
    }
    trajectory_summary = {
        algorithm: dict(indexed[algorithm].get("trajectory") or {})
        for algorithm in declared_algorithms
    }
    relative_summary = {
        algorithm: dict(indexed[algorithm].get("relative_to_baseline") or {})
        for algorithm in declared_algorithms
    }
    map_summary = {
        algorithm: {
            **dict(indexed[algorithm].get("map") or {}),
            "health_pass": indexed[algorithm].get("map_health_pass"),
            "health_flags": list(indexed[algorithm].get("map_health_flags") or []),
        }
        for algorithm in declared_algorithms
    }
    resource_summary = {
        algorithm: dict(indexed[algorithm].get("resource") or {})
        for algorithm in declared_algorithms
    }
    trajectory_diagnostics = {
        algorithm: dict(indexed[algorithm].get("trajectory_diagnostics") or {})
        for algorithm in declared_algorithms
    }
    timeline_algorithms = timeline.get("algorithms") or {}
    anomaly_counts = {
        algorithm: (
            dict(timeline_algorithms.get(algorithm) or {})
            if isinstance(timeline_algorithms, dict)
            else {}
        )
        for algorithm in declared_algorithms
    }

    recommendations = dict(semantic.get("recommendations") or {})
    report_data = {
        "schema_version": 1,
        "report_type": "frozen_lio_benchmark_experiment",
        "experiment": {
            "run_id": (manifest.get("source_run") or {}).get("run_id"),
            "source_run_state": (manifest.get("source_run") or {}).get("state"),
            "freeze_created_at_utc": manifest.get("created_at_utc"),
            "generated_at_utc": manifest.get("created_at_utc"),
            "benchmark": dict(manifest.get("benchmark") or {}),
            "baseline": baseline,
            "language": manifest.get("language"),
        },
        "metric_class": metric_class,
        "ground_truth_available": ground_truth_available,
        "ground_truth_disclaimer": disclaimer,
        "dataset_timing": {
            "dataset": dict(source_manifest.get("dataset") or {}),
            "playback_rate": source_manifest.get("playback_rate"),
            "dataset_source": dict(manifest.get("dataset_source") or {}),
        },
        "calibration": dict(source_manifest.get("calibration") or {}),
        "algorithm_provenance": dict(manifest.get("algorithm_provenance") or {}),
        "runtime_health": runtime_health,
        "trajectory_summary": trajectory_summary,
        "baseline_relative_diagnostics": relative_summary,
        "map_health": map_summary,
        "resource_summary": resource_summary,
        "trajectory_diagnostics": trajectory_diagnostics,
        "phase_summary": phase_summary,
        "anomaly_summary": {
            "window_count": len(windows),
            "per_algorithm": anomaly_counts,
            "representative_cases": representatives,
            "selected_window_ids": [
                str(item["window_id"]) for item in representatives
            ],
            "selection_policy": {
                "maximum_cases": representative_limit,
                "order": "severity-descending with position/yaw and unhealthy-algorithm coverage",
                "deduplicate_by": "window_id",
            },
        },
        "evidence_based_conclusions": {
            "scope": (
                "absolute and baseline-relative evidence; see explicit metric classes"
                if ground_truth_available
                else "baseline-relative diagnostic only"
            ),
            "health_valid_algorithms": list(
                recommendations.get("health_valid_algorithms") or []
            ),
            "not_recommended_this_run": list(
                recommendations.get("not_recommended_this_run") or []
            ),
            "closest_to_baseline": recommendations.get("closest_to_baseline"),
            "recommendations": recommendations,
        },
        "reproducibility_checklist": {
            "benchmark_commit_recorded": bool(
                (manifest.get("benchmark") or {}).get("commit")
            ),
            "dataset_sha256_recorded": bool(
                (manifest.get("dataset_source") or {}).get("sha256")
            ),
            "algorithm_provenance_recorded": all(
                algorithm in (manifest.get("algorithm_provenance") or {})
                for algorithm in declared_algorithms
            ),
            "calibration_disclosed": "calibration" in source_manifest,
            "core_source_artifacts_hashed": bool(manifest.get("source_artifacts")),
            "native_rerun_registered": _registered_path(
                manifest, "viewer/diagnostic.rrd"
            ),
        },
        "optional_evidence": {
            **dict(manifest.get("optional_evidence") or {}),
            "rerun_pointcloud": dict(
                (manifest.get("rerun_recording") or {}).get("pointcloud_evidence")
                or {}
            ),
        },
        "limitations": list(semantic.get("limitations") or []),
    }

    output = frozen / "report_data.json"
    write_json_atomic(output, report_data)
    artifact = register_generated_artifact(
        frozen, "report_data.json", "shared_report_data"
    )

    updated_manifest = _load_json_object(manifest_path)
    assert updated_manifest is not None
    updated_manifest["selected_anomaly_window_ids"] = report_data["anomaly_summary"][
        "selected_window_ids"
    ]
    updated_manifest["failure"] = None
    write_json_atomic(manifest_path, updated_manifest)
    return {"report_data": report_data, "artifact": artifact}
