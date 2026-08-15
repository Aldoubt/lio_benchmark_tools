#!/usr/bin/env python3
"""Interactive Open3D comparison of standardized LIO benchmark maps."""
from __future__ import annotations

import argparse
import colorsys
import csv
import hashlib
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.artifacts import map_artifact_paths  # noqa: E402
from benchmark_base.lib.display_alignment import (  # noqa: E402
    normalize_display_alignment_mode,
    write_display_alignment_metadata,
)
from benchmark_base.lib.manifest import load_json  # noqa: E402
from visualization.alignment import StartYawAlignment, load_start_yaw_alignment  # noqa: E402
from visualization.pointcloud_io import PointCloudData, read_standard_ply  # noqa: E402
from visualization.presets import CameraPreset, RoiPreset, load_camera, load_roi, orthographic_like_camera, save_camera  # noqa: E402


@dataclass(frozen=True)
class LoadedMap:
    algorithm_id: str
    data: PointCloudData
    source_path: Path
    alignment: StartYawAlignment | None


def require_open3d() -> Any:
    try:
        import open3d as o3d
    except ImportError as exc:
        raise SystemExit(
            "Interactive Inspector requires the optional Open3D Python package. "
            "Install a version compatible with your Python/Ubuntu environment, then rerun this command."
        ) from exc
    return o3d


def algorithm_color(algorithm_id: str) -> tuple[float, float, float]:
    digest = hashlib.sha256(algorithm_id.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") / 65535.0
    saturation = 0.55 + digest[2] / 255.0 * 0.25
    value = 0.75 + digest[3] / 255.0 * 0.20
    return colorsys.hsv_to_rgb(hue, saturation, value)


def scalar_colors(values: np.ndarray, limits: tuple[float, float]) -> np.ndarray:
    if len(values) == 0:
        return np.empty((0, 3), dtype=np.float64)
    low, high = limits
    if not high > low:
        high = low + 1.0
    t = np.clip((values - low) / (high - low), 0.0, 1.0)
    red = np.clip(1.5 * t - 0.25, 0.0, 1.0)
    green = np.clip(1.8 - np.abs(2.0 * t - 1.0) * 1.8, 0.0, 1.0)
    blue = np.clip(1.25 - 1.5 * t, 0.0, 1.0)
    return np.column_stack((red, green, blue))


def shared_scalar_limits(values: list[np.ndarray]) -> tuple[float, float]:
    sampled: list[np.ndarray] = []
    for value in values:
        finite = value[np.isfinite(value)]
        if finite.size:
            sampled.append(finite[::max(1, len(finite) // 50_000)])
    if not sampled:
        return 0.0, 1.0
    joined = np.concatenate(sampled)
    low, high = np.percentile(joined, [2.0, 98.0])
    return float(low), float(high if high > low else low + 1.0)


def cloud_colors(data: PointCloudData, algorithm_id: str, mode: str, limits: tuple[float, float] | None) -> np.ndarray:
    if mode == "algorithm":
        return np.tile(np.asarray(algorithm_color(algorithm_id)), (len(data.xyz), 1))
    if mode == "height":
        assert limits is not None
        return scalar_colors(data.xyz[:, 2], limits)
    if mode == "intensity":
        if data.intensity is None:
            return np.tile(np.asarray(algorithm_color(algorithm_id)), (len(data.xyz), 1))
        assert limits is not None
        return scalar_colors(data.intensity, limits)
    raise ValueError(f"unsupported color mode: {mode}")


def selected_algorithms(manifest: dict[str, Any], requested: list[str] | None) -> list[str]:
    available = list(manifest.get("algorithms", {}))
    if requested is None:
        return available
    unknown = [item for item in requested if item not in available]
    if unknown:
        raise ValueError(f"algorithms are not part of run: {', '.join(unknown)}")
    return requested


def _native_map_path(run: Path, algorithm_id: str) -> Path:
    paths = map_artifact_paths(run, algorithm_id)
    candidates = sorted(paths.native_dir.glob("map.*"))
    if not candidates:
        # Historical V2 compatibility during migration.
        candidates = sorted(paths.root.glob("native_map.*"))
    if not candidates:
        raise FileNotFoundError(paths.native_dir / "map.*")
    return candidates[0]


def load_map_data(run: Path, algorithm_id: str, map_kind: str, o3d: Any, alignment_mode: str) -> LoadedMap:
    paths = map_artifact_paths(run, algorithm_id)
    if map_kind == "unified":
        path = paths.unified_map if paths.unified_map.is_file() else paths.compat_unified_map
        if not path.is_file():
            raise FileNotFoundError(path)
        data = read_standard_ply(path)
    else:
        path = _native_map_path(run, algorithm_id)
        cloud = o3d.io.read_point_cloud(str(path))
        if cloud.is_empty():
            raise ValueError(f"Open3D could not read native point cloud: {path}")
        data = PointCloudData(np.asarray(cloud.points, dtype=np.float64), None)

    alignment = None
    trajectory = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
    if trajectory.is_file():
        write_display_alignment_metadata(
            run=run,
            algorithm_id=algorithm_id,
            trajectory_role="ODOMETRY",
            trajectory_path=trajectory,
            mode=alignment_mode,
        )
        if alignment_mode == "START_XY_YAW":
            alignment = load_start_yaw_alignment(trajectory)
            data = PointCloudData(alignment.apply_xyz(data.xyz), data.intensity)
    return LoadedMap(algorithm_id, data, path, alignment)


def trajectory_lineset(path: Path, o3d: Any, color: tuple[float, float, float], alignment: StartYawAlignment | None) -> Any | None:
    if not path.is_file():
        return None
    points: list[list[float]] = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            points.append([float(row["x_m"]), float(row["y_m"]), float(row["z_m"])])
    if len(points) < 2:
        return None
    xyz = np.asarray(points, dtype=np.float64)
    if alignment is not None:
        xyz = alignment.apply_xyz(xyz)
    line = o3d.geometry.LineSet()
    line.points = o3d.utility.Vector3dVector(xyz)
    pairs = np.column_stack((np.arange(len(xyz) - 1), np.arange(1, len(xyz)))).astype(np.int32)
    line.lines = o3d.utility.Vector2iVector(pairs)
    line.colors = o3d.utility.Vector3dVector(np.tile(np.asarray(color), (len(pairs), 1)))
    return line


def apply_camera(vis: Any, preset: CameraPreset) -> None:
    if preset.view_matrix is not None:
        width = int(preset.viewport_width_px or 1024)
        height = int(preset.viewport_height_px or 768)
        fov = math.radians(preset.field_of_view_deg)
        fx = width / (2.0 * math.tan(fov * 0.5))
        intrinsic = np.array([[fx, 0.0, width * 0.5], [0.0, fx, height * 0.5], [0.0, 0.0, 1.0]], dtype=np.float64)
        vis.setup_camera(intrinsic, np.asarray(preset.view_matrix, dtype=np.float64), width, height)
    else:
        vis.setup_camera(float(preset.field_of_view_deg), np.asarray(preset.lookat, dtype=np.float32), np.asarray(preset.eye, dtype=np.float32), np.asarray(preset.up, dtype=np.float32))


def capture_camera(vis: Any, path: Path, name: str) -> None:
    camera = vis.scene.camera
    rect = vis.content_rect
    preset = CameraPreset(
        name=name,
        field_of_view_deg=float(camera.get_field_of_view()),
        view_matrix=tuple(tuple(float(value) for value in row) for row in np.asarray(camera.get_view_matrix())),
        viewport_width_px=max(1, int(rect.width)),
        viewport_height_px=max(1, int(rect.height)),
    )
    save_camera(path, preset)
    print(f"saved camera preset: {path}")


def inspect(run: Path, *, algorithms: list[str] | None, map_kind: str, color_mode: str, roi_path: Path | None, camera_path: Path | None, point_size: int, display_alignment: str) -> None:
    o3d = require_open3d()
    manifest = load_json(run / "manifest.json")
    algorithm_ids = selected_algorithms(manifest, algorithms)
    roi: RoiPreset | None = load_roi(roi_path) if roi_path else None
    alignment_mode = normalize_display_alignment_mode(display_alignment)
    loaded: list[LoadedMap] = []
    for algorithm_id in algorithm_ids:
        try:
            entry = load_map_data(run, algorithm_id, map_kind, o3d, alignment_mode)
        except (FileNotFoundError, ValueError) as exc:
            print(f"skip {algorithm_id}: {exc}", file=sys.stderr)
            continue
        data = entry.data.cropped(roi.min_xyz, roi.max_xyz) if roi is not None else entry.data
        if len(data.xyz):
            loaded.append(LoadedMap(entry.algorithm_id, data, entry.source_path, entry.alignment))
    if not loaded:
        raise SystemExit("Inspector has no readable map artifacts for the selected algorithms")

    color_limits: tuple[float, float] | None = None
    if color_mode == "height":
        color_limits = shared_scalar_limits([entry.data.xyz[:, 2] for entry in loaded])
    elif color_mode == "intensity":
        color_limits = shared_scalar_limits([entry.data.intensity for entry in loaded if entry.data.intensity is not None])

    objects: list[dict[str, Any]] = []
    bounds_low: list[np.ndarray] = []
    bounds_high: list[np.ndarray] = []
    for entry in loaded:
        cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(entry.data.xyz))
        cloud.colors = o3d.utility.Vector3dVector(cloud_colors(entry.data, entry.algorithm_id, color_mode, color_limits))
        objects.append({"name": f"map:{entry.algorithm_id}", "geometry": cloud, "group": "Maps", "is_visible": True})
        trajectory = trajectory_lineset(run / "standardized" / "trajectories" / f"{entry.algorithm_id}.csv", o3d, algorithm_color(entry.algorithm_id), entry.alignment)
        if trajectory is not None:
            objects.append({"name": f"trajectory:{entry.algorithm_id}", "geometry": trajectory, "group": "Trajectories", "is_visible": True})
        low, high = entry.data.bounds()
        bounds_low.append(low)
        bounds_high.append(high)
    low = np.min(np.vstack(bounds_low), axis=0)
    high = np.max(np.vstack(bounds_high), axis=0)
    cameras = {view: orthographic_like_camera(view.upper(), low, high, view) for view in ("xy", "xz", "yz", "perspective")}
    initial = load_camera(camera_path) if camera_path else cameras["perspective"]
    preset_dir = run / "metadata" / "camera_presets"
    screenshot_dir = run / "figures" / "inspector"

    def view_action(view: str):
        return lambda vis: apply_camera(vis, cameras[view])

    def save_camera_action(vis: Any) -> None:
        preset_dir.mkdir(parents=True, exist_ok=True)
        capture_camera(vis, preset_dir / "interactive_camera.json", "interactive_camera")

    def screenshot_action(vis: Any) -> None:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        stamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        path = screenshot_dir / f"inspector_{stamp}.png"
        vis.export_current_image(str(path))
        print(f"exported inspector image: {path}")

    actions = [
        ("View XY", view_action("xy")),
        ("View XZ", view_action("xz")),
        ("View YZ", view_action("yz")),
        ("View Perspective", view_action("perspective")),
        ("Save Camera Preset", save_camera_action),
        ("Export Screenshot", screenshot_action),
    ]
    print(f"Display alignment: {alignment_mode}; standardized artifacts are unchanged")
    for entry in loaded:
        print(f"- {entry.algorithm_id}: {entry.source_path}")
    o3d.visualization.draw(
        geometry=objects,
        title=f"LIO Benchmark Inspector — {manifest.get('run_id', run.name)} — {alignment_mode}",
        width=1400,
        height=900,
        actions=actions,
        lookat=np.asarray(initial.lookat, dtype=np.float32) if initial.lookat else None,
        eye=np.asarray(initial.eye, dtype=np.float32) if initial.eye else None,
        up=np.asarray(initial.up, dtype=np.float32) if initial.up else None,
        field_of_view=float(initial.field_of_view_deg),
        show_ui=True,
        point_size=max(1, int(point_size)),
        on_init=(lambda vis: apply_camera(vis, initial)) if initial.view_matrix is not None else None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithms", nargs="+")
    parser.add_argument("--map-kind", choices=("unified", "native"), default="unified")
    parser.add_argument("--color-mode", choices=("height", "intensity", "algorithm"), default="height")
    parser.add_argument("--roi", type=Path)
    parser.add_argument("--camera", type=Path)
    parser.add_argument("--point-size", type=int, default=2)
    parser.add_argument(
        "--display-alignment",
        choices=("START_XY_YAW", "NONE", "start_yaw", "raw"),
        default="START_XY_YAW",
        help="Display-only transform. start_yaw/raw are deprecated aliases.",
    )
    args = parser.parse_args()
    inspect(
        args.run.resolve(),
        algorithms=args.algorithms,
        map_kind=args.map_kind,
        color_mode=args.color_mode,
        roi_path=args.roi,
        camera_path=args.camera,
        point_size=args.point_size,
        display_alignment=args.display_alignment,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
