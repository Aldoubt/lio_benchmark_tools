#!/usr/bin/env python3
"""Freeze an immutable MID360 dataset contract from an existing probe artifact."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.dataset_intake import freeze_dataset  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--lidar-topic", required=True)
    parser.add_argument("--imu-topic", required=True)
    parser.add_argument(
        "--profile",
        required=True,
        choices=("mid360-internal", "mid360-user-extrinsic", "unknown-lidar-imu"),
    )
    parser.add_argument(
        "--imu-angular-velocity-unit",
        required=True,
        choices=("rad_s", "unknown"),
    )
    parser.add_argument(
        "--imu-linear-acceleration-unit",
        required=True,
        choices=("m_s2", "g_like_raw", "unknown"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rotation-lidar-to-imu", nargs=9, type=float)
    parser.add_argument("--translation-lidar-to-imu", nargs=3, type=float)
    parser.add_argument("--calibration-source")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output = freeze_dataset(
            probe_path=args.probe,
            dataset_id=args.dataset_id,
            lidar_topic=args.lidar_topic,
            imu_topic=args.imu_topic,
            profile=args.profile,
            imu_angular_velocity_unit=args.imu_angular_velocity_unit,
            imu_linear_acceleration_unit=args.imu_linear_acceleration_unit,
            output_dir=args.output,
            rotation_lidar_to_imu=args.rotation_lidar_to_imu,
            translation_lidar_to_imu=args.translation_lidar_to_imu,
            calibration_source=args.calibration_source,
        )
    except (ValueError, FileExistsError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
