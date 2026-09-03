from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

import freeze_rerun as legacy
from viewer_i18n import tr


DEFAULT_WARNING_EXTENT_RATIO = 5.0
DEFAULT_SUSPECT_EXTENT_RATIO = 10.0


def classify_extent_xyz(
    extent_xyz_m: list[float] | tuple[float, float, float] | np.ndarray,
    baseline_extent_xyz_m: list[float] | tuple[float, float, float] | np.ndarray,
    *,
    warning_ratio: float = DEFAULT_WARNING_EXTENT_RATIO,
    suspect_ratio: float = DEFAULT_SUSPECT_EXTENT_RATIO,
) -> dict[str, Any]:
    """Classify one reconstructed map extent relative to the baseline map.

    This is a display QA policy only. It never deletes or rewrites the map.
    """
    extent = np.asarray(extent_xyz_m, dtype=np.float64).reshape(-1)
    baseline = np.asarray(baseline_extent_xyz_m, dtype=np.float64).reshape(-1)
    if extent.shape != (3,) or baseline.shape != (3,):
        raise ValueError("map extents must contain exactly x/y/z values")
    if not np.isfinite(extent).all() or not np.isfinite(baseline).all():
        raise ValueError("map extents must be finite")
    if np.any(extent < 0) or np.any(baseline <= 0):
        raise ValueError("candidate extents must be nonnegative and baseline extents positive")
    if warning_ratio <= 1 or suspect_ratio <= warning_ratio:
        raise ValueError("extent QA thresholds must satisfy 1 < warning < suspect")

    ratios = extent / baseline
    maximum = float(np.max(ratios))
    if maximum >= float(suspect_ratio):
        status = "suspect_extent"
    elif maximum >= float(warning_ratio):
        status = "warning_extent"
    else:
        status = "ok"
    return {
        "status": status,
        "extent_xyz_m": extent.tolist(),
        "baseline_extent_xyz_m": baseline.tolist(),
        "ratio_xyz": ratios.tolist(),
        "max_ratio": maximum,
        "warning_ratio": float(warning_ratio),
        "suspect_ratio": float(suspect_ratio),
    }


def default_spatial_visibility(
    algorithms: list[str],
    *,
    baseline: str,
    visible_algorithms: set[str] | None,
    map_qa: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return a baseline-first default visibility policy for Native Rerun.

    Non-baseline maps stay recorded but are hidden by default. If an algorithm's
    reconstructed map is suspect by extent, its entire /world spatial group is
    hidden by default so the automatic camera bounds cannot be blown up by a
    kilometer-scale failure. Users can still re-enable the entity manually.
    """
    visible = set(algorithms if visible_algorithms is None else visible_algorithms)
    result: dict[str, dict[str, Any]] = {}
    for algorithm in algorithms:
        if algorithm not in visible:
            result[algorithm] = {
                "algorithm_visible": False,
                "map_visible": False,
                "reason": "filtered",
            }
            continue
        status = str((map_qa.get(algorithm) or {}).get("status") or "map_missing")
        if algorithm != baseline and status == "suspect_extent":
            result[algorithm] = {
                "algorithm_visible": False,
                "map_visible": False,
                "reason": "suspect_extent",
            }
            continue
        if algorithm == baseline:
            result[algorithm] = {
                "algorithm_visible": True,
                "map_visible": status != "map_missing",
                "reason": "baseline",
            }
            continue
        result[algorithm] = {
            "algorithm_visible": True,
            "map_visible": False,
            "reason": "nonbaseline_map_hidden",
        }
    return result


def collect_map_extent_qa(
    run: Path,
    *,
    algorithms: list[str],
    baseline: str,
) -> dict[str, dict[str, Any]]:
    """Inspect frozen PLY evidence and compute baseline-relative extent QA."""
    import rerun_diagnostic_viewer as viewer

    run = Path(run).resolve()
    map_dir = run / "figures" / "fast_livo2_baseline_maps"
    raw: dict[str, dict[str, Any]] = {}
    for algorithm in algorithms:
        path = map_dir / f"{algorithm}_map.ply"
        if not path.is_file():
            raw[algorithm] = {
                "status": "map_missing",
                "path": None,
                "map_points": 0,
                "extent_xyz_m": None,
            }
            continue
        cloud = viewer.load_binary_little_endian_ply(path)
        if len(cloud) == 0:
            raw[algorithm] = {
                "status": "map_empty",
                "path": path.relative_to(run).as_posix(),
                "map_points": 0,
                "extent_xyz_m": [0.0, 0.0, 0.0],
            }
            continue
        extent = np.ptp(cloud[:, :3], axis=0)
        raw[algorithm] = {
            "status": "pending",
            "path": path.relative_to(run).as_posix(),
            "map_points": int(len(cloud)),
            "extent_xyz_m": extent.tolist(),
        }

    baseline_item = raw.get(baseline) or {}
    baseline_extent = baseline_item.get("extent_xyz_m")
    if not isinstance(baseline_extent, list) or len(baseline_extent) != 3 or any(
        float(value) <= 0 for value in baseline_extent
    ):
        for algorithm, item in raw.items():
            if item.get("status") == "pending":
                item["status"] = "qa_unavailable_baseline_map"
            item["is_baseline"] = algorithm == baseline
        return raw

    for algorithm, item in raw.items():
        item["is_baseline"] = algorithm == baseline
        extent = item.get("extent_xyz_m")
        if item.get("status") != "pending" or not isinstance(extent, list):
            continue
        qa = classify_extent_xyz(extent, baseline_extent)
        item.update(qa)
    return raw


def _send_blueprint_with_policy(
    rr: Any,
    rrb: Any,
    *,
    algorithms: list[str],
    visible_algorithms: set[str] | None,
    world_algorithm: str,
    point_lod: str,
    language: str,
    baseline: str,
    map_qa: dict[str, dict[str, Any]],
) -> None:
    import rerun_diagnostic_viewer as viewer

    policy = default_spatial_visibility(
        algorithms,
        baseline=baseline,
        visible_algorithms=visible_algorithms,
        map_qa=map_qa,
    )
    sensor_overrides = {
        f"/sensor/raw_lidar/{lod}": rrb.EntityBehavior(visible=lod == point_lod)
        for lod in viewer.POINT_LOD_NAMES
    }
    world_overrides: dict[str, Any] = {}
    spatial_overrides: dict[str, Any] = {}
    for algorithm in algorithms:
        paths = viewer.algorithm_entity_paths(algorithm)
        item = policy[algorithm]
        spatial_overrides[f"/{paths['root']}"] = rrb.EntityBehavior(
            visible=bool(item["algorithm_visible"])
        )
        spatial_overrides[f"/{paths['map']}"] = rrb.EntityBehavior(
            visible=bool(item["map_visible"])
        )
        for lod, path in viewer.world_entity_paths(algorithm).items():
            world_overrides[f"/{path}"] = rrb.EntityBehavior(
                visible=algorithm == world_algorithm and lod == point_lod
            )

    sensor_view = rrb.Spatial3DView(
        name=tr(language, "view.raw_lidar"),
        origin="/sensor",
        overrides=sensor_overrides,
    )
    world_view = rrb.Spatial3DView(
        name=tr(language, "view.world_lidar"),
        origin="/world_lidar",
        overrides=world_overrides,
    )
    blueprint = rrb.Blueprint(
        rrb.Vertical(
            rrb.Horizontal(
                rrb.Spatial3DView(
                    name=tr(language, "view.map_trajectories"),
                    origin="/world",
                    overrides=spatial_overrides,
                ),
                rrb.Vertical(
                    rrb.TimeSeriesView(name=tr(language, "view.cpu"), origin="/metrics/cpu"),
                    rrb.TimeSeriesView(name=tr(language, "view.rss"), origin="/metrics/rss"),
                    rrb.TimeSeriesView(name=tr(language, "view.motion"), origin="/metrics/motion"),
                    row_shares=[1, 1, 1],
                ),
                column_shares=[2, 1],
            ),
            rrb.Horizontal(
                sensor_view,
                world_view,
                rrb.TextLogView(name=tr(language, "view.anomaly_windows"), origin="/events"),
                column_shares=[1, 1, 1],
            ),
            row_shares=[3, 2],
        ),
        collapse_panels=False,
    )
    rr.send_blueprint(blueprint)


def _load_freeze_context(frozen: Path) -> tuple[list[str], str]:
    payload = json.loads((Path(frozen) / "freeze_manifest.json").read_text(encoding="utf-8"))
    algorithms = [str(item) for item in payload.get("algorithms") or []]
    baseline = str(payload.get("baseline") or "")
    if not algorithms or not baseline:
        raise ValueError("freeze manifest is missing algorithms/baseline for spatial QA")
    return algorithms, baseline


def build_frozen_rerun(frozen: Path) -> dict[str, Any]:
    """Build the legacy recording with a bounded, auditable spatial default view."""
    import rerun_diagnostic_viewer as viewer

    frozen = Path(frozen).resolve()
    algorithms, baseline = _load_freeze_context(frozen)
    state: dict[str, Any] = {"map_qa": {}, "visibility": {}}

    original_ensure_static_maps = legacy.ensure_static_maps
    original_viewer_api = legacy._viewer_api
    original_send_blueprint = viewer.send_blueprint

    def ensure_static_maps_with_qa(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_ensure_static_maps(*args, **kwargs)
        viewer_run = Path(args[1] if len(args) >= 2 else kwargs["viewer_run"]).resolve()
        qa = collect_map_extent_qa(
            viewer_run,
            algorithms=algorithms,
            baseline=baseline,
        )
        visibility = default_spatial_visibility(
            algorithms,
            baseline=baseline,
            visible_algorithms=set(algorithms),
            map_qa=qa,
        )
        state["map_qa"] = qa
        state["visibility"] = visibility
        derivation = result.get("derivation")
        if not isinstance(derivation, dict):
            derivation = {}
        result["derivation"] = {
            **derivation,
            "extent_qa": qa,
            "default_spatial_visibility": visibility,
            "extent_qa_policy": {
                "warning_ratio": DEFAULT_WARNING_EXTENT_RATIO,
                "suspect_ratio": DEFAULT_SUSPECT_EXTENT_RATIO,
                "default_map_visibility": "baseline-only",
                "suspect_algorithm_default_visibility": "hidden",
            },
        }
        return result

    def viewer_api_with_qa():
        log_recording, parse_point_lods, default_point_lods = original_viewer_api()

        def log_recording_with_qa(**kwargs: Any) -> dict[str, Any]:
            summary = log_recording(**kwargs)
            summary["map_extent_qa"] = state["map_qa"]
            summary["default_spatial_visibility"] = state["visibility"]
            summary["spatial_qa_policy"] = {
                "warning_ratio": DEFAULT_WARNING_EXTENT_RATIO,
                "suspect_ratio": DEFAULT_SUSPECT_EXTENT_RATIO,
                "default_map_visibility": "baseline-only",
                "suspect_algorithm_default_visibility": "hidden",
            }
            return summary

        return log_recording_with_qa, parse_point_lods, default_point_lods

    def send_blueprint_with_qa(
        rr: Any,
        rrb: Any,
        *,
        algorithms: list[str],
        visible_algorithms: set[str] | None,
        world_algorithm: str,
        point_lod: str,
        language: str,
    ) -> None:
        _send_blueprint_with_policy(
            rr,
            rrb,
            algorithms=algorithms,
            visible_algorithms=visible_algorithms,
            world_algorithm=world_algorithm,
            point_lod=point_lod,
            language=language,
            baseline=baseline,
            map_qa=state["map_qa"],
        )

    legacy.ensure_static_maps = ensure_static_maps_with_qa
    legacy._viewer_api = viewer_api_with_qa
    viewer.send_blueprint = send_blueprint_with_qa
    try:
        return legacy.build_frozen_rerun(frozen)
    finally:
        legacy.ensure_static_maps = original_ensure_static_maps
        legacy._viewer_api = original_viewer_api
        viewer.send_blueprint = original_send_blueprint
