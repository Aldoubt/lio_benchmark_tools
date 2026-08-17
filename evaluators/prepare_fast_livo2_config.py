#!/usr/bin/env python3
"""Generate a run-local FAST-LIVO2 config from frozen benchmark evidence."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_base.lib.calibration import CONFIRMED_CALIBRATION_STATUSES  # noqa: E402


TEMPLATE = ROOT / "benchmark_base/config/templates/fast_livo2_mid360.yaml.in"
TOKENS = (
    "@@LID_TOPIC@@",
    "@@IMU_TOPIC@@",
    "@@EXTRINSIC_T@@",
    "@@EXTRINSIC_R@@",
)


def _float_scalar(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("FAST-LIVO2 calibration contains non-finite values")
    # Benchmark parameters are human-audited provenance. Twelve significant
    # digits preserve the frozen values while avoiding binary-float expansion.
    text = f"{number:.12g}"
    if "." not in text and "e" not in text.lower():
        text += ".0"
    return text


def _vector(values: Iterable[float], expected: int, name: str) -> str:
    items = list(values)
    if len(items) != expected:
        raise ValueError(f"{name} must contain {expected} values")
    return "[" + ", ".join(_float_scalar(value) for value in items) + "]"


def generate(run: Path, output: Path) -> Path:
    run = run.resolve()
    output = output.resolve()
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    dataset = manifest.get("dataset", {})
    topics = dataset.get("topics", {}) if isinstance(dataset, dict) else {}
    lidar_topic = str(topics.get("lidar", "")).strip()
    imu_topic = str(topics.get("imu", "")).strip()
    if not lidar_topic or not imu_topic:
        raise ValueError("frozen dataset must provide LiDAR and IMU topics")

    calibration_path = run / "configs/generated/fast_livo2/calibration.json"
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if calibration.get("convention") != "LIDAR_TO_IMU":
        raise ValueError(
            f"FAST-LIVO2 requires LIDAR_TO_IMU, got {calibration.get('convention')}"
        )
    status = str(calibration.get("calibration_status", "UNKNOWN")).upper()
    if status not in CONFIRMED_CALIBRATION_STATUSES:
        raise ValueError(f"FAST-LIVO2 requires usable fixed calibration, got {status}")
    if calibration.get("diagnostic_only"):
        raise ValueError("FAST-LIVO2 canonical calibration must not be diagnostic-only")

    template = TEMPLATE.read_text(encoding="utf-8")
    for token in TOKENS:
        if template.count(token) != 1:
            raise ValueError(f"FAST-LIVO2 template must contain token exactly once: {token}")

    replacements = {
        "@@LID_TOPIC@@": lidar_topic,
        "@@IMU_TOPIC@@": imu_topic,
        "@@EXTRINSIC_T@@": _vector(calibration.get("translation_m", []), 3, "extrinsic_T"),
        "@@EXTRINSIC_R@@": _vector(calibration.get("rotation_row_major", []), 9, "extrinsic_R"),
    }
    text = template
    for token, value in replacements.items():
        text = text.replace(token, value)
    if "@@" in text:
        raise ValueError("FAST-LIVO2 template contains unresolved replacement token")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(output)

    metadata = {
        "schema_version": 1,
        "algorithm_id": "fast_livo2",
        "config": str(output),
        "template": str(TEMPLATE.resolve()),
        "lidar_topic": lidar_topic,
        "imu_topic": imu_topic,
        "canonical_convention": calibration.get("canonical_convention"),
        "canonical_equation": calibration.get("canonical_equation"),
        "effective_convention": calibration.get("convention"),
        "rotation_row_major": calibration.get("rotation_row_major"),
        "translation_m": calibration.get("translation_m"),
        "calibration_status": status,
        "calibration_source": calibration.get("calibration_source"),
        "calibration_source_type": calibration.get("calibration_source_type"),
        "sensor_model": calibration.get("sensor_model"),
        "imu_relation": calibration.get("imu_relation"),
        "online_extrinsic_estimation": False,
    }
    metadata_path = output.parent / "adapter_config_metadata.json"
    metadata_temp = metadata_path.with_name(metadata_path.name + ".tmp")
    metadata_temp.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metadata_temp.replace(metadata_path)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path = generate(args.run, args.output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
