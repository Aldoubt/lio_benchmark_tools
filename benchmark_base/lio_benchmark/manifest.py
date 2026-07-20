"""Manifest loading, migration and semantic validation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .registry import validate_registry_entry

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"配置不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 格式错误 {path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("manifest 顶层必须是对象")
    return data


def resolve_path(value: str, base: Path | None = None) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    return expanded if expanded.is_absolute() else (base or REPO_ROOT) / expanded


def _matrix_ok(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 9 and all(isinstance(x, (int, float)) for x in value)


def _vector_ok(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(isinstance(x, (int, float)) for x in value)


def validate_manifest(manifest: dict[str, Any], check_paths: bool = True) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 2:
        errors.append("schema_version 必须为 2；v1 请先使用 migrate-manifest")
    for key in ("name", "output_root", "dataset", "calibration", "algorithms"):
        if key not in manifest:
            errors.append(f"缺少顶层字段: {key}")
    dataset = manifest.get("dataset")
    if not isinstance(dataset, dict):
        return errors + ["dataset 必须是对象"]
    required_dataset = (
        "bag_dir", "storage_id", "lidar_topic", "lidar_type", "imu_topic", "imu_type",
        "point_time_field", "point_time_datatype", "point_time_unit", "point_time_semantics",
    )
    for key in required_dataset:
        if dataset.get(key) in (None, ""):
            errors.append(f"dataset 缺少字段: {key}")
    if check_paths and dataset.get("bag_dir"):
        bag = resolve_path(str(dataset["bag_dir"]))
        if not bag.is_dir():
            errors.append(f"bag_dir 不存在: {bag}")
        elif not (bag / "metadata.yaml").is_file():
            errors.append(f"bag_dir 缺少 metadata.yaml: {bag}")
    calibration = manifest.get("calibration", {})
    if not isinstance(calibration, dict):
        errors.append("calibration 必须是对象")
    else:
        for name in ("lidar_to_imu", "imu_to_base", "lidar_to_base"):
            transform = calibration.get(name)
            if not isinstance(transform, dict):
                errors.append(f"calibration.{name} 必须是对象")
                continue
            if not _matrix_ok(transform.get("rotation")) or not _vector_ok(transform.get("translation")):
                errors.append(f"calibration.{name} 必须含 9 项 rotation 和 3 项 translation")
            if transform.get("direction") != name:
                errors.append(f"calibration.{name}.direction 必须显式为 {name}")
    algorithms = manifest.get("algorithms")
    if not isinstance(algorithms, dict):
        return errors + ["algorithms 必须是对象"]
    for name, config in algorithms.items():
        if not isinstance(config, dict):
            errors.append(f"algorithm {name} 必须是对象")
            continue
        errors.extend(validate_registry_entry(name, config))
        for key in ("enabled", "workspace", "source", "branch", "commit", "setup_scripts", "runner", "config", "input_topics", "output_topics", "patches"):
            if key not in config:
                errors.append(f"algorithm {name} 缺少字段: {key}")
        if check_paths and config.get("enabled", False):
            for key in ("workspace", "runner", "config"):
                target = resolve_path(str(config.get(key, "")))
                if not target.exists():
                    errors.append(f"algorithm {name}.{key} 不存在: {target}")
            for setup in config.get("setup_scripts", []):
                target = resolve_path(str(setup))
                if not target.is_file():
                    errors.append(f"algorithm {name} setup 不存在: {target}")
    return errors


def migrate_v1(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("schema_version") != 1:
        raise ValueError("输入不是 schema v1 manifest")
    old_dataset = source.get("dataset", {})
    old_cal = source.get("calibration", {})
    algorithms: dict[str, Any] = {}
    group_map = {"glim_full_slam": "full_slam"}
    for name, old in source.get("algorithms", {}).items():
        group = group_map.get(name, "lidar_imu_odometry")
        algorithms[name] = {
            "enabled": True, "group": group, "mode": old.get("mode", "odometry"),
            "sensor_inputs": ["lidar", "imu"], "workspace": source.get("workspace", "UNRESOLVED"),
            "source": old.get("source", "UNRESOLVED"), "repository": "UNRESOLVED", "branch": "UNRESOLVED",
            "commit": "UNRESOLVED", "setup_scripts": [], "runner": old.get("runner", "UNRESOLVED"),
            "config": "UNRESOLVED", "input_topics": {}, "output_topics": {}, "patches": [],
        }
    r = old_cal.get("rotation_lidar_to_imu_row_major", [1,0,0,0,1,0,0,0,1])
    t = old_cal.get("translation_lidar_to_imu_m", [0,0,0])
    unresolved = {"rotation": [1,0,0,0,1,0,0,0,1], "translation": [0,0,0], "confidence": "UNRESOLVED"}
    return {
        "schema_version": 2, "name": source.get("name", "migrated_experiment"),
        "output_root": source.get("output_root", "runs"), "playback_rate": 1.0,
        "dataset": {
            "bag_dir": old_dataset.get("bag_dir", "UNRESOLVED"), "storage_id": "sqlite3",
            "lidar_topic": old_dataset.get("lidar_topic", "UNRESOLVED"), "lidar_type": old_dataset.get("lidar_type", "UNRESOLVED"),
            "imu_topic": old_dataset.get("imu_topic", "UNRESOLVED"), "imu_type": old_dataset.get("imu_type", "UNRESOLVED"),
            "wheel_odom_topic": None, "ground_truth": None, "imu_acceleration_unit": old_dataset.get("imu_acceleration_unit", "UNRESOLVED"),
            "point_time_field": old_dataset.get("point_time_field", "UNRESOLVED"), "point_time_datatype": "UNRESOLVED",
            "point_time_unit": old_dataset.get("point_time_unit", "UNRESOLVED"), "point_time_semantics": "UNRESOLVED",
            "start_offset_s": 0.0, "end_offset_s": None,
        },
        "calibration": {
            "lidar_to_imu": {"direction": "lidar_to_imu", "rotation": r, "translation": t, "confidence": "migrated"},
            "imu_to_base": {"direction": "imu_to_base", **unresolved},
            "lidar_to_base": {"direction": "lidar_to_base", **unresolved},
            "source": old_cal.get("source", "UNRESOLVED"), "confidence": "migrated",
        },
        "evaluation": source.get("evaluation", {}), "algorithms": algorithms,
    }
