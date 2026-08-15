#!/usr/bin/env python3
"""Render a deterministic same-bag point-cloud animation for the repository README."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
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
from reporting.contracts import ffmpeg_gif_command  # noqa: E402
from visualization.alignment import load_start_yaw_alignment  # noqa: E402
from visualization.pointcloud_io import PointCloudData, read_standard_ply  # noqa: E402
from visualization.presets import CameraPreset, RoiPreset, load_camera, load_roi, orthographic_like_camera  # noqa: E402


def require_matplotlib() -> Any:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("README demo rendering requires matplotlib.") from exc
    return plt


def _unified_map_path(run: Path, algorithm_id: str) -> Path:
    paths = map_artifact_paths(run, algorithm_id)
    return paths.unified_map if paths.unified_map.is_file() else paths.compat_unified_map


def load_clouds(run: Path, algorithms: list[str], roi: RoiPreset | None, display_alignment: str) -> dict[str, PointCloudData]:
    canonical = normalize_display_alignment_mode(display_alignment)
    clouds: dict[str, PointCloudData] = {}
    for algorithm_id in algorithms:
        path = _unified_map_path(run, algorithm_id)
        if not path.is_file():
            print(f"demo skip {algorithm_id}: missing {path}", file=sys.stderr)
            continue
        cloud = read_standard_ply(path)
        trajectory = run / "standardized/trajectories" / f"{algorithm_id}.csv"
        if trajectory.is_file():
            write_display_alignment_metadata(
                run=run,
                algorithm_id=algorithm_id,
                trajectory_role="ODOMETRY",
                trajectory_path=trajectory,
                mode=canonical,
            )
            if canonical == "START_XY_YAW":
                alignment = load_start_yaw_alignment(trajectory)
                cloud = PointCloudData(alignment.apply_xyz(cloud.xyz), cloud.intensity)
        if roi is not None:
            cloud = cloud.cropped(roi.min_xyz, roi.max_xyz)
        if len(cloud.xyz):
            clouds[algorithm_id] = cloud
    return clouds


def common_bounds(clouds: dict[str, PointCloudData]) -> tuple[np.ndarray, np.ndarray]:
    low = np.min(np.vstack([cloud.bounds()[0] for cloud in clouds.values()]), axis=0)
    high = np.max(np.vstack([cloud.bounds()[1] for cloud in clouds.values()]), axis=0)
    span = np.maximum(high - low, 0.1)
    return low - span * 0.04, high + span * 0.04


def shared_height_limits(clouds: dict[str, PointCloudData]) -> tuple[float, float]:
    values = np.concatenate([
        cloud.xyz[::max(1, len(cloud.xyz) // 50_000), 2] for cloud in clouds.values()
    ])
    low, high = np.percentile(values, [2.0, 98.0])
    return float(low), float(high if high > low else low + 1.0)


def camera_angles(preset: CameraPreset) -> tuple[float, float]:
    if preset.lookat is None or preset.eye is None:
        raise ValueError(
            "README demo requires a vector-form camera preset; captured view-matrix presets are for Open3D Inspector reuse"
        )
    delta = np.asarray(preset.eye) - np.asarray(preset.lookat)
    radius = float(np.linalg.norm(delta))
    if radius <= 1e-9:
        return 25.0, -60.0
    return math.degrees(math.asin(delta[2] / radius)), math.degrees(math.atan2(delta[1], delta[0]))


def render_frames(
    manifest: dict[str, Any],
    clouds: dict[str, PointCloudData],
    output_dir: Path,
    camera: CameraPreset,
    frames_per_algorithm: int,
    alignment_mode: str,
) -> int:
    plt = require_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    low, high = common_bounds(clouds)
    zlow, zhigh = shared_height_limits(clouds)
    elev0, azim0 = camera_angles(camera)
    frame_index = 0
    dataset_id = manifest.get("dataset", {}).get("dataset_id", "legacy_v1_dataset")
    for algorithm_id, cloud in clouds.items():
        step = max(1, len(cloud.xyz) // 120_000)
        shown = cloud.xyz[::step]
        for local_index in range(frames_per_algorithm):
            phase = local_index / max(1, frames_per_algorithm - 1)
            azim = azim0 - 25.0 + 50.0 * phase
            fig = plt.figure(figsize=(9.6, 5.4), constrained_layout=True)
            axis = fig.add_subplot(111, projection="3d")
            axis.scatter(
                shown[:, 0],
                shown[:, 1],
                shown[:, 2],
                c=shown[:, 2],
                s=0.15,
                cmap="viridis",
                vmin=zlow,
                vmax=zhigh,
                rasterized=True,
            )
            axis.set_xlim(low[0], high[0])
            axis.set_ylim(low[1], high[1])
            axis.set_zlim(low[2], high[2])
            axis.set_box_aspect((
                max(high[0] - low[0], 0.1),
                max(high[1] - low[1], 0.1),
                max(high[2] - low[2], 0.1),
            ))
            axis.view_init(elev=elev0, azim=azim)
            axis.set_axis_off()
            config = manifest.get("algorithms", {}).get(algorithm_id, {})
            label = config.get("display_name", algorithm_id) if isinstance(config, dict) else algorithm_id
            fig.text(0.03, 0.94, str(label), fontsize=18, weight="bold")
            fig.text(0.03, 0.89, f"Same bag · {dataset_id} · identical ROI/camera/color scale", fontsize=10)
            fig.text(0.03, 0.05, f"Unified reconstruction · timestamp matched · Display alignment: {alignment_mode}", fontsize=9)
            fig.savefig(output_dir / f"frame_{frame_index:05d}.png", dpi=120)
            plt.close(fig)
            frame_index += 1
    return frame_index


def generate(
    run: Path,
    algorithms: list[str] | None,
    roi_path: Path | None,
    camera_path: Path | None,
    output: Path,
    frames_per_algorithm: int,
    fps: int,
    display_alignment: str,
) -> None:
    if frames_per_algorithm < 2:
        raise ValueError("frames_per_algorithm must be >= 2")
    canonical = normalize_display_alignment_mode(display_alignment)
    manifest = load_json(run / "manifest.json")
    selected = algorithms or list(manifest.get("algorithms", {}))
    roi = load_roi(roi_path) if roi_path else None
    clouds = load_clouds(run, selected, roi, canonical)
    if not clouds:
        raise SystemExit("No standardized unified maps are available for the README demo")
    low, high = common_bounds(clouds)
    camera = load_camera(camera_path) if camera_path else orthographic_like_camera("demo", low, high, "perspective", 45.0)
    frame_dir = run / "figures/demo_frames"
    count = render_frames(manifest, clouds, frame_dir, camera, frames_per_algorithm, canonical)
    metadata = {
        "schema": "lio_benchmark_demo/v3",
        "run_id": manifest.get("run_id", run.name),
        "dataset_id": manifest.get("dataset", {}).get("dataset_id", "legacy_v1_dataset"),
        "algorithms": list(clouds),
        "map_kind": "UNIFIED_RECONSTRUCTION",
        "roi": str(roi_path) if roi_path else None,
        "camera": str(camera_path) if camera_path else "AUTO_SHARED_PERSPECTIVE",
        "display_alignment": canonical,
        "shared_height_color_scale": True,
        "frames_per_algorithm": frames_per_algorithm,
        "frame_count": count,
        "fps": fps,
        "output": str(output),
        "same_camera_path_for_all_algorithms": True,
        "scientific_artifacts_modified": False,
    }
    (frame_dir / "demo_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    ffmpeg = shutil.which("ffmpeg")
    command = ffmpeg_gif_command(frame_dir / "frame_%05d.png", output, fps=fps)
    if ffmpeg is None:
        print("ffmpeg is not installed; frames were rendered successfully.", file=sys.stderr)
        print("After installing ffmpeg, run:\n" + " ".join(command), file=sys.stderr)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    command[0] = ffmpeg
    subprocess.run(command, check=True)
    print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithms", nargs="+")
    parser.add_argument("--roi", type=Path)
    parser.add_argument("--camera", type=Path)
    parser.add_argument("--output", type=Path, default=MODULE_ROOT / "assets/demo/same_bag_map_comparison.gif")
    parser.add_argument("--frames-per-algorithm", type=int, default=24)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument(
        "--display-alignment",
        choices=("START_XY_YAW", "NONE", "start_yaw", "raw"),
        default="START_XY_YAW",
        help="Display-only transform. start_yaw/raw are deprecated aliases.",
    )
    args = parser.parse_args()
    generate(
        args.run.resolve(),
        args.algorithms,
        args.roi,
        args.camera,
        args.output,
        args.frames_per_algorithm,
        args.fps,
        args.display_alignment,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
