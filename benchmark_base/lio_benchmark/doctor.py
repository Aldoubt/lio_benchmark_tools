"""Pre-flight checks that do not replay sensor data."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from .manifest import resolve_path, validate_manifest


def check_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    def add(name: str, ok: bool, detail: str, blocking: bool = True) -> None:
        checks.append({"name": name, "status": "PASS" if ok else ("FAIL" if blocking else "WARN"), "detail": detail})

    for error in validate_manifest(manifest, check_paths=True):
        add("manifest", False, error)
    add("ros_distro", os.environ.get("ROS_DISTRO") == "humble", f"ROS_DISTRO={os.environ.get('ROS_DISTRO', '')}")
    ros2 = shutil.which("ros2") or ("/opt/ros/humble/bin/ros2" if Path("/opt/ros/humble/bin/ros2").is_file() else None)
    add("ros2", bool(ros2), str(ros2 or "not found"))
    for module in ("rclpy", "rosbag2_py", "numpy", "scipy", "yaml", "psutil"):
        add(f"python:{module}", importlib.util.find_spec(module) is not None, "available" if importlib.util.find_spec(module) else "missing")
    bag = resolve_path(str(manifest.get("dataset", {}).get("bag_dir", "")))
    metadata = bag / "metadata.yaml"
    add("bag_dir", bag.is_dir(), str(bag))
    add("bag_metadata", metadata.is_file(), str(metadata))
    topics: dict[str, str] = {}
    if metadata.is_file():
        try:
            data = yaml.safe_load(metadata.read_text(encoding="utf-8"))["rosbag2_bagfile_information"]
            storage = data.get("storage_identifier") or "sqlite3 (inferred from .db3)"
            add("bag_storage", storage in ("sqlite3", "sqlite3 (inferred from .db3)"), str(storage))
            for item in data.get("topics_with_message_count", []):
                meta = item["topic_metadata"]
                topics[meta["name"]] = meta["type"]
        except Exception as exc:
            add("bag_metadata", False, repr(exc))
    dataset = manifest.get("dataset", {})
    for setup in dataset.get("setup_scripts", []):
        path = resolve_path(str(setup))
        add("dataset:setup", path.is_file(), str(path))
    for kind in ("lidar", "imu"):
        topic, expected = dataset.get(f"{kind}_topic"), dataset.get(f"{kind}_type")
        add(f"topic:{kind}", topic in topics and topics.get(topic) == expected, f"{topic}: actual={topics.get(topic)} expected={expected}")
    add("imu_acceleration_unit", dataset.get("imu_acceleration_unit") in ("g", "m/s^2"), str(dataset.get("imu_acceleration_unit")))
    time_detail = "/".join(str(dataset.get(key, "")) for key in ("point_time_field", "point_time_datatype", "point_time_unit", "point_time_semantics"))
    add("point_time_contract", "UNRESOLVED" not in time_detail and all(dataset.get(key) for key in ("point_time_field", "point_time_datatype", "point_time_unit", "point_time_semantics")), time_detail)
    validation_path = resolve_path(str(dataset.get("pre_run_input_validation", "")))
    validation_ok = False
    validation_detail = str(validation_path)
    if validation_path.is_file():
        try:
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            validation_ok = validation.get("output_time_backtracks_after_sort") == 0 and validation.get("non_finite_points") == 0
            validation_detail += f"; frames={validation.get('sampled_lidar_frames')} dropped_ratio={validation.get('dropped_ratio')}"
        except Exception as exc:
            validation_detail += f"; {exc!r}"
    add("point_time_validation", validation_ok, validation_detail)
    for name in ("lidar_to_imu", "imu_to_base", "lidar_to_base"):
        transform = manifest.get("calibration", {}).get(name, {})
        add(f"calibration:{name}", transform.get("confidence") not in (None, "", "UNRESOLVED"), str(transform.get("confidence")))
    output = resolve_path(str(manifest.get("output_root", "runs")))
    parent = output if output.exists() else output.parent
    add("output_writable", parent.is_dir() and os.access(parent, os.W_OK), str(output))
    if parent.is_dir():
        free_gib = shutil.disk_usage(parent).free / (1024 ** 3)
        add("output_disk_space", free_gib >= 20.0, f"free={free_gib:.1f} GiB (minimum preflight 20 GiB)")
    for name, config in manifest.get("algorithms", {}).items():
        if not config.get("enabled"):
            continue
        for key in ("runner", "config"):
            path = resolve_path(str(config.get(key, "")))
            add(f"algorithm:{name}:{key}", path.exists(), str(path))
        for setup in config.get("setup_scripts", []):
            path = resolve_path(str(setup))
            add(f"algorithm:{name}:setup", path.is_file(), str(path))
        for patch in config.get("patches", []):
            path = resolve_path(str(patch))
            add(f"algorithm:{name}:patch", path.is_file(), str(path))
        for executable in config.get("required_executables", []):
            path = resolve_path(str(executable))
            add(f"algorithm:{name}:executable", path.is_file() and os.access(path, os.X_OK), str(path))
    failures = sum(item["status"] == "FAIL" for item in checks)
    warnings = sum(item["status"] == "WARN" for item in checks)
    return {"status": "PASS" if failures == 0 else "FAIL", "failures": failures, "warnings": warnings, "checks": checks}
