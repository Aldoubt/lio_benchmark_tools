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

from benchmark_base.lib.manifest import load_json  # noqa: E402
from reporting.contracts import ffmpeg_gif_command  # noqa: E402
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


def load_clouds(run: Path, algorithms: list[str], roi: RoiPreset | None) -> dict[str, PointCloudData]:
    clouds: dict[str, PointCloudData] = {}
    for algorithm_id in algorithms:
        path = run / "standardized" / "maps" / algorithm_id / "unified_map.ply"
        if not path.is_file():
            print(f"demo skip {algorithm_id}: missing {path}", file=sys.stderr)
            continue
        cloud = read_standard_ply(path)
        if roi is not None:
            cloud = cloud.cropped(roi.min_xyz, roi.max_xyz)
        if len(cloud.xyz):
            clouds[algorithm_id] = cloud
    return clouds


def common_bounds(clouds: dict[str, PointCloudData]) -> tuple[np.ndarray, np.ndarray]:
    low = np.min(np.vstack([cloud.bounds()[0] for cloud in clouds.values()]), axis=0)
    high = np.max(np.vstack([cloud.bounds()[1] for cloud in clouds.values()]), axis=0)
    span = np.maximum(high - low, 0.1)
    pad = span * 0.04
    return low - pad, high + pad


def camera_angles(preset: CameraPreset) -> tuple[float, float]:
    if preset.lookat is None or preset.eye is None:
        raise ValueError(
            "README demo requires a vector-form camera preset; captured view-matrix presets are for Open3D Inspector reuse"
        )
    delta = np.asarray(preset.eye) - np.asarray(preset.lookat)
    radius = float(np.linalg.norm(delta))
    if radius <= 1e-9:
        return 25.0, -60.0
    elev = math.degrees(math.asin(delta[2] / radius))
    azim = math.degrees(math.atan2(delta[1], delta[0]))
    return elev, azim


def render_frames(
    manifest: dict[str, Any],
    clouds: dict[str, PointCloudData],
    output_dir: Path,
    camera: CameraPreset,
    frames_per_algorithm: int,
) -> int:
    plt = require_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    low, high = common_bounds(clouds)
    elev0, azim0 = camera_angles(camera)
    frame_index = 0
    dataset = manifest.get("dataset", {})
    dataset_id = dataset.get("dataset_id", "legacy_v1_dataset")
    for algorithm_id, cloud in clouds.items():
        step = max(1, len(cloud.xyz) // 120_000)
        shown = cloud.xyz[::step]
        z = shown[:, 2]
        zlow, zhigh = np.percentile(z, [2, 98]) if len(z) else (0.0, 1.0)
        if not zhigh > zlow:
            zhigh = zlow + 1.0
        for local_index in range(frames_per_algorithm):
            phase = local_index / max(1, frames_per_algorithm - 1)
            azim = azim0 - 25.0 + 50.0 * phase
            fig = plt.figure(figsize=(9.6, 5.4), constrained_layout=True)
            axis = fig.add_subplot(111, projection="3d")
            axis.scatter(
                shown[:, 0], shown[:, 1], shown[:, 2],
                c=z, s=0.15, cmap="viridis", vmin=zlow, vmax=zhigh, rasterized=True,
            )
            axis.set_xlim(low[0], high[0])
            axis.set_ylim(low[1], high[1])
            axis.set_zlim(low[2], high[2])
            axis.set_box_aspect(
                (
                    max(high[0] - low[0], 0.1),
                    max(high[1] - low[1], 0.1),
                    max(high[2] - low[2], 0.1),
                )
            )
            axis.view_init(elev=elev0, azim=azim)
            axis.set_axis_off()
            config = manifest.get("algorithms", {}).get(algorithm_id, {})
            label = config.get("display_name", algorithm_id) if isinstance(config, dict) else algorithm_id
            fig.text(0.03, 0.94, str(label), fontsize=18, weight="bold")
            fig.text(0.03, 0.89, f"Same bag · {dataset_id} · identical ROI/camera path", fontsize=10)
            fig.text(0.03, 0.05, "Unified reconstruction from timestamp-matched trajectory", fontsize=9)
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
) -> None:
    if frames_per_algorithm < 2:
        raise ValueError("frames_per_algorithm must be >= 2")
    manifest = load_json(run / "manifest.json")
    selected = algorithms or list(manifest.get("algorithms", {}))
    roi = load_roi(roi_path) if roi_path else None
    clouds = load_clouds(run, selected, roi)
    if not clouds:
        raise SystemExit("No standardized unified maps are available for the README demo")
    low, high = common_bounds(clouds)
    camera = (
        load_camera(camera_path)
        if camera_path
        else orthographic_like_camera("demo", low, high, "perspective", 45.0)
    )
    frame_dir = run / "figures" / "demo_frames"
    count = render_frames(manifest, clouds, frame_dir, camera, frames_per_algorithm)
    metadata = {
        "schema": "lio_benchmark_demo/v2",
        "run_id": manifest.get("run_id", run.name),
        "dataset_id": manifest.get("dataset", {}).get("dataset_id", "legacy_v1_dataset"),
        "algorithms": list(clouds),
        "roi": str(roi_path) if roi_path else None,
        "camera": str(camera_path) if camera_path else "AUTO_SHARED_PERSPECTIVE",
        "frames_per_algorithm": frames_per_algorithm,
        "frame_count": count,
        "fps": fps,
        "output": str(output),
        "same_camera_path_for_all_algorithms": True,
    }
    (frame_dir / "demo_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    ffmpeg = shutil.which("ffmpeg")
    command = ffmpeg_gif_command(frame_dir / "frame_%05d.png", output, fps=fps)
    if ffmpeg is None:
        print("ffmpeg is not installed; frames were rendered successfully.", file=sys.stderr)
        print("After installing ffmpeg, run:", file=sys.stderr)
        print(" ".join(command), file=sys.stderr)
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
    parser.add_argument(
        "--output", type=Path, default=MODULE_ROOT / "assets/demo/same_bag_map_comparison.gif"
    )
    parser.add_argument("--frames-per-algorithm", type=int, default=24)
    parser.add_argument("--fps", type=int, default=12)
    args = parser.parse_args()
    generate(
        args.run.resolve(), args.algorithms, args.roi, args.camera, args.output,
        args.frames_per_algorithm, args.fps,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
