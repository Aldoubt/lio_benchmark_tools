#!/usr/bin/env python3
"""将本数据集的 MID360 PointCloud2 无损时间字段转换为 Livox CustomMsg。"""
from __future__ import annotations

import struct

import rclpy
from livox_ros_driver2.msg import CustomMsg, CustomPoint
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2


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
        expected = {"x": (0, 7), "y": (4, 7), "z": (8, 7), "intensity": (12, 7),
                    "tag": (16, 2), "line": (17, 2), "timestamp": (18, 8)}
        actual = {field.name: (field.offset, field.datatype) for field in cloud.fields}
        if any(actual.get(name) != spec for name, spec in expected.items()):
            self.get_logger().error(f"不兼容的 PointCloud2 字段: {actual}")
            return
        if cloud.is_bigendian or cloud.point_step < 26:
            self.get_logger().error(f"不支持的字节布局: bigendian={cloud.is_bigendian}, point_step={cloud.point_step}")
            return

        count = cloud.width * cloud.height
        if count == 0:
            return
        unpack = struct.Struct("<ffffBBQ").unpack_from
        first_timestamp = unpack(cloud.data, 0)[6]
        output = CustomMsg()
        output.header = cloud.header
        output.timebase = first_timestamp
        output.lidar_id = 0
        output.rsvd = [0, 0, 0]
        points: list[CustomPoint] = []
        points_append = points.append
        for index in range(count):
            x, y, z, intensity, tag, line, timestamp = unpack(cloud.data, index * cloud.point_step)
            offset = timestamp - first_timestamp
            if offset < 0 or offset > 0xFFFFFFFF:
                self.get_logger().error(f"逐点时间偏移越界: index={index}, offset_ns={offset}")
                return
            point = CustomPoint()
            point.offset_time = offset
            point.x, point.y, point.z = x, y, z
            point.reflectivity = max(0, min(255, round(intensity)))
            point.tag, point.line = tag, line
            points_append(point)
        output.points = points
        output.point_num = len(points)
        self.publisher.publish(output)
        self.frames += 1
        if self.frames % 250 == 0:
            self.get_logger().info(f"已转换 {self.frames} 帧，当前点数 {len(points)}")


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
