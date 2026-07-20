"""Headless LIO-SAM launch for reproducible offline runs."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    params = LaunchConfiguration("params_file")
    nodes = [
        Node(package="lio_sam", executable=executable, name=executable, parameters=[params, {"use_sim_time": True}], output="screen")
        for executable in (
            "lio_sam_imuPreintegration", "lio_sam_imageProjection",
            "lio_sam_featureExtraction", "lio_sam_mapOptimization",
        )
    ]
    sensor_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="lio_sam_sensor_extrinsic",
        arguments=[
            "--x", "0.011", "--y", "0.02329", "--z", "-0.04412",
            "--qx", "0", "--qy", "0", "--qz", "0", "--qw", "1",
            "--frame-id", "livox_imu", "--child-frame-id", "livox_frame",
        ],
        output="screen",
    )
    return LaunchDescription([DeclareLaunchArgument("params_file"), sensor_tf, *nodes])
