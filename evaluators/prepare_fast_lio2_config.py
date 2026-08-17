#!/usr/bin/env python3
"""Generate a run-local FAST-LIO2 ROS2 config from the frozen benchmark manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def float_scalar(value: float) -> str:
    # Keep run-local parameter provenance human-readable without exposing the
    # binary expansion of ordinary decimal calibration constants.
    text = f"{float(value):.12g}"
    if "." not in text and "e" not in text.lower():
        text += ".0"
    return text


def fmt(values: list[float]) -> str:
    return "[" + ", ".join(float_scalar(v) for v in values) + "]"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collect-native-map", action="store_true")
    args = parser.parse_args()

    manifest = json.loads((args.run / "manifest.json").read_text(encoding="utf-8"))
    dataset = manifest["dataset"]
    generated = args.run / "configs/generated/fast_lio2/calibration.json"
    calibration = json.loads(generated.read_text(encoding="utf-8"))
    if calibration["convention"] != "LIDAR_TO_IMU":
        raise SystemExit(f"FAST-LIO2 requires LIDAR_TO_IMU, got {calibration['convention']}")

    lidar_type = dataset.get("types", {}).get("lidar", "")
    if lidar_type == "livox_ros_driver2/msg/CustomMsg":
        preprocess_lidar_type = 1
        timestamp_unit = 3  # nanoseconds for this ROS2 port's MID360 config
        scan_line = 4
    elif lidar_type == "sensor_msgs/msg/PointCloud2":
        preprocess_lidar_type = 4
        timestamp_unit = 3
        scan_line = 4
    else:
        raise SystemExit(f"unsupported FAST-LIO2 LiDAR message type: {lidar_type}")

    native_map = args.output.parent / "native_map.pcd"
    text = f"""/**:
  ros__parameters:
    feature_extract_enable: false
    point_filter_num: 3
    max_iteration: 3
    filter_size_surf: 0.5
    filter_size_map: 0.5
    cube_side_length: 1000.0
    runtime_pos_log_enable: true
    map_file_path: \"{native_map}\"
    common:
      lid_topic: \"{dataset['topics']['lidar']}\"
      imu_topic: \"{dataset['topics']['imu']}\"
      time_sync_en: false
      time_offset_lidar_to_imu: 0.0
    preprocess:
      lidar_type: {preprocess_lidar_type}
      scan_line: {scan_line}
      blind: 0.5
      timestamp_unit: {timestamp_unit}
      scan_rate: 10
    mapping:
      acc_cov: 0.1
      gyr_cov: 0.1
      b_acc_cov: 0.0001
      b_gyr_cov: 0.0001
      fov_degree: 360.0
      det_range: 100.0
      extrinsic_est_en: false
      extrinsic_T: {fmt(calibration['translation_m'])}
      extrinsic_R: {fmt(calibration['rotation_row_major'])}
    publish:
      path_en: true
      effect_map_en: false
      map_en: {'true' if args.collect_native_map else 'false'}
      scan_publish_en: true
      dense_publish_en: false
      scan_bodyframe_pub_en: true
    pcd_save:
      pcd_save_en: {'true' if args.collect_native_map else 'false'}
      interval: -1
"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    metadata = {
        "schema_version": 1,
        "algorithm_id": "fast_lio2",
        "execution_repository": "Franklif1/Fast_LIO2_ROS2",
        "execution_branch": "ros2",
        "lidar_type": lidar_type,
        "collect_native_map": args.collect_native_map,
        "config": str(args.output),
        "native_map_path": str(native_map) if args.collect_native_map else None,
        "canonical_convention": calibration.get("canonical_convention"),
        "canonical_equation": calibration.get("canonical_equation"),
        "effective_convention": calibration.get("convention"),
        "rotation_row_major": calibration.get("rotation_row_major"),
        "translation_m": calibration.get("translation_m"),
        "calibration_source": calibration.get("calibration_source"),
        "calibration_source_type": calibration.get("calibration_source_type"),
        "calibration_status": calibration.get("calibration_status"),
        "sensor_model": calibration.get("sensor_model"),
        "imu_relation": calibration.get("imu_relation"),
        "online_extrinsic_estimation": False,
    }
    (args.output.parent / "adapter_config_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
