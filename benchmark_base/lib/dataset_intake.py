#!/usr/bin/env python3
"""Pure, fail-closed freezing of dataset contracts from probe evidence."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shutil
from typing import Any, Iterable
import uuid

from benchmark_base.lib.bag_probe import (
    build_bag_identity,
    sha256_file,
    validate_probe_payload,
)
from benchmark_base.lib.calibration import RigidTransform
from benchmark_base.lib.registry import validate_dataset_record


INTAKE_SCHEMA = "lio_benchmark_dataset_intake/v1"
PROFILES = frozenset({"mid360-internal", "mid360-user-extrinsic", "unknown-lidar-imu"})
ANGULAR_VELOCITY_UNITS = frozenset({"rad_s", "unknown"})
LINEAR_ACCELERATION_UNITS = frozenset({"m_s2", "g_like_raw", "unknown"})
LIVOX_CUSTOM_TYPE = "livox_ros_driver2/msg/CustomMsg"
IMU_TYPE = "sensor_msgs/msg/Imu"
INTERNAL_ROTATION = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0)
INTERNAL_TRANSLATION = (-0.011, -0.02329, 0.04412)
MANUFACTURER_IMU_ORIGIN_IN_LIDAR = (0.011, 0.02329, -0.04412)


def _load_probe(path: Path) -> tuple[Path, dict[str, Any]]:
    probe_path = path.expanduser().resolve()
    if not probe_path.is_file():
        raise ValueError(f"probe file does not exist: {probe_path}")
    try:
        payload = json.loads(probe_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid probe JSON: {probe_path}: {exc}") from exc
    validate_probe_payload(payload)
    return probe_path, payload


def _validate_dataset_id(dataset_id: str) -> str:
    value = str(dataset_id).strip()
    if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("dataset id may contain only letters, numbers, underscore and hyphen")
    return value


def _validate_units(angular: str, linear: str) -> tuple[str, str]:
    angular_value = str(angular).strip()
    linear_value = str(linear).strip()
    if angular_value not in ANGULAR_VELOCITY_UNITS:
        raise ValueError(
            "angular velocity unit must be one of: "
            + ", ".join(sorted(ANGULAR_VELOCITY_UNITS))
        )
    if linear_value not in LINEAR_ACCELERATION_UNITS:
        raise ValueError(
            "linear acceleration unit must be one of: "
            + ", ".join(sorted(LINEAR_ACCELERATION_UNITS))
        )
    return angular_value, linear_value


def _topic_map(probe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = probe.get("topics", [])
    if not isinstance(rows, list):
        raise ValueError("probe topics must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("name"):
            raise ValueError("probe topic record is invalid")
        name = str(row["name"])
        if name in result:
            raise ValueError(f"duplicate topic evidence in probe: {name}")
        result[name] = row
    return result


def _validate_selected_topics(
    probe: dict[str, Any], lidar_topic: str, imu_topic: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if lidar_topic == imu_topic:
        raise ValueError("selected LiDAR and IMU topics must be different")
    topics = _topic_map(probe)
    if lidar_topic not in topics:
        raise ValueError(f"selected LiDAR topic is absent from probe: {lidar_topic}")
    if imu_topic not in topics:
        raise ValueError(f"selected IMU topic is absent from probe: {imu_topic}")
    lidar = topics[lidar_topic]
    imu = topics[imu_topic]

    lidar_type = str(lidar.get("type", ""))
    if lidar_type == "sensor_msgs/msg/PointCloud2":
        raise ValueError(
            "PointCloud2 point-time semantics are unresolved in MID360 Bag Intake V1"
        )
    if lidar_type != LIVOX_CUSTOM_TYPE:
        raise ValueError(f"selected LiDAR type is unsupported in V1: {lidar_type or '<missing>'}")
    if str(imu.get("type", "")) != IMU_TYPE:
        raise ValueError(
            f"selected IMU type must be {IMU_TYPE}, got {imu.get('type', '<missing>')}"
        )

    for role, row in (("LiDAR", lidar), ("IMU", imu)):
        if int(row.get("message_count", 0)) <= 0:
            raise ValueError(f"selected {role} topic contains no messages")
        if int(row.get("recorded_time_reversal_count", 0)) != 0:
            raise ValueError(f"selected {role} recorded time is non-monotonic")
        if row.get("header_first_s") is None or row.get("header_last_s") is None:
            raise ValueError(f"selected {role} header time evidence is unavailable")
        if int(row.get("header_time_reversal_count", 0)) != 0:
            raise ValueError(f"selected {role} header time is non-monotonic")
    return lidar, imu


def _as_finite(values: Iterable[float], expected: int, name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != expected:
        raise ValueError(f"{name} must have {expected} values")
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{name} must contain only finite values")
    return result


def _rotation_plausible(rotation: tuple[float, ...], tolerance: float = 1e-3) -> None:
    rows = (
        rotation[0:3],
        rotation[3:6],
        rotation[6:9],
    )
    for row in rows:
        norm = math.sqrt(sum(value * value for value in row))
        if abs(norm - 1.0) > tolerance:
            raise ValueError("rotation rows must have unit norm within 1e-3")
    for left, right in ((rows[0], rows[1]), (rows[0], rows[2]), (rows[1], rows[2])):
        dot = sum(a * b for a, b in zip(left, right))
        if abs(dot) > tolerance:
            raise ValueError("rotation rows must be orthogonal within 1e-3")
    r = rotation
    determinant = (
        r[0] * (r[4] * r[8] - r[5] * r[7])
        - r[1] * (r[3] * r[8] - r[5] * r[6])
        + r[2] * (r[3] * r[7] - r[4] * r[6])
    )
    if abs(determinant - 1.0) > tolerance:
        raise ValueError("rotation determinant must be +1 within 1e-3")


def _calibration_for_profile(
    profile: str,
    *,
    rotation_lidar_to_imu: Iterable[float] | None,
    translation_lidar_to_imu: Iterable[float] | None,
    calibration_source: str | None,
) -> dict[str, Any]:
    if profile not in PROFILES:
        raise ValueError("profile must be one of: " + ", ".join(sorted(PROFILES)))

    common = {
        "canonical_convention": "LIDAR_TO_IMU",
        "canonical_equation": "p_I = R_IL * p_L + t_IL",
        "online_extrinsic_estimation": False,
    }
    if profile == "mid360-internal":
        if any(value is not None for value in (rotation_lidar_to_imu, translation_lidar_to_imu, calibration_source)):
            raise ValueError("mid360-internal does not accept user extrinsic arguments")
        return {
            **common,
            "rotation_lidar_to_imu_row_major": list(INTERNAL_ROTATION),
            "translation_lidar_to_imu_m": list(INTERNAL_TRANSLATION),
            "manufacturer_imu_origin_in_lidar_m": list(MANUFACTURER_IMU_ORIGIN_IN_LIDAR),
            "status": "MANUFACTURER_SPEC",
            "source_type": "MANUFACTURER_SPEC",
            "sensor_model": "Livox Mid-360",
            "sensor_model_source": "EXPLICIT_PROFILE_SELECTION",
            "imu_relation": "INTERNAL_IMU",
            "source": "Livox Mid-360 manufacturer internal LiDAR/IMU geometry; selected explicitly by intake profile",
        }

    if profile == "mid360-user-extrinsic":
        if rotation_lidar_to_imu is None or translation_lidar_to_imu is None:
            raise ValueError("mid360-user-extrinsic requires rotation and translation")
        source = str(calibration_source or "").strip()
        if not source:
            raise ValueError("mid360-user-extrinsic requires calibration source")
        rotation = _as_finite(rotation_lidar_to_imu, 9, "rotation")
        translation = _as_finite(translation_lidar_to_imu, 3, "translation")
        transform = RigidTransform(rotation=rotation, translation=translation)
        _rotation_plausible(transform.rotation)
        return {
            **common,
            "rotation_lidar_to_imu_row_major": list(transform.rotation),
            "translation_lidar_to_imu_m": list(transform.translation),
            "status": "USER_PROVIDED",
            "source_type": "USER_PROVIDED",
            "sensor_model": "Livox Mid-360",
            "sensor_model_source": "EXPLICIT_PROFILE_SELECTION",
            "imu_relation": "USER_SPECIFIED",
            "source": source,
        }

    if any(value is not None for value in (rotation_lidar_to_imu, translation_lidar_to_imu, calibration_source)):
        raise ValueError("unknown-lidar-imu does not accept extrinsic values")
    return {
        **common,
        "rotation_lidar_to_imu_row_major": list(INTERNAL_ROTATION),
        "translation_lidar_to_imu_m": [0.0, 0.0, 0.0],
        "status": "UNKNOWN",
        "source_type": "UNKNOWN",
        "sensor_model": "UNKNOWN",
        "sensor_model_source": "UNRESOLVED",
        "imu_relation": "UNKNOWN",
        "source": "UNRESOLVED",
        "placeholder_transform": True,
        "usable_for_lidar_imu_benchmark": False,
    }


def _build_dataset(
    *,
    probe: dict[str, Any],
    probe_sha: str,
    current_identity: dict[str, Any],
    dataset_id: str,
    lidar_topic: str,
    imu_topic: str,
    lidar: dict[str, Any],
    imu_topic_evidence: dict[str, Any],
    profile: str,
    imu_angular_velocity_unit: str,
    imu_linear_acceleration_unit: str,
    rotation_lidar_to_imu: Iterable[float] | None,
    translation_lidar_to_imu: Iterable[float] | None,
    calibration_source: str | None,
) -> dict[str, Any]:
    calibration = _calibration_for_profile(
        profile,
        rotation_lidar_to_imu=rotation_lidar_to_imu,
        translation_lidar_to_imu=translation_lidar_to_imu,
        calibration_source=calibration_source,
    )
    bag_dir = str(Path(str(probe["source"]["bag_dir"])).expanduser().resolve())
    dataset = {
        "schema_version": 2,
        "dataset_id": dataset_id,
        "bag_dir": bag_dir,
        "sha256": current_identity["bag_content_sha256"],
        "environment": "UNSPECIFIED",
        "acquisition": {
            "platform": "UNSPECIFIED",
            "route_type": "UNSPECIFIED",
            "camera_present": False,
        },
        "topics": {
            "lidar": lidar_topic,
            "imu": imu_topic,
            "camera": None,
        },
        "types": {
            "lidar": str(lidar["type"]),
            "imu": str(imu_topic_evidence["type"]),
            "camera": None,
        },
        "timestamp": {
            "point_time_field": "offset_time",
            "point_time_unit": "ns_relative_to_timebase",
            "scan_time_field": "header.stamp",
            "timebase_field": "timebase",
            "verified_from_bag": True,
            "header_time_audit": "FULL_SELECTED_TOPIC",
        },
        "imu": {
            "angular_velocity_unit": imu_angular_velocity_unit,
            "linear_acceleration_unit": imu_linear_acceleration_unit,
            "unit_source": "EXPLICIT_USER_SELECTION",
            "frame_ids_observed": list(imu_topic_evidence.get("frame_ids", [])),
        },
        "calibration": calibration,
        "intake": {
            "schema": INTAKE_SCHEMA,
            "profile": profile,
            "inspection_sha256": probe_sha,
            "bag_content_sha256": current_identity["bag_content_sha256"],
            "selected_topics_source": "EXPLICIT_USER_SELECTION",
        },
    }
    validate_dataset_record(dataset, expected_id=dataset_id)
    return dataset


def freeze_dataset(
    *,
    probe_path: Path,
    dataset_id: str,
    lidar_topic: str,
    imu_topic: str,
    profile: str,
    imu_angular_velocity_unit: str,
    imu_linear_acceleration_unit: str,
    output_dir: Path,
    rotation_lidar_to_imu: Iterable[float] | None = None,
    translation_lidar_to_imu: Iterable[float] | None = None,
    calibration_source: str | None = None,
) -> Path:
    """Freeze an immutable dataset directory from prior read-only probe evidence."""
    probe_file, probe = _load_probe(probe_path)
    dataset_id = _validate_dataset_id(dataset_id)
    angular_unit, linear_unit = _validate_units(
        imu_angular_velocity_unit, imu_linear_acceleration_unit
    )
    lidar, imu_evidence = _validate_selected_topics(probe, lidar_topic, imu_topic)

    bag_dir = Path(str(probe["source"]["bag_dir"])).expanduser().resolve()
    identity_path = Path(str(probe["bag_identity"].get("bag_dir", ""))).expanduser().resolve()
    if identity_path != bag_dir:
        raise ValueError("probe source bag path and bag identity path disagree")
    current_identity = build_bag_identity(bag_dir)
    probed_sha = str(probe["bag_identity"].get("bag_content_sha256", ""))
    if current_identity["bag_content_sha256"] != probed_sha:
        raise ValueError(
            "bag identity mismatch: source bag content changed after probe evidence was created"
        )

    # Validate profile arguments before creating any staging directory.
    _calibration_for_profile(
        profile,
        rotation_lidar_to_imu=rotation_lidar_to_imu,
        translation_lidar_to_imu=translation_lidar_to_imu,
        calibration_source=calibration_source,
    )

    output = output_dir.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}.staging-{uuid.uuid4().hex}"
    probe_sha = sha256_file(probe_file)

    try:
        staging.mkdir(parents=False, exist_ok=False)
        shutil.copyfile(probe_file, staging / "inspection.json")
        dataset = _build_dataset(
            probe=probe,
            probe_sha=probe_sha,
            current_identity=current_identity,
            dataset_id=dataset_id,
            lidar_topic=lidar_topic,
            imu_topic=imu_topic,
            lidar=lidar,
            imu_topic_evidence=imu_evidence,
            profile=profile,
            imu_angular_velocity_unit=angular_unit,
            imu_linear_acceleration_unit=linear_unit,
            rotation_lidar_to_imu=rotation_lidar_to_imu,
            translation_lidar_to_imu=translation_lidar_to_imu,
            calibration_source=calibration_source,
        )
        (staging / "dataset.json").write_text(
            json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if {path.name for path in staging.iterdir()} != {"inspection.json", "dataset.json"}:
            raise RuntimeError("dataset staging directory contains unexpected artifacts")
        if output.exists():
            raise FileExistsError(f"output directory appeared during freeze: {output}")
        staging.replace(output)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return output
