#!/usr/bin/env python3
"""Materialize an immutable GLIM config directory from a benchmark descriptor."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import yaml


def strip_json_comments(text: str) -> str:
    """Remove C/C++ comments while preserving strings and line numbers."""
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
        elif char == '"':
            in_string = True
            output.append(char)
            index += 1
        elif char == "/" and following == "/":
            while index < len(text) and text[index] != "\n":
                index += 1
        elif char == "/" and following == "*":
            index += 2
            while index + 1 < len(text) and text[index:index + 2] != "*/":
                output.append("\n" if text[index] == "\n" else " ")
                index += 1
            index += 2
        else:
            output.append(char)
            index += 1
    return "".join(output)


def read_json(path: Path) -> dict:
    return json.loads(strip_json_comments(path.read_text(encoding="utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("descriptor", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"拒绝覆盖 GLIM 配置目录: {args.output}")
    spec = yaml.safe_load(args.descriptor.read_text(encoding="utf-8"))
    workspace = Path(os.environ["LIO_BENCHMARK_ALGORITHM_WORKSPACE"])
    source = workspace / spec["upstream_config_relpath"]
    shutil.copytree(source, args.output)
    global_config = read_json(args.output / "config.json")
    global_config["global"].update({key: spec[key] for key in ("config_odometry", "config_sub_mapping", "config_global_mapping")})
    (args.output / "config.json").write_text(json.dumps(global_config, indent=2) + "\n", encoding="utf-8")
    ros = read_json(args.output / "config_ros.json")
    ros["glim_ros"].update({"enable_local_mapping": spec["enable_local_mapping"], "enable_global_mapping": spec["enable_global_mapping"], "imu_topic": spec["imu_topic"], "points_topic": spec["points_topic"], "acc_scale": spec["acc_scale"], "extension_modules": ["librviz_viewer.so"]})
    (args.output / "config_ros.json").write_text(json.dumps(ros, indent=2) + "\n", encoding="utf-8")
    sensors = read_json(args.output / "config_sensors.json")
    sensors["sensors"].update({"T_lidar_imu": spec["T_lidar_imu_xyzw"], "ring_field": "ring", "autoconf_perpoint_times": False, "autoconf_prefer_frame_time": True, "perpoint_relative_time": spec["perpoint_relative_time"], "perpoint_time_scale": spec["perpoint_time_scale"]})
    (args.output / "config_sensors.json").write_text(json.dumps(sensors, indent=2) + "\n", encoding="utf-8")
    preprocess = read_json(args.output / "config_preprocess.json")
    preprocess["preprocess"].update({"distance_near_thresh": spec["minimum_range_m"], "distance_far_thresh": spec["maximum_range_m"]})
    (args.output / "config_preprocess.json").write_text(json.dumps(preprocess, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
