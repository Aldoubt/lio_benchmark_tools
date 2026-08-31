from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from freeze_experiment import (
    register_generated_artifact,
    sha256_path,
    write_json_atomic,
)
from pointcloud_frame_index import build_pointcloud_frame_index
from viewer_i18n import native_viewer_language


def build_compat_maps(
    source: Path, *, algorithms: list[str], baseline: str
) -> dict[str, Any]:
    """Lazy bridge so importing freeze_rerun does not require ROS modules."""
    from freeze_map_compat import build_compat_maps as implementation

    return implementation(source, algorithms=algorithms, baseline=baseline)


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


def pointcloud_source_status(
    run: Path,
    *,
    index_root: Path | None = None,
) -> dict[str, Any]:
    run = Path(run).resolve()
    root = Path(index_root).resolve() if index_root is not None else run
    index_path = root / "metrics" / "pointcloud_frame_index.json"
    if not index_path.is_file():
        return {
            "available": False,
            "reason": "pointcloud_frame_index_missing",
            "index_path": None,
            "sqlite_db": None,
        }

    payload = _load_json_object(index_path)
    if payload is None or not all(
        payload.get(key) for key in ("sqlite_db", "lidar_topic", "lidar_type")
    ):
        return {
            "available": False,
            "reason": "pointcloud_frame_index_invalid",
            "index_path": str(index_path),
            "sqlite_db": None,
        }

    sqlite_db = Path(str(payload["sqlite_db"])).expanduser()
    if not sqlite_db.is_absolute():
        sqlite_db = (root / sqlite_db).resolve()
    else:
        sqlite_db = sqlite_db.resolve()
    if not sqlite_db.is_file():
        return {
            "available": False,
            "reason": "pointcloud_sqlite_missing",
            "index_path": str(index_path),
            "sqlite_db": str(sqlite_db),
        }
    runtime_available, runtime_reason = _pointcloud_runtime_status(
        str(payload["lidar_type"])
    )
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


def _load_freeze_manifest(frozen: Path) -> dict[str, Any]:
    path = Path(frozen) / "freeze_manifest.json"
    payload = _load_json_object(path)
    if payload is None:
        raise ValueError(f"invalid or missing freeze manifest: {path}")
    return payload


def register_compatibility_artifact(
    frozen: Path,
    relative_path: str,
    role: str,
    derivation: str,
) -> dict[str, Any]:
    frozen = Path(frozen).resolve()
    relative = Path(str(relative_path))
    if relative.is_absolute() or ".." in relative.parts or str(relative) in {"", "."}:
        raise ValueError(f"invalid compatibility artifact path: {relative_path}")
    target = (frozen / relative).resolve()
    try:
        target.relative_to(frozen)
    except ValueError as exc:
        raise ValueError(
            f"compatibility artifact escapes frozen bundle: {relative_path}"
        ) from exc
    digest, size = sha256_path(target)
    manifest = _load_freeze_manifest(frozen)
    record = {
        "bundle_path": relative.as_posix(),
        "role": str(role),
        "derivation": str(derivation),
        "size_bytes": size,
        "sha256": digest,
    }
    existing = manifest.get("compatibility_artifacts")
    if not isinstance(existing, list):
        existing = []
    manifest["compatibility_artifacts"] = [
        item
        for item in existing
        if not isinstance(item, dict) or item.get("bundle_path") != record["bundle_path"]
    ] + [record]
    write_json_atomic(frozen / "freeze_manifest.json", manifest)
    return record


def ensure_pointcloud_source(run: Path, frozen: Path) -> dict[str, Any]:
    """Use or derive a compact frame index without mutating the historical run."""
    run = Path(run).resolve()
    frozen = Path(frozen).resolve()
    frozen_source = (frozen / "source").resolve()
    index_root = frozen_source if frozen_source.is_dir() else run

    status = pointcloud_source_status(run, index_root=index_root)
    if status["available"]:
        return {
            **status,
            "index_source": (
                "frozen/source" if index_root == frozen_source else "source_run"
            ),
            "derived": False,
            "derivation_error": None,
        }

    if (
        status["reason"] != "pointcloud_frame_index_missing"
        or index_root != frozen_source
        or not (frozen_source / "manifest.json").is_file()
    ):
        return {
            **status,
            "index_source": (
                "frozen/source" if index_root == frozen_source else "source_run"
            ),
            "derived": False,
            "derivation_error": None,
        }

    try:
        result = build_pointcloud_frame_index(frozen_source)
        for relative in result.get("artifacts") or []:
            register_compatibility_artifact(
                frozen,
                (Path("source") / str(relative)).as_posix(),
                "compatibility_derived_pointcloud_index",
                "source-bag-read-only-index-v1",
            )
        rebuilt = pointcloud_source_status(run, index_root=frozen_source)
        return {
            **rebuilt,
            "index_source": "frozen/source",
            "derived": bool(rebuilt["available"]),
            "derivation_error": None,
            "derivation": {
                "method": "source-bag-read-only-index-v1",
                "frames": result.get("frames"),
                "origin_timestamp_s": result.get("origin_timestamp_s"),
                "origin_source": result.get("origin_source"),
            },
        }
    except Exception as exc:
        # Pointcloud evidence remains optional. Preserve the completed freeze
        # path while making the exact omission reason auditable.
        return {
            **status,
            "index_source": "frozen/source",
            "derived": False,
            "derivation_error": f"{type(exc).__name__}: {exc}",
        }


def ensure_static_maps(
    frozen: Path,
    viewer_run: Path,
    *,
    algorithms: list[str],
    baseline: str,
) -> dict[str, Any]:
    """Populate missing map PLYs in the frozen compatibility source only."""
    frozen = Path(frozen).resolve()
    viewer_run = Path(viewer_run).resolve()
    map_dir = viewer_run / "figures" / "fast_livo2_baseline_maps"

    def available() -> list[str]:
        return [
            algorithm
            for algorithm in algorithms
            if (map_dir / f"{algorithm}_map.ply").is_file()
        ]

    before = available()
    if len(before) == len(algorithms):
        return {
            "available_algorithms": before,
            "derived": False,
            "derivation_error": None,
        }

    if viewer_run.name != "source" or not (viewer_run / "manifest.json").is_file():
        return {
            "available_algorithms": before,
            "derived": False,
            "derivation_error": "frozen_source_manifest_unavailable",
        }

    try:
        result = build_compat_maps(
            viewer_run,
            algorithms=algorithms,
            baseline=baseline,
        )
        for relative in result.get("artifacts") or []:
            register_compatibility_artifact(
                frozen,
                (Path("source") / str(relative)).as_posix(),
                "compatibility_derived_reconstructed_map",
                "baseline-aligned-read-only-bag-map-v1",
            )
        after = available()
        return {
            "available_algorithms": after,
            "derived": bool(result.get("artifacts")),
            "derivation_error": None,
            "derivation": result,
        }
    except Exception as exc:
        return {
            "available_algorithms": available(),
            "derived": False,
            "derivation_error": f"{type(exc).__name__}: {exc}",
        }


def _viewer_api() -> tuple[
    Callable[..., dict[str, Any]], Callable[[str], dict[str, int]], str
]:
    import rerun_diagnostic_viewer as viewer

    def log_recording_with_diagnostic_source(
        *, diagnostic_run: Path | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        if diagnostic_run is None:
            return viewer.log_recording(**kwargs)

        original_run = Path(kwargs["run"]).resolve()
        diagnostic_root = Path(diagnostic_run).resolve()
        if diagnostic_root == original_run:
            return viewer.log_recording(**kwargs)

        original_load_json = viewer.load_json
        original_load_csv = viewer.load_csv
        original_projection_context = viewer._projection_context
        original_timeline_positions = viewer._timeline_positions

        def relative_to_original(path: Path) -> Path | None:
            try:
                return Path(path).resolve().relative_to(original_run)
            except ValueError:
                return None

        def redirected_load_json(path: Path, default: Any = None) -> Any:
            relative = relative_to_original(Path(path))
            if relative in {
                Path("metrics/diagnostic_timeline.json"),
                Path("metrics/pointcloud_frame_index.json"),
            }:
                redirected = diagnostic_root / relative
                if redirected.is_file():
                    return original_load_json(redirected, default)
            return original_load_json(path, default)

        def redirected_load_csv(path: Path) -> list[dict[str, str]]:
            relative = relative_to_original(Path(path))
            if (
                relative is not None
                and len(relative.parts) >= 2
                and relative.parts[:2] == ("metrics", "diagnostic_timeline")
            ):
                return original_load_csv(diagnostic_root / relative)
            return original_load_csv(path)

        def redirected_projection_context(
            _run: Path, algorithms: list[str], baseline: str
        ) -> Any:
            return original_projection_context(diagnostic_root, algorithms, baseline)

        def redirected_timeline_positions(
            _run: Path, algorithm: str
        ) -> tuple[Any, Any]:
            return original_timeline_positions(diagnostic_root, algorithm)

        viewer.load_json = redirected_load_json
        viewer.load_csv = redirected_load_csv
        viewer._projection_context = redirected_projection_context
        viewer._timeline_positions = redirected_timeline_positions
        try:
            return viewer.log_recording(**kwargs)
        finally:
            viewer.load_json = original_load_json
            viewer.load_csv = original_load_csv
            viewer._projection_context = original_projection_context
            viewer._timeline_positions = original_timeline_positions

    return (
        log_recording_with_diagnostic_source,
        viewer.parse_point_lods,
        viewer.DEFAULT_POINT_LODS,
    )


def finalize_saved_rerun_recording() -> str:
    try:
        import rerun as rr
    except ImportError as exc:
        raise RuntimeError(
            "Rerun SDK is not installed. Install the tested viewer dependency with: "
            "python3 -m pip install 'rerun-sdk==0.36.3'"
        ) from exc

    # rerun-sdk 0.36.3 does not expose a module-level rr.flush(). The file sink
    # created by rr.save() is finalized by rr.disconnect(), which closes open
    # files before we hash/register the .rrd artifact.
    rr.disconnect()
    return str(getattr(rr, "__version__", "unknown"))


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
    frozen_source = (frozen / "source").resolve()
    viewer_run = (
        frozen_source
        if frozen_source.is_dir() and (frozen_source / "manifest.json").is_file()
        else run
    )
    diagnostic_run = frozen_source if frozen_source.is_dir() else run

    algorithms = manifest.get("algorithms")
    if not isinstance(algorithms, list) or not algorithms:
        raise ValueError("freeze manifest must contain non-empty algorithms")
    algorithms = [str(item) for item in algorithms]
    baseline = str(manifest.get("baseline") or "")
    if not baseline:
        raise ValueError("freeze manifest is missing baseline")
    if baseline not in algorithms:
        raise ValueError(f"freeze baseline is not present in algorithms: {baseline}")
    report_language = str(manifest.get("language") or "")
    if not report_language:
        raise ValueError("freeze manifest is missing language")
    display_language = native_viewer_language(report_language)

    pointcloud = ensure_pointcloud_source(run, frozen)
    pointcloud_mode = "anomaly" if pointcloud["available"] else "none"
    maps = ensure_static_maps(
        frozen,
        viewer_run,
        algorithms=algorithms,
        baseline=baseline,
    )
    log_recording, parse_point_lods, default_point_lods = _viewer_api()
    output = (frozen / "viewer" / "diagnostic.rrd").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        summary = log_recording(
            run=viewer_run,
            diagnostic_run=diagnostic_run,
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
            language=display_language,
            save=output,
            spawn=False,
        )
        sdk_version = finalize_saved_rerun_recording()
        if not output.is_file():
            raise RuntimeError(
                f"Native Rerun recording builder did not create: {output}"
            )

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
        "diagnostic_source": (
            "frozen/source" if diagnostic_run == frozen_source else "source_run"
        ),
        "report_language": report_language,
        "native_viewer_language": display_language,
        "native_language_policy": "ascii-safe-labels-for-rerun-0.36",
        "bounded_policy": "anomaly-near",
        "map_evidence": {
            "optional": True,
            "requested": True,
            "source": (
                "frozen/source" if viewer_run == frozen_source else "source_run"
            ),
            "available_algorithms": maps.get("available_algorithms") or [],
            "derived": bool(maps.get("derived")),
            "derivation_error": maps.get("derivation_error"),
            "derivation": maps.get("derivation"),
        },
        "pointcloud_evidence": {
            "enabled": bool(pointcloud["available"]),
            "mode": pointcloud_mode,
            "omission_reason": pointcloud["reason"],
            "index_path": pointcloud["index_path"],
            "sqlite_db": pointcloud["sqlite_db"],
            "index_source": pointcloud.get("index_source"),
            "index_derived": bool(pointcloud.get("derived")),
            "index_derivation_error": pointcloud.get("derivation_error"),
            "index_derivation": pointcloud.get("derivation"),
            "payload_source": "original_rosbag2_sqlite_read_only",
        },
        "builder_summary": summary,
    }
    write_json_atomic(frozen / "freeze_manifest.json", manifest)
    return {
        "artifact": artifact,
        "recording": manifest["rerun_recording"],
    }
