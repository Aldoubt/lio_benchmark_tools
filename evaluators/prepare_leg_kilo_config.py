#!/usr/bin/env python3
"""Generate a current-master Leg-KILO LIO config from its official MID360 template."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def yaml_scalar(value: str) -> str:
    return json.dumps(value)


def yaml_array(values: list[float]) -> str:
    return "[" + ", ".join(f"{float(value):.17g}" for value in values) + "]"


def replace_key(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(key)}\s*:\s*.*$")
    line = f"{key}: {value}"
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    return text.rstrip() + "\n" + line + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads((args.run / "manifest.json").read_text(encoding="utf-8"))
    dataset = manifest["dataset"]
    lidar_type = dataset.get("types", {}).get("lidar")
    if lidar_type != "livox_ros_driver2/msg/CustomMsg":
        raise SystemExit(
            "Current Leg-KILO MID360 adapter is frozen for livox_ros_driver2/msg/CustomMsg; "
            f"dataset provides {lidar_type!r}"
        )

    calibration_path = args.run / "configs/generated/leg_kilo/calibration.json"
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if calibration["convention"] != "LIDAR_TO_IMU":
        raise SystemExit(f"Leg-KILO master requires LIDAR_TO_IMU, got {calibration['convention']}")

    template = args.source / "legkilo/config/m3dgr_mid360.yaml"
    if not template.is_file():
        raise SystemExit(f"official Leg-KILO MID360 template not found: {template}")
    text = template.read_text(encoding="utf-8-sig")
    run_id = str(manifest.get("run_id", args.run.name))
    result_name = "lio_benchmark_" + re.sub(r"[^A-Za-z0-9_.-]", "_", run_id)

    replacements = {
        "lidar_topic": yaml_scalar(dataset["topics"]["lidar"]),
        "imu_topic": yaml_scalar(dataset["topics"]["imu"]),
        "sensor_type": "LIO",
        "extrinsic_T": yaml_array(calibration["translation_m"]),
        "extrinsic_R": yaml_array(calibration["rotation_row_major"]),
        "lidar_type": "5",
        "time_scale": "1e-9",
        "temp_result_save_folder": yaml_scalar(result_name),
    }
    for key, value in replacements.items():
        text = replace_key(text, key, value)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    metadata = {
        "schema_version": 1,
        "algorithm_id": "leg_kilo",
        "source_repository": "ouguangjun/Leg-KILO",
        "source_branch": "master",
        "template": str(template),
        "config": str(args.output),
        "sensor_type": "LIO",
        "kinematics": False,
        "time_scale": 1e-9,
        "temp_result_save_folder": result_name,
        "upstream_runtime_result_path": str(args.source / "result" / result_name),
        "calibration_convention": calibration["convention"],
        "calibration_status": calibration.get("calibration_status"),
        "calibration_source": calibration.get("calibration_source"),
    }
    (args.output.parent / "adapter_config_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
