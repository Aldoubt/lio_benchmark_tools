#!/usr/bin/env python3
"""Convert the project MID360 PointCloud2 layout to Livox CustomMsg without losing point time."""
from __future__ import annotations

import sys
from pathlib import Path

import rclpy
from livox_ros_driver2.msg import CustomMsg, CustomPoint
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.mid360_layout import (  # noqa: E402
    MID360_POINT_STEP,
    MID360_POINT_STRUCT,
    absolute_ns_float_to_uint64,
    offset_ns_uint32,
)


class Converter(Node):
    def __init__(self) -> None:
        super().__init__("pointcloud2_to_livox_custom")
        self.declare_parameter("input_topic", "/livox/lidar")
        self.declare_parameter("output_topic", "/lio_eval/livox_custom")
        input_topic = str(self.get_parameter("input_topic").value)
        output_topic = str(self.get_parameter("output_topic").value)
        self.publisher = self.create_publisher(CustomMsg, output_topic, qos_profile_sensor_data)
        self.subscription = self.create_subscription(PointCloud2, input_topic, self.callback, qos_profile_sensor_data)
        self.frames = 0

    def callback(self, cloud: PointCloud2) -> None:
        expected = {
            "x": (0, 7), "y": (4, 7), "z": (8, 7), "intensity": (12, 7),
            "tag": (16, 2), "line": (17, 2), "timestamp": (18, 8),
        }
        actual = {field.name: (field.offset, field.datatype) for field in cloud.fields}
        if any(actual.get(name) != spec for name, spec in expected.items()):
            self.get_logger().error(f"incompatible PointCloud2 fields: {actual}")
            return
        if cloud.is_bigendian or cloud.point_step < MID360_POINT_STEP:
            self.get_logger().error(
                f"unsupported byte layout: bigendian={cloud.is_bigendian}, point_step={cloud.point_step}"
            )
            return
        count = cloud.width * cloud.height
        if count == 0:
            return
        try:
            first_raw = MID360_POINT_STRUCT.unpack_from(cloud.data, 0)
            first_timestamp = absolute_ns_float_to_uint64(first_raw[6])
        except (ValueError, TypeError) as exc:
            self.get_logger().error(f"invalid first point timestamp: {exc}")
            return
        output = CustomMsg()
        output.header = cloud.header
        output.timebase = first_timestamp
        output.lidar_id = 0
        output.rsvd = [0, 0, 0]
        points: list[CustomPoint] = []
        append = points.append
        for index in range(count):
            x, y, z, intensity, tag, line, timestamp_float_ns = MID360_POINT_STRUCT.unpack_from(
                cloud.data, index * cloud.point_step
            )
            try:
                timestamp_ns = absolute_ns_float_to_uint64(timestamp_float_ns)
                offset = offset_ns_uint32(timestamp_ns, first_timestamp)
            except ValueError as exc:
                self.get_logger().error(f"invalid point timestamp: index={index}, error={exc}")
                return
            point = CustomPoint()
            point.offset_time = offset
            point.x, point.y, point.z = x, y, z
            point.reflectivity = max(0, min(255, round(intensity)))
            point.tag, point.line = tag, line
            append(point)
        output.points = points
        output.point_num = len(points)
        self.publisher.publish(output)
        self.frames += 1
        if self.frames % 250 == 0:
            self.get_logger().info(f"converted {self.frames} frames; current points={len(points)}")


def main() -> None:
    rclpy.init()
    node = Converter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
