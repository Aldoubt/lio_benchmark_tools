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
STATIC_POINT_DENSE_STEP = 10


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
            artifact = register_generated_artifact(frozen, target_rel, "static_report_evidence")
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


def _write_anomaly_cases(frozen: Path, report_data: dict[str, Any]) -> list[dict[str, Any]]:
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
        artifact = register_generated_artifact(frozen, relative, "representative_anomaly_case")
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


def _pointcloud_runtime_api():
    """Load the same indexed-LiDAR and projection implementation used by Native Rerun."""
    from rerun_diagnostic_viewer import (
        _projection_context,
        _read_indexed_lidar_scans,
        nearest_frame,
    )
    from viewer_projection import project_points_to_display_world

    return nearest_frame, _read_indexed_lidar_scans, _projection_context, project_points_to_display_world


def _case_target_time(window: dict[str, Any]) -> float:
    if window.get("center_bag_time_s") is not None:
        return float(window["center_bag_time_s"])
    if window.get("view_start_bag_time_s") is not None and window.get("view_end_bag_time_s") is not None:
        return 0.5 * (
            float(window["view_start_bag_time_s"]) + float(window["view_end_bag_time_s"])
        )
    start = float(window.get("start_bag_time_s") or 0.0)
    end = float(window.get("end_bag_time_s") or start)
    return 0.5 * (start + end)


def _write_pointcloud_case_figure(
    path: Path,
    *,
    window: dict[str, Any],
    frame_bag_time_s: float,
    raw_points: Any,
    baseline_points: Any,
    target_points: Any,
    baseline: str,
    target_algorithm: str,
) -> None:
    import numpy as np
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    raw = np.asarray(raw_points, dtype=np.float64)
    baseline_world = np.asarray(baseline_points, dtype=np.float64)
    target_world = np.asarray(target_points, dtype=np.float64)
    panels: list[tuple[str, np.ndarray]] = [
        ("Raw LiDAR XY", raw),
        (f"{baseline} world XY", baseline_world),
    ]
    if target_algorithm != baseline:
        panels.append((f"{target_algorithm} world XY", target_world))

    figure, axes = plt.subplots(1, len(panels), figsize=(5.2 * len(panels), 5.0), constrained_layout=True)
    if len(panels) == 1:
        axes = [axes]
    for axis, (title, points) in zip(axes, panels):
        finite = points[np.isfinite(points).all(axis=1)] if points.ndim == 2 and points.shape[1] >= 2 else np.empty((0, 3))
        if len(finite):
            axis.scatter(finite[:, 0], finite[:, 1], s=0.7, alpha=0.6)
        axis.set_title(title)
        axis.set_xlabel("X (m)")
        axis.set_ylabel("Y (m)")
        axis.set_aspect("equal", adjustable="datalim")
        axis.grid(alpha=0.2)
    types = ",".join(str(item) for item in (window.get("types") or [])) or "anomaly"
    figure.suptitle(
        f"{window.get('window_id', 'case')} | frame={frame_bag_time_s:.3f}s | {types} | severity={float(window.get('severity') or 0.0):.2f}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _render_pointcloud_cases(
    frozen: Path,
    source_run: Path | None,
    freeze_manifest: dict[str, Any],
    report_data: dict[str, Any],
) -> dict[str, Any]:
    import numpy as np

    if source_run is None or not source_run.is_dir():
        return {
            "available": False,
            "source_available": False,
            "reason": "source_run_unavailable_for_static_pointcloud",
            "cases": [],
        }

    index_path = source_run / "metrics/pointcloud_frame_index.json"
    if not index_path.is_file():
        return {
            "available": False,
            "source_available": False,
            "reason": "pointcloud_frame_index_missing",
            "cases": [],
        }
    index_payload = _load_json(index_path)
    frames = [dict(item) for item in (index_payload.get("frames") or []) if isinstance(item, dict)]
    if not frames:
        return {
            "available": False,
            "source_available": False,
            "reason": "pointcloud_frame_index_empty",
            "cases": [],
        }

    summary = report_data.get("anomaly_summary") or {}
    windows = [dict(item) for item in (summary.get("representative_cases") or []) if isinstance(item, dict)]
    if not windows:
        return {
            "available": False,
            "source_available": True,
            "reason": "no_representative_anomaly_cases",
            "cases": [],
        }

    sqlite_db = Path(str(index_payload.get("sqlite_db") or "")).expanduser()
    if not sqlite_db.is_absolute():
        sqlite_db = (source_run / sqlite_db).resolve()
    else:
        sqlite_db = sqlite_db.resolve()
    if not sqlite_db.is_file():
        return {
            "available": False,
            "source_available": False,
            "reason": "pointcloud_sqlite_missing",
            "cases": [],
        }
    lidar_topic = str(index_payload.get("lidar_topic") or "")
    lidar_type = str(index_payload.get("lidar_type") or "")
    if not lidar_topic or not lidar_type:
        return {
            "available": False,
            "source_available": False,
            "reason": "pointcloud_frame_index_invalid",
            "cases": [],
        }

    nearest_frame, read_scans, projection_context, project_points = _pointcloud_runtime_api()
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unique_frames: dict[int, dict[str, Any]] = {}
    for window in windows:
        frame = nearest_frame(frames, _case_target_time(window))
        selected.append((window, frame))
        unique_frames[int(frame["message_id"])] = frame
    selected_frames = sorted(unique_frames.values(), key=lambda item: float(item["bag_time_s"]))

    source_manifest = _load_json(frozen / "source/manifest.json")
    evaluation = source_manifest.get("evaluation") or {}
    minimum_range_m = float(evaluation.get("minimum_range_m", 0.5))
    maximum_range_m = float(evaluation.get("maximum_range_m", 100.0))
    scans = read_scans(
        sqlite_db,
        lidar_topic,
        lidar_type,
        selected_frames,
        dense_step=STATIC_POINT_DENSE_STEP,
        minimum_range_m=minimum_range_m,
        maximum_range_m=maximum_range_m,
    )
    if not scans:
        return {
            "available": False,
            "source_available": True,
            "reason": "selected_pointcloud_messages_unavailable",
            "cases": [],
        }

    baseline = str(freeze_manifest.get("baseline") or "")
    if not baseline:
        raise ValueError("freeze manifest is missing baseline for pointcloud evidence")
    declared_algorithms = [str(item) for item in (freeze_manifest.get("algorithms") or [])]
    required_algorithms = [baseline]
    for window in windows:
        algorithm = str(window.get("algorithm") or "")
        if algorithm and algorithm not in required_algorithms:
            required_algorithms.append(algorithm)
    missing_algorithms = [item for item in required_algorithms if item not in declared_algorithms]
    if missing_algorithms:
        raise ValueError(
            "representative pointcloud cases reference algorithms outside freeze: "
            + ", ".join(missing_algorithms)
        )
    trajectories, alignments, origin = projection_context(source_run, required_algorithms, baseline)

    calibration = (freeze_manifest.get("calibration") or {}).get("lidar_to_imu") or {}
    extrinsic_rotation = np.asarray(
        calibration.get("rotation", np.eye(3)), dtype=np.float64
    ).reshape(3, 3)
    extrinsic_translation = np.asarray(
        calibration.get("translation", np.zeros(3)), dtype=np.float64
    ).reshape(3)
    max_gap_value = evaluation.get("max_pose_interpolation_gap_s")
    max_gap_s = float(max_gap_value) if max_gap_value is not None else None

    output: list[dict[str, Any]] = []
    for index, (window, frame) in enumerate(selected, start=1):
        frame_time = float(frame["bag_time_s"])
        scan = min(scans, key=lambda item: abs(float(item.bag_time_s) - frame_time))
        baseline_rotation, baseline_translation = alignments[baseline]
        baseline_projected, baseline_valid = project_points(
            scan.points_xyz,
            scan.point_times_s,
            trajectories[baseline],
            extrinsic_rotation,
            extrinsic_translation,
            baseline_rotation,
            baseline_translation,
            origin,
            max_gap_s,
        )
        if not np.any(baseline_valid):
            continue
        target_algorithm = str(window.get("algorithm") or baseline)
        if target_algorithm == baseline:
            target_projected = baseline_projected
            target_valid = baseline_valid
        else:
            target_rotation, target_translation = alignments[target_algorithm]
            target_projected, target_valid = project_points(
                scan.points_xyz,
                scan.point_times_s,
                trajectories[target_algorithm],
                extrinsic_rotation,
                extrinsic_translation,
                target_rotation,
                target_translation,
                origin,
                max_gap_s,
            )
            if not np.any(target_valid):
                continue

        window_id = str(window.get("window_id") or f"case_{index:02d}")
        relative = (
            Path("evidence/anomalies")
            / f"case_{index:02d}_{_safe_name(window_id)}_pointcloud.png"
        ).as_posix()
        _write_pointcloud_case_figure(
            frozen / relative,
            window=window,
            frame_bag_time_s=frame_time,
            raw_points=np.asarray(scan.points_xyz),
            baseline_points=baseline_projected[baseline_valid],
            target_points=target_projected[target_valid],
            baseline=baseline,
            target_algorithm=target_algorithm,
        )
        artifact = register_generated_artifact(
            frozen, relative, "representative_pointcloud_case"
        )
        output.append(
            {
                "window_id": window_id,
                "algorithm": target_algorithm,
                "message_id": int(frame["message_id"]),
                "frame_bag_time_s": frame_time,
                "dense_step": STATIC_POINT_DENSE_STEP,
                "bundle_path": relative,
                "sha256": artifact["sha256"],
                "size_bytes": artifact["size_bytes"],
            }
        )

    return {
        "available": bool(output),
        "source_available": True,
        "reason": None if output else "no_projectable_pointcloud_cases",
        "policy": (
            "nearest indexed LiDAR frame to each deterministic representative anomaly; "
            "world projections reuse viewer_projection.project_points_to_display_world"
        ),
        "cases": output,
    }


def build_report_evidence(frozen: Path) -> dict[str, Any]:
    frozen = Path(frozen).resolve()
    freeze_manifest_path = frozen / "freeze_manifest.json"
    freeze_manifest = _load_json(freeze_manifest_path)
    if freeze_manifest.get("freeze_state") == "COMPLETE":
        raise ValueError("frozen bundle is already COMPLETE")
    report_data = _load_json(frozen / "report_data.json")

    source_value = (freeze_manifest.get("source_run") or {}).get("path")
    source_run = Path(str(source_value)).expanduser().resolve() if source_value else None
    static_figures = _copy_static_figures(frozen, source_run)
    anomaly_cases = _write_anomaly_cases(frozen, report_data)

    rerun_pointcloud = ((report_data.get("optional_evidence") or {}).get("rerun_pointcloud") or {})
    pointcloud_source_available = bool(rerun_pointcloud.get("enabled"))
    if pointcloud_source_available:
        try:
            pointcloud_case_evidence = _render_pointcloud_cases(
                frozen, source_run, freeze_manifest, report_data
            )
        except Exception as exc:
            pointcloud_case_evidence = {
                "available": False,
                "source_available": True,
                "reason": f"static_pointcloud_render_failed:{type(exc).__name__}:{exc}",
                "cases": [],
            }
    else:
        pointcloud_case_evidence = {
            "available": False,
            "source_available": False,
            "reason": str(
                rerun_pointcloud.get("omission_reason") or "pointcloud_evidence_unavailable"
            ),
            "cases": [],
        }

    evidence_manifest = {
        "schema_version": 1,
        "static_figure_source": {
            "path": str(source_run) if source_run is not None else None,
            "available": bool(source_run is not None and source_run.is_dir()),
            "policy": "copy known pre-existing deterministic report figures only",
        },
        "static_figures": static_figures,
        "anomaly_cases": anomaly_cases,
        "pointcloud_case_evidence": pointcloud_case_evidence,
    }
    output = frozen / "evidence/evidence_manifest.json"
    write_json_atomic(output, evidence_manifest)
    artifact = register_generated_artifact(
        frozen, "evidence/evidence_manifest.json", "report_evidence_manifest"
    )
    return {"manifest": evidence_manifest, "artifact": artifact}
