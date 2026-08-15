#!/usr/bin/env python3
"""Convert upstream trajectory CSV files into the V2 standard trajectory contract."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.trajectory import (  # noqa: E402
    PoseSample,
    Trajectory,
    TrajectoryError,
    normalize_quaternion,
    quaternion_from_rpy,
    rpy_from_quaternion,
)


def load_column_map(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    path = Path(value)
    payload = path.read_text(encoding="utf-8") if path.is_file() else value
    decoded = json.loads(payload)
    if not isinstance(decoded, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in decoded.items()):
        raise ValueError("column map must be a JSON object of standardized_name -> source_name")
    return decoded


def resolve_name(fieldnames: list[str], target: str, mapping: dict[str, str], aliases: tuple[str, ...]) -> str | None:
    requested = mapping.get(target)
    if requested:
        if requested not in fieldnames:
            raise ValueError(f"column map for {target} points to missing source column {requested}")
        return requested
    for name in (target, *aliases):
        if name in fieldnames:
            return name
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-topic", default="")
    parser.add_argument("--column-map", help="JSON string or path; keys use standardized column names")
    args = parser.parse_args()

    mapping = load_column_map(args.column_map)
    with args.input.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError("input trajectory CSV has no header")
        fieldnames = list(reader.fieldnames)
        names = {
            "timestamp_s": resolve_name(fieldnames, "timestamp_s", mapping, ("time_s", "timestamp", "stamp_s")),
            "x_m": resolve_name(fieldnames, "x_m", mapping, ("x",)),
            "y_m": resolve_name(fieldnames, "y_m", mapping, ("y",)),
            "z_m": resolve_name(fieldnames, "z_m", mapping, ("z",)),
            "qx": resolve_name(fieldnames, "qx", mapping, ()),
            "qy": resolve_name(fieldnames, "qy", mapping, ()),
            "qz": resolve_name(fieldnames, "qz", mapping, ()),
            "qw": resolve_name(fieldnames, "qw", mapping, ()),
            "roll_rad": resolve_name(fieldnames, "roll_rad", mapping, ("roll",)),
            "pitch_rad": resolve_name(fieldnames, "pitch_rad", mapping, ("pitch",)),
            "yaw_rad": resolve_name(fieldnames, "yaw_rad", mapping, ("yaw",)),
        }
        required = ("timestamp_s", "x_m", "y_m", "z_m")
        missing = [key for key in required if names[key] is None]
        if missing:
            raise ValueError(f"input trajectory missing required columns: {', '.join(missing)}")
        has_quaternion = all(names[key] is not None for key in ("qx", "qy", "qz", "qw"))
        has_rpy = all(names[key] is not None for key in ("roll_rad", "pitch_rad", "yaw_rad"))
        if not has_quaternion and not has_rpy:
            raise ValueError("input trajectory must provide quaternion or roll/pitch/yaw")
        samples: list[PoseSample] = []
        for row in reader:
            timestamp = float(row[names["timestamp_s"]])  # type: ignore[index]
            x = float(row[names["x_m"]])  # type: ignore[index]
            y = float(row[names["y_m"]])  # type: ignore[index]
            z = float(row[names["z_m"]])  # type: ignore[index]
            if has_quaternion:
                q = normalize_quaternion(
                    tuple(float(row[names[key]]) for key in ("qx", "qy", "qz", "qw"))  # type: ignore[index]
                )
                roll, pitch, yaw = rpy_from_quaternion(*q)
            else:
                roll = float(row[names["roll_rad"]])  # type: ignore[index]
                pitch = float(row[names["pitch_rad"]])  # type: ignore[index]
                yaw = float(row[names["yaw_rad"]])  # type: ignore[index]
                q = quaternion_from_rpy(roll, pitch, yaw)
            samples.append(
                PoseSample(timestamp, x, y, z, q[0], q[1], q[2], q[3], roll, pitch, yaw, args.source_topic)
            )
    try:
        trajectory = Trajectory(samples)
    except TrajectoryError as exc:
        raise SystemExit(str(exc)) from exc
    trajectory.write_csv(args.output)
    summary = {
        "input": str(args.input),
        "output": str(args.output),
        "samples": len(trajectory.samples),
        "start_timestamp_s": trajectory.timestamps[0],
        "end_timestamp_s": trajectory.timestamps[-1],
        "source_topic": args.source_topic,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
