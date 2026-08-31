from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from freeze_experiment import register_generated_artifact, write_json_atomic


def _load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _pointcloud_runtime_status(topic_type: str) -> tuple[bool, str | None]:
    try:
        from rclpy.serialization import deserialize_message  # noqa: F401
        from rosidl_runtime_py.utilities import get_message

        get_message(str(topic_type))
    except Exception:
        return False, "pointcloud_runtime_unavailable"
    return True, None


def pointcloud_source_status(run: Path) -> dict[str, Any]:
    run = Path(run).resolve()
    index_path = run / "metrics" / "pointcloud_frame_index.json"
    if not index_path.is_file():
        return {
            "available": False,
            "reason": "pointcloud_frame_index_missing",
            "index_path": None,
            "sqlite_db": None,
        }

    payload = _load_json_object(index_path)
    if payload is None or not all(payload.get(key) for key in ("sqlite_db", "lidar_topic", "lidar_type")):
        return {
            "available": False,
            "reason": "pointcloud_frame_index_invalid",
            "index_path": str(index_path),
            "sqlite_db": None,
        }

    sqlite_db = Path(str(payload["sqlite_db"])).expanduser()
    if not sqlite_db.is_absolute():
        sqlite_db = (run / sqlite_db).resolve()
    else:
        sqlite_db = sqlite_db.resolve()
    if not sqlite_db.is_file():
        return {
            "available": False,
            "reason": "pointcloud_sqlite_missing",
            "index_path": str(index_path),
            "sqlite_db": str(sqlite_db),
        }
    runtime_available, runtime_reason = _pointcloud_runtime_status(str(payload["lidar_type"]))
    if not runtime_available:
        return {
            "available": False,
            "reason": runtime_reason or "pointcloud_runtime_unavailable",
            "index_path": str(index_path),
            "sqlite_db": str(sqlite_db),
        }
    return {
        "available": True,
        "reason": None,
        "index_path": str(index_path),
        "sqlite_db": str(sqlite_db),
    }


def _viewer_api() -> tuple[Callable[..., dict[str, Any]], Callable[[str], dict[str, int]], str]:
    from rerun_diagnostic_viewer import DEFAULT_POINT_LODS, log_recording, parse_point_lods

    return log_recording, parse_point_lods, DEFAULT_POINT_LODS


def finalize_saved_rerun_recording() -> str:
    try:
        import rerun as rr
    except ImportError as exc:
        raise RuntimeError(
            "Rerun SDK is not installed. Install the tested viewer dependency with: "
            "python3 -m pip install 'rerun-sdk==0.36.3'"
        ) from exc
    rr.flush()
    rr.disconnect()
    return str(getattr(rr, "__version__", "unknown"))


def _load_freeze_manifest(frozen: Path) -> dict[str, Any]:
    path = Path(frozen) / "freeze_manifest.json"
    payload = _load_json_object(path)
    if payload is None:
        raise ValueError(f"invalid or missing freeze manifest: {path}")
    return payload


def _record_rerun_failure(frozen: Path, exc: Exception) -> None:
    try:
        manifest = _load_freeze_manifest(frozen)
    except Exception:
        return
    manifest["failure"] = {
        "stage": "viewer/diagnostic.rrd",
        "type": type(exc).__name__,
        "message": str(exc),
    }
    write_json_atomic(Path(frozen) / "freeze_manifest.json", manifest)


def build_frozen_rerun(frozen: Path) -> dict[str, Any]:
    frozen = Path(frozen).resolve()
    manifest = _load_freeze_manifest(frozen)
    if manifest.get("freeze_state") == "COMPLETE":
        raise ValueError("frozen bundle is already COMPLETE")

    source_run = manifest.get("source_run") or {}
    run_path = source_run.get("path") if isinstance(source_run, dict) else None
    if not run_path:
        raise ValueError("freeze manifest is missing source_run.path")
    run = Path(str(run_path)).expanduser().resolve()
    if not run.is_dir():
        raise FileNotFoundError(f"source run is unavailable: {run}")

    algorithms = manifest.get("algorithms")
    if not isinstance(algorithms, list) or not algorithms:
        raise ValueError("freeze manifest must contain non-empty algorithms")
    algorithms = [str(item) for item in algorithms]
    baseline = str(manifest.get("baseline") or "")
    if not baseline:
        raise ValueError("freeze manifest is missing baseline")
    if baseline not in algorithms:
        raise ValueError(f"freeze baseline is not present in algorithms: {baseline}")
    language = str(manifest.get("language") or "")
    if not language:
        raise ValueError("freeze manifest is missing language")

    pointcloud = pointcloud_source_status(run)
    pointcloud_mode = "anomaly" if pointcloud["available"] else "none"
    log_recording, parse_point_lods, default_point_lods = _viewer_api()
    output = (frozen / "viewer" / "diagnostic.rrd").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        summary = log_recording(
            run=run,
            algorithms=algorithms,
            baseline=baseline,
            with_maps=True,
            map_point_step=4,
            pointcloud_mode=pointcloud_mode,
            pointcloud_period_s=1.0,
            point_step=20,
            point_lods=parse_point_lods(default_point_lods),
            world_pointcloud_mode=pointcloud_mode,
            world_algorithm=baseline,
            language=language,
            save=output,
            spawn=False,
        )
        sdk_version = finalize_saved_rerun_recording()
        if not output.is_file():
            raise RuntimeError(f"Native Rerun recording builder did not create: {output}")

        artifact = register_generated_artifact(
            frozen,
            "viewer/diagnostic.rrd",
            "native_rerun_recording",
        )
    except Exception as exc:
        _record_rerun_failure(frozen, exc)
        raise

    manifest = _load_freeze_manifest(frozen)
    manifest["failure"] = None
    manifest["rerun_recording"] = {
        "sdk_version": sdk_version,
        "path": "viewer/diagnostic.rrd",
        "bounded_policy": "anomaly-near",
        "map_evidence": {
            "optional": True,
            "requested": True,
        },
        "pointcloud_evidence": {
            "enabled": bool(pointcloud["available"]),
            "mode": pointcloud_mode,
            "omission_reason": pointcloud["reason"],
            "index_path": pointcloud["index_path"],
            "sqlite_db": pointcloud["sqlite_db"],
        },
        "builder_summary": summary,
    }
    write_json_atomic(frozen / "freeze_manifest.json", manifest)
    return {
        "artifact": artifact,
        "recording": manifest["rerun_recording"],
    }
