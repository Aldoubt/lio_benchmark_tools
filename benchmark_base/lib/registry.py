#!/usr/bin/env python3
"""Dataset and algorithm registry loading for LIO Benchmark Tools V2."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from benchmark_base.lib.algorithm_roles import (
    ADAPTER_STATUSES,
    ALGORITHM_TIERS,
    EVALUATION_ROLES,
    SENSOR_PROFILE_KEYS,
)


class RegistryError(ValueError):
    """Raised when a registry record is missing or violates the V2 contract."""


CORE_BASELINES = (
    "fast_livo2",
    "fast_lio2",
    "point_lio",
    "dlio",
    "lio_sam",
    "glim_odometry",
    "glim_full_slam",
    "leg_kilo",
    "kiss_icp",
)
RESEARCH_BASELINES = ("faster_lio", "slict")
LEGACY_BASELINES = ("leg_kilo2_lidar_imu",)
# Backward-compatible name used by existing V2 tests and callers.
FIXED_BASELINES = CORE_BASELINES


class Registry:
    """Read-only registry facade.

    ``root`` points at ``benchmark_base/registry``. Runtime path existence is
    intentionally not checked here because tracked registry records may be
    portable templates whose bag/source paths are machine-local.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        default = Path(__file__).resolve().parents[1] / "registry"
        self.root = Path(root).resolve() if root is not None else default
        self.algorithm_dir = self.root / "algorithms"
        self.dataset_dir = self.root / "datasets"

    def list_algorithms(self) -> tuple[str, ...]:
        return self._list_ids(self.algorithm_dir)

    def list_datasets(self) -> tuple[str, ...]:
        return self._list_ids(self.dataset_dir)

    def load_algorithm(self, algorithm_id: str) -> dict[str, Any]:
        record = self._load_record(self.algorithm_dir, algorithm_id)
        self._validate_algorithm(record, algorithm_id)
        return record

    def load_dataset(self, dataset_id: str) -> dict[str, Any]:
        record = self._load_record(self.dataset_dir, dataset_id)
        self._validate_dataset(record, dataset_id)
        return record

    @staticmethod
    def _list_ids(directory: Path) -> tuple[str, ...]:
        if not directory.is_dir():
            return ()
        return tuple(sorted(path.stem for path in directory.glob("*.json") if path.is_file()))

    @staticmethod
    def _load_record(directory: Path, record_id: str) -> dict[str, Any]:
        if not record_id or any(char in record_id for char in ("/", "\\", "..")):
            raise RegistryError(f"invalid registry id: {record_id!r}")
        path = directory / f"{record_id}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RegistryError(f"registry record not found: {record_id}") from exc
        except json.JSONDecodeError as exc:
            raise RegistryError(f"invalid JSON in {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise RegistryError(f"registry record must be an object: {path}")
        return value

    @staticmethod
    def _require_keys(record: dict[str, Any], keys: Iterable[str], kind: str) -> None:
        missing = [key for key in keys if record.get(key) in (None, "")]
        if missing:
            raise RegistryError(f"{kind} record missing required keys: {', '.join(missing)}")

    @classmethod
    def _validate_algorithm(cls, record: dict[str, Any], expected_id: str) -> None:
        cls._require_keys(
            record,
            (
                "schema_version",
                "algorithm_id",
                "display_name",
                "mode",
                "tier",
                "family_id",
                "family",
                "evaluation_roles",
                "sensor_profile",
                "algorithm_generation",
                "adapter_status",
                "required_modalities",
                "source",
                "runner",
                "topics",
            ),
            "algorithm",
        )
        if record["schema_version"] != 2:
            raise RegistryError("algorithm schema_version must be 2")
        if record["algorithm_id"] != expected_id:
            raise RegistryError(
                f"algorithm_id mismatch: file={expected_id} record={record['algorithm_id']}"
            )
        if record["mode"] not in ("odometry", "full_slam"):
            raise RegistryError(f"unsupported algorithm mode: {record['mode']}")
        if record["tier"] not in ALGORITHM_TIERS:
            raise RegistryError(f"unsupported algorithm tier: {record['tier']}")
        if not isinstance(record["family"], list) or not record["family"]:
            raise RegistryError("algorithm family must be a non-empty list")
        if not isinstance(record["evaluation_roles"], list) or not record["evaluation_roles"]:
            raise RegistryError("algorithm evaluation_roles must be a non-empty list")
        unknown_roles = set(record["evaluation_roles"]) - EVALUATION_ROLES
        if unknown_roles:
            raise RegistryError(f"unsupported evaluation roles: {sorted(unknown_roles)}")
        sensor_profile = record["sensor_profile"]
        if not isinstance(sensor_profile, dict):
            raise RegistryError("algorithm sensor_profile must be an object")
        if set(sensor_profile) != set(SENSOR_PROFILE_KEYS):
            raise RegistryError(
                "algorithm sensor_profile must contain exactly: " + ", ".join(SENSOR_PROFILE_KEYS)
            )
        if not all(isinstance(value, bool) for value in sensor_profile.values()):
            raise RegistryError("algorithm sensor_profile values must be booleans")
        if not sensor_profile["lidar"]:
            raise RegistryError("algorithm sensor_profile.lidar must be true")
        if record["adapter_status"] not in ADAPTER_STATUSES:
            raise RegistryError(f"unsupported adapter status: {record['adapter_status']}")
        if not isinstance(record["required_modalities"], list) or not record["required_modalities"]:
            raise RegistryError("required_modalities must be a non-empty list")
        if not isinstance(record.get("optional_modalities", []), list):
            raise RegistryError("optional_modalities must be a list")
        source = record["source"]
        if not isinstance(source, dict) or not source.get("repository"):
            raise RegistryError("algorithm source.repository is required")
        runner = record["runner"]
        if not isinstance(runner, dict) or not runner.get("adapter"):
            raise RegistryError("algorithm runner.adapter is required")
        topics = record["topics"]
        if not isinstance(topics, dict) or not isinstance(topics.get("inputs"), dict):
            raise RegistryError("algorithm topics.inputs object is required")
        if not isinstance(topics.get("outputs"), dict):
            raise RegistryError("algorithm topics.outputs object is required")

    @classmethod
    def _validate_dataset(cls, record: dict[str, Any], expected_id: str) -> None:
        cls._require_keys(
            record,
            (
                "schema_version",
                "dataset_id",
                "bag_dir",
                "environment",
                "acquisition",
                "topics",
                "types",
                "timestamp",
                "calibration",
            ),
            "dataset",
        )
        if record["schema_version"] != 2:
            raise RegistryError("dataset schema_version must be 2")
        if record["dataset_id"] != expected_id:
            raise RegistryError(
                f"dataset_id mismatch: file={expected_id} record={record['dataset_id']}"
            )
        topics = record["topics"]
        if not isinstance(topics, dict) or not topics.get("lidar") or not topics.get("imu"):
            raise RegistryError("dataset topics.lidar and topics.imu are required")
        types = record["types"]
        if not isinstance(types, dict) or not types.get("lidar") or not types.get("imu"):
            raise RegistryError("dataset types.lidar and types.imu are required")
        timestamp = record["timestamp"]
        if not isinstance(timestamp, dict) or not timestamp.get("point_time_field"):
            raise RegistryError("dataset timestamp.point_time_field is required")
        if not timestamp.get("point_time_unit"):
            raise RegistryError("dataset timestamp.point_time_unit is required")
        calibration = record["calibration"]
        if not isinstance(calibration, dict):
            raise RegistryError("dataset calibration must be an object")
        if len(calibration.get("rotation_lidar_to_imu_row_major", [])) != 9:
            raise RegistryError("dataset calibration rotation must have 9 values")
        if len(calibration.get("translation_lidar_to_imu_m", [])) != 3:
            raise RegistryError("dataset calibration translation must have 3 values")


def validate_fixed_baselines(registry: Registry | None = None) -> None:
    active = registry or Registry()
    missing = [item for item in FIXED_BASELINES if item not in active.list_algorithms()]
    if missing:
        raise RegistryError(f"fixed baseline registry entries missing: {', '.join(missing)}")
    for item in FIXED_BASELINES:
        active.load_algorithm(item)
