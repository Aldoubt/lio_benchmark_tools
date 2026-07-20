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
    return LaunchDescription([DeclareLaunchArgument("params_file"), *nodes])
