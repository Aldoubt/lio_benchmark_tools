cmake_minimum_required(VERSION 3.8)
project(lio_benchmark_adapters)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(livox_ros_driver2 REQUIRED)

add_executable(custommsg_to_pointcloud2 src/custommsg_to_pointcloud2.cpp)
target_compile_features(custommsg_to_pointcloud2 PRIVATE cxx_std_17)
ament_target_dependencies(custommsg_to_pointcloud2 rclcpp sensor_msgs livox_ros_driver2)

install(TARGETS custommsg_to_pointcloud2 DESTINATION lib/${PROJECT_NAME})
ament_package()
