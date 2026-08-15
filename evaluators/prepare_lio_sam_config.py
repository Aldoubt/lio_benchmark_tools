#!/usr/bin/env python3
"""Generate a run-local LIO-SAM ROS2 MID360 config from the integration template."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def yaml_scalar(value: str) -> str:
    return json.dumps(value)


def yaml_array(values: list[float]) -> str:
    return "[" + ", ".join(f"{float(value):.17g}" for value in values) + "]"


def replace_indented_key(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^(\s*){re.escape(key)}\s*:\s*.*$")
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"LIO-SAM template missing key: {key}")
    indent = match.group(1)
    return pattern.sub(f"{indent}{key}: {value}", text, count=1)


def invert_rotation(row_major: list[float]) -> list[float]:
    if len(row_major) != 9:
        raise SystemExit("rotation must contain 9 values")
    r = [float(value) for value in row_major]
    return [r[0], r[3], r[6], r[1], r[4], r[7], r[2], r[5], r[8]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads((args.run / "manifest.json").read_text(encoding="utf-8"))
    dataset = manifest["dataset"]
    if dataset.get("capabilities", {}).get("imu_orientation_valid") is not True:
        raise SystemExit("LIO-SAM requires dataset.capabilities.imu_orientation_valid=true")
    if dataset.get("types", {}).get("lidar") != "livox_ros_driver2/msg/CustomMsg":
        raise SystemExit("Current LIO-SAM MID360 ROS2 adapter requires Livox CustomMsg input")

    calibration = json.loads(
        (args.run / "configs/generated/lio_sam/calibration.json").read_text(encoding="utf-8")
    )
    if calibration["convention"] != "LIDAR_TO_IMU":
        raise SystemExit(f"LIO-SAM adapter expects canonical LIDAR_TO_IMU, got {calibration['convention']}")
    r_li = [float(value) for value in calibration["rotation_row_major"]]
    r_il = invert_rotation(r_li)
    t_li = [float(value) for value in calibration["translation_m"]]

    template = args.source / "config/params.yaml"
    if not template.is_file():
        raise SystemExit(f"LIO-SAM integration template not found: {template}")
    text = template.read_text(encoding="utf-8")
    replacements = {
        "pointCloudTopic": yaml_scalar(dataset["topics"]["lidar"]),
        "imuTopic": yaml_scalar(dataset["topics"]["imu"]),
        "gpsTopic": yaml_scalar("/lio_benchmark/disabled_gps"),
        "sensor": yaml_scalar("livox"),
        "N_SCAN": "4",
        "extrinsicTrans": yaml_array(t_li),
        "extrinsicRot": yaml_array(r_il),
        "extrinsicRPY": yaml_array(r_li),
        "useImuHeadingInitialization": "false",
    }
    for key, value in replacements.items():
        text = replace_indented_key(text, key, value)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    metadata = {
        "schema_version": 1,
        "algorithm_id": "lio_sam",
        "algorithm_repository": "TixiaoShan/LIO-SAM",
        "execution_repository": "UV-Lab/LIO-SAM_MID360_ROS2_PKG",
        "implementation_repository": "UV-Lab/LIO-SAM_MID360_ROS2",
        "template": str(template),
        "config": str(args.output),
        "imu_orientation_valid": True,
        "extrinsicTrans_semantics": "LIDAR_TO_IMU translation",
        "extrinsicRot_semantics": "IMU_TO_LIDAR rotation",
        "extrinsicRPY_semantics": "LIDAR_TO_IMU rotation; source internally inverts for attitude",
        "calibration_status": calibration.get("calibration_status"),
        "calibration_source": calibration.get("calibration_source"),
        "gnss_enabled": False,
    }
    (args.output.parent / "adapter_config_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
