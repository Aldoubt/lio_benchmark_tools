#!/usr/bin/env python3
"""Pure reporting contracts that do not require matplotlib or Open3D."""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from benchmark_base.lib.trajectory import Trajectory


@dataclass(frozen=True)
class AlgorithmSummary:
    algorithm_id: str
    run_status: str
    returncode: int | None
    trajectory_status: str
    trajectory_samples: int | None
    path_length_m: float | None
    end_translation_m: float | None
    map_status: str
    map_source: str | None
    map_points: int | None
    matched_scans: int | None
    unmatched_scans: int | None
    runtime_s: float | None


def _runtime_seconds(payload: dict[str, Any]) -> float | None:
    try:
        start = datetime.fromisoformat(str(payload["started_at"]))
        finish = datetime.fromisoformat(str(payload["finished_at"]))
    except (KeyError, TypeError, ValueError):
        return None
    return max(0.0, (finish - start).total_seconds())


def trajectory_metrics(path: Path) -> tuple[int, float, float]:
    trajectory = Trajectory.from_csv(path)
    length = 0.0
    for left, right in zip(trajectory.samples, trajectory.samples[1:]):
        length += math.sqrt(
            (right.x_m - left.x_m) ** 2
            + (right.y_m - left.y_m) ** 2
            + (right.z_m - left.z_m) ** 2
        )
    first, last = trajectory.samples[0], trajectory.samples[-1]
    displacement = math.sqrt(
        (last.x_m - first.x_m) ** 2
        + (last.y_m - first.y_m) ** 2
        + (last.z_m - first.z_m) ** 2
    )
    return len(trajectory.samples), length, displacement


def collect_summary(run: str | Path, algorithm_id: str) -> AlgorithmSummary:
    run = Path(run)
    run_meta = run / "metadata" / f"run_{algorithm_id}.json"
    if run_meta.is_file():
        execution = json.loads(run_meta.read_text(encoding="utf-8"))
        run_status = str(execution.get("status", "UNKNOWN"))
        returncode = execution.get("returncode")
        runtime_s = _runtime_seconds(execution)
    else:
        run_status, returncode, runtime_s = "MISSING", None, None

    trajectory_path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
    if trajectory_path.is_file():
        try:
            trajectory_samples, path_length, end_translation = trajectory_metrics(trajectory_path)
            trajectory_status = "AVAILABLE"
        except Exception:
            trajectory_status, trajectory_samples, path_length, end_translation = "INVALID", None, None, None
    else:
        trajectory_status, trajectory_samples, path_length, end_translation = "MISSING", None, None, None

    map_meta = run / "standardized" / "maps" / algorithm_id / "map_metadata.json"
    if map_meta.is_file():
        try:
            metadata = json.loads(map_meta.read_text(encoding="utf-8"))
            matching = metadata.get("timestamp_matching", {})
            map_status = "AVAILABLE"
            map_source = metadata.get("map_source")
            map_points = int(metadata["point_count"])
            matched_scans = matching.get("matched_scan_count")
            unmatched_scans = matching.get("unmatched_scan_count")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            map_status, map_source, map_points, matched_scans, unmatched_scans = "INVALID", None, None, None, None
    else:
        map_status, map_source, map_points, matched_scans, unmatched_scans = "MISSING", None, None, None, None

    return AlgorithmSummary(
        algorithm_id=algorithm_id,
        run_status=run_status,
        returncode=returncode,
        trajectory_status=trajectory_status,
        trajectory_samples=trajectory_samples,
        path_length_m=path_length,
        end_translation_m=end_translation,
        map_status=map_status,
        map_source=map_source,
        map_points=map_points,
        matched_scans=matched_scans,
        unmatched_scans=unmatched_scans,
        runtime_s=runtime_s,
    )


def write_summary_csv(path: str | Path, rows: list[AlgorithmSummary]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(rows[0]).keys()) if rows else list(AlgorithmSummary.__dataclass_fields__)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def ffmpeg_gif_command(frame_pattern: Path, output: Path, fps: int = 12, width_px: int = 960) -> list[str]:
    if fps <= 0 or width_px <= 0:
        raise ValueError("fps and width_px must be positive")
    filter_graph = (
        f"fps={fps},scale={width_px}:-1:flags=lanczos,split[s0][s1];"
        "[s0]palettegen=max_colors=192[p];[s1][p]paletteuse=dither=bayer"
    )
    return [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frame_pattern),
        "-vf",
        filter_graph,
        "-loop",
        "0",
        str(output),
    ]
