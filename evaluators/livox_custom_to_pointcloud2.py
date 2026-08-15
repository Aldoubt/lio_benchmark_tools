#!/usr/bin/env python3
"""Republish Livox CustomMsg as PointCloud2 with per-point offset time preserved."""
from __future__ import annotations

import argparse

import numpy as np
import rclpy
from livox_ros_driver2.msg import CustomMsg
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2, PointField


class Converter(Node):
    def __init__(self, input_topic: str, output_topic: str) -> None:
        super().__init__("lio_benchmark_livox_custom_to_pointcloud2")
        self.publisher = self.create_publisher(PointCloud2, output_topic, qos_profile_sensor_data)
        self.subscription = self.create_subscription(CustomMsg, input_topic, self.callback, qos_profile_sensor_data)
        self.get_logger().info(f"{input_topic} -> {output_topic}; fields=x,y,z,t(offset_time uint32)")

    def callback(self, msg: CustomMsg) -> None:
        count = min(int(msg.point_num), len(msg.points))
        cloud = PointCloud2()
        cloud.header = msg.header
        cloud.height = 1
        cloud.width = count
        cloud.is_bigendian = False
        cloud.is_dense = False
        cloud.point_step = 16
        cloud.row_step = cloud.point_step * count
        cloud.fields = [
            PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
            PointField(name="t", offset=12, datatype=PointField.UINT32, count=1),
        ]
        records = np.empty(count, dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("t", "<u4")])
        if count:
            records["x"] = np.fromiter((p.x for p in msg.points[:count]), dtype=np.float32, count=count)
            records["y"] = np.fromiter((p.y for p in msg.points[:count]), dtype=np.float32, count=count)
            records["z"] = np.fromiter((p.z for p in msg.points[:count]), dtype=np.float32, count=count)
            records["t"] = np.fromiter((p.offset_time for p in msg.points[:count]), dtype=np.uint32, count=count)
        cloud.data = records.tobytes()
        self.publisher.publish(cloud)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-topic", default="/livox/lidar")
    parser.add_argument("--output-topic", default="/lio_benchmark/kiss_icp_points")
    args = parser.parse_args()
    rclpy.init()
    node = Converter(args.input_topic, args.output_topic)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
