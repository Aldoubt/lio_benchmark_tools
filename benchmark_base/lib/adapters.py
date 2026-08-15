#!/usr/bin/env python3
"""Generic adapter lifecycle contracts for benchmark algorithms.

The core distinguishes an upstream algorithm failure from conditions that make
an algorithm impossible or scientifically invalid to run. This module is ROS-
independent; shell/ROS execution remains in algorithm-specific adapters.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from benchmark_base.lib.calibration import resolve_algorithm_extrinsic


BLOCKING_STATUSES = frozenset({
    "FAIL_IMPLEMENTATION",
    "BLOCKED_ENVIRONMENT",
    "BLOCKED_DEPENDENCY",
    "BLOCKED_INPUT",
    "BLOCKED_CALIBRATION",
})


@dataclass(frozen=True)
class AdapterStatus:
    algorithm_id: str
    status: str
    runnable: bool
    diagnostic_only: bool
    reasons: tuple[str, ...]
    checks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm_id": self.algorithm_id,
            "status": self.status,
            "runnable": self.runnable,
            "diagnostic_only": self.diagnostic_only,
            "reasons": list(self.reasons),
            "checks": self.checks,
        }


@dataclass(frozen=True)
class PreparedAdapter:
    algorithm_id: str
    generated_config_dir: Path
    preflight: AdapterStatus
    generated_calibration: Path | None


@dataclass(frozen=True)
class CollectionReport:
    algorithm_id: str
    raw_output_dir: Path
    outputs: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm_id": self.algorithm_id,
            "raw_output_dir": str(self.raw_output_dir),
            "outputs": self.outputs,
        }


def _algorithm(manifest: dict[str, Any], algorithm_id: str) -> dict[str, Any]:
    algorithms = manifest.get("algorithms", {})
    if not isinstance(algorithms, dict) or algorithm_id not in algorithms:
        raise ValueError(f"algorithm is not selected in manifest: {algorithm_id}")
    record = algorithms[algorithm_id]
    if not isinstance(record, dict):
        raise ValueError(f"algorithm manifest entry must be an object: {algorithm_id}")
    return record


def _source_path(manifest: dict[str, Any], algorithm: dict[str, Any]) -> Path | None:
    source = algorithm.get("source", {})
    hint = source.get("local_path_hint") if isinstance(source, dict) else None
    if not hint:
        return None
    path = Path(str(hint)).expanduser()
    if not path.is_absolute():
        path = Path(str(manifest.get("workspace", "."))).expanduser() / path
    return path.resolve()


def _runner_path(algorithm: dict[str, Any], benchmark_root: str | Path) -> Path | None:
    runner = algorithm.get("runner", {})
    adapter = runner.get("adapter") if isinstance(runner, dict) else None
    if not adapter:
        return None
    path = Path(str(adapter)).expanduser()
    if not path.is_absolute():
        path = Path(benchmark_root) / path
    return path.resolve()


def preflight_algorithm(
    manifest: dict[str, Any],
    algorithm_id: str,
    *,
    benchmark_root: str | Path,
    allow_diagnostic_calibration: bool = False,
    runtime_env: Mapping[str, str] | None = None,
) -> AdapterStatus:
    algorithm = _algorithm(manifest, algorithm_id)
    dataset = manifest.get("dataset", {})
    if not isinstance(dataset, dict):
        raise ValueError("manifest dataset must be an object")

    checks: dict[str, Any] = {}
    reasons: list[str] = []
    source = _source_path(manifest, algorithm)
    checks["source_path"] = str(source) if source else None
    checks["source_exists"] = bool(source and source.is_dir())
    if source is not None and not source.is_dir():
        reasons.append(f"source repository/path does not exist: {source}")
        return AdapterStatus(algorithm_id, "BLOCKED_ENVIRONMENT", False, False, tuple(reasons), checks)

    runner = _runner_path(algorithm, benchmark_root)
    checks["runner_path"] = str(runner) if runner else None
    checks["runner_exists"] = bool(runner and runner.is_file())
    if runner is None or not runner.is_file():
        reasons.append(f"runner adapter is missing: {runner or '<not declared>'}")
        return AdapterStatus(algorithm_id, "FAIL_IMPLEMENTATION", False, False, tuple(reasons), checks)

    environment_requirements = algorithm.get("environment_requirements", {})
    environment_requirements = (
        environment_requirements if isinstance(environment_requirements, dict) else {}
    )
    supported_ros_distros = [
        str(value) for value in environment_requirements.get("ros_distros", [])
    ]
    env = os.environ if runtime_env is None else runtime_env
    active_ros_distro = str(env.get("ROS_DISTRO", ""))
    checks["ros_distro"] = active_ros_distro or None
    checks["supported_ros_distros"] = supported_ros_distros
    if supported_ros_distros and active_ros_distro not in supported_ros_distros:
        reasons.append(
            f"ROS_DISTRO {active_ros_distro or '<unset>'} is unsupported; expected one of: "
            + ", ".join(supported_ros_distros)
        )
        return AdapterStatus(
            algorithm_id,
            "BLOCKED_ENVIRONMENT",
            False,
            False,
            tuple(reasons),
            checks,
        )

    required_modalities = list(algorithm.get("required_modalities", []))
    topics = dataset.get("topics", {}) if isinstance(dataset.get("topics", {}), dict) else {}
    missing_modalities: list[str] = []
    for modality in required_modalities:
        if modality in ("lidar", "imu", "camera") and not topics.get(modality):
            missing_modalities.append(modality)
    checks["required_modalities"] = required_modalities
    checks["missing_modalities"] = missing_modalities
    if missing_modalities:
        reasons.append("dataset is missing required input topics: " + ", ".join(missing_modalities))
        return AdapterStatus(algorithm_id, "BLOCKED_INPUT", False, False, tuple(reasons), checks)

    requirements = algorithm.get("input_requirements", {})
    capability_requirements = (
        requirements.get("dataset_capabilities", {}) if isinstance(requirements, dict) else {}
    )
    capabilities = dataset.get("capabilities", {}) if isinstance(dataset.get("capabilities", {}), dict) else {}
    missing_capabilities = [
        key for key, expected in capability_requirements.items() if capabilities.get(key) != expected
    ]
    checks["required_dataset_capabilities"] = capability_requirements
    checks["missing_dataset_capabilities"] = missing_capabilities
    if missing_capabilities:
        reasons.append(
            "dataset does not satisfy required capabilities: " + ", ".join(missing_capabilities)
        )
        return AdapterStatus(algorithm_id, "BLOCKED_INPUT", False, False, tuple(reasons), checks)

    uses_imu = "imu" in required_modalities or bool(algorithm.get("sensor_profile", {}).get("imu"))
    convention = str(algorithm.get("extrinsic_convention", "NONE" if not uses_imu else "")).upper()
    checks["extrinsic_convention"] = convention or None
    if uses_imu and not convention:
        reasons.append("LiDAR-IMU adapter has no explicit extrinsic_convention")
        return AdapterStatus(algorithm_id, "FAIL_IMPLEMENTATION", False, False, tuple(reasons), checks)

    if convention != "NONE":
        calibration = dataset.get("calibration", {})
        status = str(calibration.get("status", "UNKNOWN")).upper() if isinstance(calibration, dict) else "UNKNOWN"
        checks["calibration_status"] = status
        if status not in {"CONFIRMED", "VERIFIED"}:
            reasons.append(f"canonical LiDAR-IMU calibration is not confirmed: {status}")
            return AdapterStatus(
                algorithm_id,
                "BLOCKED_CALIBRATION",
                bool(allow_diagnostic_calibration),
                True,
                tuple(reasons),
                checks,
            )
        try:
            resolved = resolve_algorithm_extrinsic(dataset, algorithm)
        except ValueError as exc:
            reasons.append(str(exc))
            return AdapterStatus(algorithm_id, "FAIL_IMPLEMENTATION", False, False, tuple(reasons), checks)
        checks["resolved_extrinsic_convention"] = resolved["convention"]
    else:
        checks["calibration_status"] = "NOT_REQUIRED"

    return AdapterStatus(algorithm_id, "PASS", True, False, (), checks)


def prepare_algorithm(
    run_dir: str | Path,
    manifest: dict[str, Any],
    algorithm_id: str,
    *,
    benchmark_root: str | Path,
    allow_diagnostic_calibration: bool = False,
) -> PreparedAdapter:
    run = Path(run_dir)
    algorithm = _algorithm(manifest, algorithm_id)
    preflight = preflight_algorithm(
        manifest,
        algorithm_id,
        benchmark_root=benchmark_root,
        allow_diagnostic_calibration=allow_diagnostic_calibration,
    )
    if not preflight.runnable:
        raise ValueError(f"adapter preflight blocked {algorithm_id}: {preflight.status}: {'; '.join(preflight.reasons)}")

    generated = run / "configs" / "generated" / algorithm_id
    generated.mkdir(parents=True, exist_ok=True)
    calibration_path: Path | None = None
    convention = str(algorithm.get("extrinsic_convention", "NONE")).upper()
    if convention != "NONE":
        resolved = resolve_algorithm_extrinsic(manifest["dataset"], algorithm)
        calibration_path = generated / "calibration.json"
        calibration_path.write_text(json.dumps(resolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    status_path = run / "metadata" / "algorithms" / algorithm_id / "preflight.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(preflight.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return PreparedAdapter(algorithm_id, generated, preflight, calibration_path)


def collect_algorithm(
    run_dir: str | Path,
    manifest: dict[str, Any],
    algorithm_id: str,
) -> CollectionReport:
    run = Path(run_dir)
    algorithm = _algorithm(manifest, algorithm_id)
    raw = run / "raw" / algorithm_id
    outputs: dict[str, dict[str, Any]] = {}
    declarations = algorithm.get("topics", {}).get("outputs", {})
    if not isinstance(declarations, dict):
        declarations = {}
    for name, declaration in declarations.items():
        if not declaration:
            outputs[name] = {"status": "NOT_PROVIDED", "declaration": declaration}
            continue
        value = str(declaration)
        if value.startswith("/"):
            outputs[name] = {"status": "TOPIC_DECLARED", "declaration": value}
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = raw / candidate
        outputs[name] = {
            "status": "AVAILABLE" if candidate.exists() else "MISSING",
            "declaration": value,
            "path": str(candidate),
        }
    report = CollectionReport(algorithm_id, raw, outputs)
    path = run / "metadata" / "algorithms" / algorithm_id / "collection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
