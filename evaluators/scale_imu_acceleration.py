#!/usr/bin/env python3
"""把 Livox 驱动输出的 g 单位加速度转换为 SI m/s²，其他字段原样保留。"""
from __future__ import annotations

import copy

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import Imu


class ImuScaler(Node):
    def __init__(self) -> None:
        super().__init__("lio_eval_imu_scaler")
        self.declare_parameter("input_topic", "/livox/imu")
        self.declare_parameter("output_topic", "/lio_eval/imu_si")
        self.declare_parameter("acceleration_scale", 9.80665)
        self.declare_parameter("output_frame_id", "livox_imu")
        input_topic = str(self.get_parameter("input_topic").value)
        output_topic = str(self.get_parameter("output_topic").value)
        self.scale = float(self.get_parameter("acceleration_scale").value)
        self.output_frame_id = str(self.get_parameter("output_frame_id").value)
        output_qos = QoSProfile(depth=1000, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
        self.publisher = self.create_publisher(Imu, output_topic, output_qos)
        input_qos = QoSProfile(depth=1000, reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE)
        self.subscription = self.create_subscription(Imu, input_topic, self.callback, input_qos)
        self.count = 0

    def callback(self, source: Imu) -> None:
        output = copy.deepcopy(source)
        output.header.frame_id = self.output_frame_id
        output.linear_acceleration.x *= self.scale
        output.linear_acceleration.y *= self.scale
        output.linear_acceleration.z *= self.scale
        # covariance scales quadratically when it is populated (all-zero means unknown in this bag).
        if any(output.linear_acceleration_covariance):
            output.linear_acceleration_covariance = [value * self.scale * self.scale for value in output.linear_acceleration_covariance]
        self.publisher.publish(output)
        self.count += 1
        if self.count % 10000 == 0:
            self.get_logger().info(f"已转换 {self.count} 条 IMU，acceleration_scale={self.scale}")


def main() -> None:
    rclpy.init()
    node = ImuScaler()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
