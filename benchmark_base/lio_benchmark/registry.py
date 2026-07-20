"""Canonical algorithm taxonomy and comparison-group rules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlgorithmSpec:
    name: str
    label: str
    group: str
    mode: str
    sensor_inputs: tuple[str, ...]
    requires_si_imu: bool = False


ALGORITHMS = {
    item.name: item
    for item in (
        AlgorithmSpec("kiss_icp", "KISS-ICP", "lidar_only_odometry", "odometry", ("lidar",)),
        AlgorithmSpec("mola_lo", "MOLA-LO", "lidar_only_odometry", "odometry", ("lidar",)),
        AlgorithmSpec("mola_lio", "MOLA-LIO", "lidar_imu_odometry", "odometry", ("lidar", "imu"), True),
        AlgorithmSpec("fast_livo2", "FAST-LIVO2", "lidar_imu_odometry", "odometry", ("lidar", "imu")),
        AlgorithmSpec("point_lio", "Point-LIO", "lidar_imu_odometry", "odometry", ("lidar", "imu")),
        AlgorithmSpec("dlio", "DLIO", "lidar_imu_odometry", "odometry", ("lidar", "imu"), True),
        AlgorithmSpec("glim_odometry", "GLIM odometry", "lidar_imu_odometry", "odometry", ("lidar", "imu"), True),
        AlgorithmSpec("glim_full_slam", "GLIM full SLAM", "full_slam", "full_slam", ("lidar", "imu"), True),
        AlgorithmSpec("lio_sam_no_loop", "LIO-SAM (loop off)", "full_slam", "full_slam", ("lidar", "imu"), True),
        AlgorithmSpec("lio_sam_loop", "LIO-SAM (loop on)", "full_slam", "full_slam", ("lidar", "imu"), True),
    )
}


def validate_registry_entry(name: str, config: dict) -> list[str]:
    errors: list[str] = []
    spec = ALGORITHMS.get(name)
    if spec is None:
        return [f"未知算法: {name}"]
    for key, expected in (("group", spec.group), ("mode", spec.mode)):
        if config.get(key) != expected:
            errors.append(f"algorithm {name}.{key} 必须为 {expected}")
    if tuple(config.get("sensor_inputs", ())) != spec.sensor_inputs:
        errors.append(f"algorithm {name}.sensor_inputs 必须为 {list(spec.sensor_inputs)}")
    return errors


def comparison_groups(names: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for name in names:
        spec = ALGORITHMS[name]
        groups.setdefault(spec.group, []).append(name)
    return groups
