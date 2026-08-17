#!/usr/bin/env python3
"""Plan Representative Window V1 from raw LiDAR/IMU evidence only."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import io
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.cloud_contract import cloud_rows  # noqa: E402
from benchmark_base.lib.manifest import load_json  # noqa: E402
from benchmark_base.lib.representative_windows import (  # noqa: E402
    LIDAR_NEAR_RANGE_M,
    LIDAR_POINT_STEP,
    MIN_IMU_SAMPLES_PER_WINDOW,
    MIN_LIDAR_SCANS_PER_WINDOW,
    POST_INITIALIZATION_GUARD_S,
    RANGE_HISTOGRAM_BINS,
    RANGE_HISTOGRAM_MAX_M,
    SCHEMA_VERSION,
    SELECTION_LABELS,
    WINDOW_DURATION_S,
    WINDOW_STRIDE_S,
    ImuFeatureSample,
    RepresentativeWindowError,
    SelectedWindow,
    WindowFeature,
    build_child_experiment_config,
    build_window_features,
    lidar_scan_feature,
    select_from_window_features,
    validate_selector_manifest,
)
from benchmark_base.lib.rosbag_trajectory import (  # noqa: E402
    normalize_topic,
    open_reader,
    topic_map,
)


FEATURE_FIELDS = (
    "start_offset_s",
    "duration_s",
    "lidar_scan_count",
    "imu_sample_count",
    "gyro_rms_rad_s",
    "gyro_p95_rad_s",
    "accel_dynamic_rms_native",
    "scene_change_mean",
    "geometric_degeneracy_median",
    "geometric_degeneracy_p90",
    "valid",
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _window_feature_csv(features: tuple[WindowFeature, ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FEATURE_FIELDS)
    writer.writeheader()
    for feature in features:
        writer.writerow({name: getattr(feature, name) for name in FEATURE_FIELDS})
    return stream.getvalue().encode("utf-8")


def _selected_payload(selected: tuple[SelectedWindow, ...]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "labels": list(SELECTION_LABELS),
        "windows": [
            {
                "label": item.label,
                "start_offset_s": item.start_offset_s,
                "duration_s": item.duration_s,
                "end_offset_s": item.end_offset_s,
                "selection_score": item.score,
                "features": asdict(item.feature),
            }
            for item in selected
        ],
    }


def _plan_markdown(
    run: Path,
    dataset: dict[str, Any],
    selected: tuple[SelectedWindow, ...],
    acceleration_unit: str,
) -> bytes:
    lines = [
        "# Representative Window V1 Plan",
        "",
        f"- selector run: `{run}`",
        f"- dataset: `{dataset.get('dataset_id', 'UNKNOWN')}`",
        "- selection inputs: raw LiDAR + raw IMU only",
        "- estimator outputs used: false",
        "- ground truth used: false",
        "- scientific status: DESCRIPTIVE_NO_GROUND_TRUTH",
        f"- raw acceleration unit: `{acceleration_unit}`",
        "",
        "| label | start offset (s) | duration (s) | gyro p95 (rad/s) | scene change | geometric proxy |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in selected:
        feature = item.feature
        lines.append(
            f"| {item.label} | {item.start_offset_s:.3f} | {item.duration_s:.1f} | "
            f"{feature.gyro_p95_rad_s:.6g} | {feature.scene_change_mean:.6g} | "
            f"{feature.geometric_degeneracy_median:.6g} |"
        )
    lines.extend(
        [
            "",
            "`geometric_degeneracy_candidate` and `steady_translation_candidate` are raw-sensor-derived candidate labels, not ground-truth motion classes.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def _read_raw_features(
    manifest: dict[str, Any],
) -> tuple[tuple[Any, ...], tuple[ImuFeatureSample, ...], float, dict[str, Any]]:
    dataset = manifest.get("dataset")
    if not isinstance(dataset, dict):
        raise RepresentativeWindowError("selector run dataset is missing")
    bag = Path(str(dataset.get("bag_dir", ""))).expanduser().resolve()
    if not bag.is_dir():
        raise RepresentativeWindowError(f"selector bag directory does not exist: {bag}")

    topics = dataset.get("topics")
    types = dataset.get("types")
    if not isinstance(topics, dict) or not isinstance(types, dict):
        raise RepresentativeWindowError("selector dataset topics/types are missing")
    lidar_topic = normalize_topic(str(topics.get("lidar", "")))
    imu_topic = normalize_topic(str(topics.get("imu", "")))
    lidar_type = str(types.get("lidar", "")).strip()
    imu_type = str(types.get("imu", "")).strip()
    if not lidar_topic or not imu_topic or not lidar_type or not imu_type:
        raise RepresentativeWindowError("selector requires raw LiDAR and IMU topics/types")

    available = topic_map(bag)
    for topic, expected_type in ((lidar_topic, lidar_type), (imu_topic, imu_type)):
        if topic not in available:
            raise RepresentativeWindowError(f"selector bag is missing topic {topic}")
        actual_type = available[topic][1]
        if actual_type != expected_type:
            raise RepresentativeWindowError(
                f"selector topic type mismatch for {topic}: expected {expected_type}, got {actual_type}"
            )

    lidar_class = get_message(lidar_type)
    imu_class = get_message(imu_type)
    reader = open_reader(bag)
    first_record_ns: int | None = None
    last_lidar_offset: float | None = None
    last_imu_offset: float | None = None
    lidar_features: list[Any] = []
    imu_features: list[ImuFeatureSample] = []
    skipped_lidar_scans = 0

    while reader.has_next():
        current_topic, raw, recorded_ns = reader.read_next()
        if first_record_ns is None:
            first_record_ns = int(recorded_ns)
        offset_s = (int(recorded_ns) - first_record_ns) * 1e-9
        normalized = normalize_topic(current_topic)
        if normalized == lidar_topic:
            message = deserialize_message(raw, lidar_class)
            try:
                rows = cloud_rows(message, LIDAR_POINT_STEP, LIDAR_NEAR_RANGE_M)
                feature = lidar_scan_feature(offset_s, np.asarray(rows[:, :3], dtype=np.float64))
            except (ValueError, RepresentativeWindowError, IndexError):
                skipped_lidar_scans += 1
                continue
            lidar_features.append(feature)
            last_lidar_offset = offset_s
        elif normalized == imu_topic:
            message = deserialize_message(raw, imu_class)
            angular_velocity = message.angular_velocity
            linear_acceleration = message.linear_acceleration
            angular_speed = math.sqrt(
                float(angular_velocity.x) ** 2
                + float(angular_velocity.y) ** 2
                + float(angular_velocity.z) ** 2
            )
            acceleration_norm = math.sqrt(
                float(linear_acceleration.x) ** 2
                + float(linear_acceleration.y) ** 2
                + float(linear_acceleration.z) ** 2
            )
            if not math.isfinite(angular_speed) or not math.isfinite(acceleration_norm):
                continue
            imu_features.append(ImuFeatureSample(offset_s, angular_speed, acceleration_norm))
            last_imu_offset = offset_s

    if first_record_ns is None or last_lidar_offset is None or last_imu_offset is None:
        raise RepresentativeWindowError("selector bag has no usable raw LiDAR/IMU interval")
    analysis_end_s = min(last_lidar_offset, last_imu_offset)
    raw_meta = {
        "bag_dir": str(bag),
        "first_bag_record_ns": first_record_ns,
        "analysis_end_offset_s": analysis_end_s,
        "usable_lidar_scans": len(lidar_features),
        "skipped_lidar_scans": skipped_lidar_scans,
        "usable_imu_samples": len(imu_features),
        "lidar_topic": lidar_topic,
        "lidar_type": lidar_type,
        "imu_topic": imu_topic,
        "imu_type": imu_type,
    }
    return tuple(lidar_features), tuple(imu_features), analysis_end_s, raw_meta


def _expected_contents(
    run: Path,
    manifest: dict[str, Any],
    features: tuple[WindowFeature, ...],
    selected: tuple[SelectedWindow, ...],
    raw_meta: dict[str, Any],
) -> dict[Path, bytes]:
    metadata_dir = run / "metadata" / "representative_windows"
    config_dir = run / "configs" / "representative_windows"
    report_path = run / "reports" / "REPRESENTATIVE_WINDOW_PLAN.md"
    dataset = manifest["dataset"]
    acceleration_unit = str(
        dataset.get("imu", {}).get("linear_acceleration_unit", "DATASET_NATIVE")
        if isinstance(dataset.get("imu"), dict)
        else "DATASET_NATIVE"
    )

    contents: dict[Path, bytes] = {
        metadata_dir / "window_features.csv": _window_feature_csv(features),
        metadata_dir / "selected_windows.json": _json_bytes(_selected_payload(selected)),
        report_path: _plan_markdown(run, dataset, selected, acceleration_unit),
    }
    child_fingerprints: dict[str, dict[str, Any]] = {}
    for item in selected:
        config = build_child_experiment_config(manifest, item)
        payload = _json_bytes(config)
        relative = Path("configs") / "representative_windows" / f"{item.label}.json"
        path = run / relative
        contents[path] = payload
        child_fingerprints[item.label] = {
            "path": relative.as_posix(),
            "sha256": _sha256_bytes(payload),
            "start_offset_s": item.start_offset_s,
            "duration_s": item.duration_s,
        }

    manifest_path = run / "manifest.json"
    bag_dir = Path(str(dataset["bag_dir"])).expanduser().resolve()
    selection_metadata = {
        "schema_version": SCHEMA_VERSION,
        "policy": "REPRESENTATIVE_WINDOW_V1_RAW_SENSOR_ONLY",
        "selection_inputs": ["RAW_LIDAR", "RAW_IMU", "BAG_RECORD_TIME"],
        "estimator_outputs_used": False,
        "ground_truth_used": False,
        "scientific_status": "DESCRIPTIVE_NO_GROUND_TRUTH",
        "time_domain": "BAG_RECORD_OFFSET_FROM_FIRST_RECORD",
        "dataset_id": dataset.get("dataset_id"),
        "bag_dir": str(bag_dir),
        "dataset_declared_sha256": dataset.get("sha256"),
        "bag_metadata_yaml_sha256": _sha256_file(bag_dir / "metadata.yaml"),
        "selector_manifest_sha256": _sha256_file(manifest_path),
        "algorithm_ids": list(manifest["algorithm_refs"]),
        "raw_sensor_evidence": raw_meta,
        "imu_acceleration_input_unit": acceleration_unit,
        "constants": {
            "window_duration_s": WINDOW_DURATION_S,
            "window_stride_s": WINDOW_STRIDE_S,
            "post_initialization_guard_s": POST_INITIALIZATION_GUARD_S,
            "lidar_point_step": LIDAR_POINT_STEP,
            "lidar_near_range_m": LIDAR_NEAR_RANGE_M,
            "range_histogram_max_m": RANGE_HISTOGRAM_MAX_M,
            "range_histogram_bins": RANGE_HISTOGRAM_BINS,
            "minimum_lidar_scans_per_window": MIN_LIDAR_SCANS_PER_WINDOW,
            "minimum_imu_samples_per_window": MIN_IMU_SAMPLES_PER_WINDOW,
        },
        "selected_windows": [
            {
                "label": item.label,
                "start_offset_s": item.start_offset_s,
                "duration_s": item.duration_s,
                "end_offset_s": item.end_offset_s,
            }
            for item in selected
        ],
        "child_configs": child_fingerprints,
    }
    contents[metadata_dir / "selection_metadata.json"] = _json_bytes(selection_metadata)
    return contents


def _commit_immutable(contents: dict[Path, bytes]) -> None:
    existing = [path.is_file() for path in contents]
    if any(existing) and not all(existing):
        raise RepresentativeWindowError("partial representative-window artifacts already exist")
    if all(existing):
        mismatched = [path for path, payload in contents.items() if path.read_bytes() != payload]
        if mismatched:
            raise RepresentativeWindowError(
                "existing representative-window artifacts do not match current frozen inputs: "
                + ", ".join(str(path) for path in mismatched)
            )
        return

    for path, payload in contents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)


def plan_run(run: str | Path) -> Path:
    run = Path(run).resolve()
    manifest_path = run / "manifest.json"
    if not manifest_path.is_file():
        raise RepresentativeWindowError(f"missing selector run manifest: {manifest_path}")
    manifest = load_json(manifest_path)
    validate_selector_manifest(manifest)
    lidar, imu, analysis_end_s, raw_meta = _read_raw_features(manifest)
    features = build_window_features(lidar, imu, analysis_end_s=analysis_end_s)
    selected = select_from_window_features(features)
    contents = _expected_contents(run, manifest, features, selected, raw_meta)
    _commit_immutable(contents)
    return run / "metadata" / "representative_windows" / "selected_windows.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = plan_run(args.run)
    except (OSError, ValueError, RepresentativeWindowError) as exc:
        raise SystemExit(str(exc)) from exc
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
