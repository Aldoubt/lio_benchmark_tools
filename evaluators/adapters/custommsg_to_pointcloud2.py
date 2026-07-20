#!/usr/bin/env python3
"""Convert Livox CustomMsg to a common, timestamped PointCloud2 contract."""
from __future__ import annotations

import json
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np

POINT_STRUCT = struct.Struct("<ffffHf")
INPUT_DTYPE = np.dtype([
    ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
    ("reflectivity", "u1"), ("tag", "u1"), ("line", "u1"),
    ("offset_time", "<u4"),
])
POINT_DTYPE = np.dtype({
    "names": ["x", "y", "z", "intensity", "ring", "time"],
    "formats": ["<f4", "<f4", "<f4", "<f4", "<u2", "<f4"],
    "offsets": [0, 4, 8, 12, 16, 18],
    "itemsize": POINT_STRUCT.size,
})
FIELDS = (
    ("x", 0, 7), ("y", 4, 7), ("z", 8, 7), ("intensity", 12, 7),
    ("ring", 16, 4), ("time", 18, 7),
)


@dataclass
class Validation:
    frames: int = 0
    input_points: int = 0
    output_points: int = 0
    invalid_tag_points: int = 0
    non_finite_points: int = 0
    input_time_backtracks: int = 0
    output_time_backtracks: int = 0
    time_min_s: float | None = None
    time_max_s: float | None = None
    ring_counts: Counter[int] = field(default_factory=Counter)

    def as_dict(self) -> dict:
        dropped = self.input_points - self.output_points
        return {
            "frames": self.frames, "input_points": self.input_points, "output_points": self.output_points,
            "missing_fields": 0, "invalid_tag_points": self.invalid_tag_points,
            "non_finite_points": self.non_finite_points, "invalid_time_points": 0,
            "input_time_backtracks": self.input_time_backtracks, "output_time_backtracks": self.output_time_backtracks,
            "time_min_s": self.time_min_s, "time_max_s": self.time_max_s,
            "ring_min": min(self.ring_counts) if self.ring_counts else None,
            "ring_max": max(self.ring_counts) if self.ring_counts else None,
            "ring_counts": {str(k): v for k, v in sorted(self.ring_counts.items())},
            "dropped_points": dropped, "dropped_ratio": dropped / self.input_points if self.input_points else 0.0,
            "time_semantics": "FLOAT32 seconds relative to CustomMsg header/timebase",
            "ring_semantics": "exact uint8 CustomPoint.line value widened to uint16; no synthetic rings",
        }


def convert_points(points: Sequence, sort_by_time: bool = True, validation: Validation | None = None) -> bytes:
    stats = validation or Validation()
    stats.frames += 1
    count = len(points)
    stats.input_points += count
    source = np.fromiter(
        ((point.x, point.y, point.z, point.reflectivity, point.tag, point.line, point.offset_time) for point in points),
        dtype=INPUT_DTYPE,
        count=count,
    )
    offsets, tags = source["offset_time"], source["tag"]
    x, y, z = source["x"], source["y"], source["z"]
    stats.input_time_backtracks += int(np.count_nonzero(offsets[1:] < offsets[:-1]))
    tag_valid = np.isin(np.bitwise_and(tags, 0x30), (0x00, 0x10))
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    stats.invalid_tag_points += int(np.count_nonzero(~tag_valid))
    stats.non_finite_points += int(np.count_nonzero(tag_valid & ~finite))
    selected = np.flatnonzero(tag_valid & finite)
    if sort_by_time and selected.size:
        selected = selected[np.argsort(offsets[selected], kind="stable")]
    records = np.empty(selected.size, dtype=POINT_DTYPE)
    records["x"] = x[selected]
    records["y"] = y[selected]
    records["z"] = z[selected]
    records["intensity"] = source["reflectivity"][selected]
    records["ring"] = source["line"][selected]
    records["time"] = offsets[selected].astype(np.float32) * np.float32(1e-9)
    stats.output_points += int(selected.size)
    stats.output_time_backtracks += int(np.count_nonzero(records["time"][1:] < records["time"][:-1]))
    if selected.size:
        minimum, maximum = float(records["time"].min()), float(records["time"].max())
        stats.time_min_s = minimum if stats.time_min_s is None else min(stats.time_min_s, minimum)
        stats.time_max_s = maximum if stats.time_max_s is None else max(stats.time_max_s, maximum)
        rings, ring_counts = np.unique(records["ring"], return_counts=True)
        stats.ring_counts.update({int(ring): int(value) for ring, value in zip(rings, ring_counts)})
    return records.tobytes()


def main() -> None:
    import rclpy
    from livox_ros_driver2.msg import CustomMsg
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2, PointField

    class Converter(Node):
        def __init__(self) -> None:
            super().__init__("lio_benchmark_custommsg_to_pointcloud2")
            self.declare_parameter("input_topic", "/agt/sensors/lidar/custom")
            self.declare_parameter("output_topic", "/lio_benchmark/points")
            self.declare_parameter("sort_by_time", True)
            self.declare_parameter("metrics_path", "")
            self.stats = Validation()
            self.output_topic = str(self.get_parameter("output_topic").value)
            self.sort_by_time = bool(self.get_parameter("sort_by_time").value)
            self.metrics_path = str(self.get_parameter("metrics_path").value)
            self.pub = self.create_publisher(PointCloud2, self.output_topic, qos_profile_sensor_data)
            input_qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE)
            self.sub = self.create_subscription(CustomMsg, str(self.get_parameter("input_topic").value), self.callback, input_qos)

        def callback(self, source: CustomMsg) -> None:
            output = PointCloud2()
            output.header = source.header
            output.height = 1
            output.width = 0
            output.is_bigendian = False
            output.is_dense = True
            output.fields = [PointField(name=n, offset=o, datatype=d, count=1) for n, o, d in FIELDS]
            output.point_step = POINT_STRUCT.size
            output.data = convert_points(source.points, self.sort_by_time, self.stats)
            output.width = len(output.data) // output.point_step
            output.row_step = output.width * output.point_step
            self.pub.publish(output)

        def save(self) -> None:
            if self.metrics_path:
                path = Path(self.metrics_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(self.stats.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rclpy.init()
    node = Converter()
    try:
        rclpy.spin(node)
    finally:
        node.save(); node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()


if __name__ == "__main__":
    main()
