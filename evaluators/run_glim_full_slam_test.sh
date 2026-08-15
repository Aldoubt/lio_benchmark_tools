#!/usr/bin/env bash
set -eo pipefail

WORKSPACE=${WORKSPACE:-/home/yangxuan/ros2_ws}
BAG_DIR=${1:-"$WORKSPACE/date/mid360_init_state2"}
OUTPUT_DIR=${2:-"$WORKSPACE/date/output/glim_full_slam"}
CONFIG_DIR=${3:-"$WORKSPACE/date/glim_full_slam_test/config"}
BAG_PLAY_RATE=${BAG_PLAY_RATE:-1.0}
mkdir -p "$OUTPUT_DIR" "$OUTPUT_DIR/ros_logs" "$OUTPUT_DIR/dump"
source /opt/ros/humble/setup.bash
export CMAKE_PREFIX_PATH="$WORKSPACE/date/install/glim_deps:${CMAKE_PREFIX_PATH:-}"
export LD_LIBRARY_PATH="$WORKSPACE/date/install/glim_deps/lib:$WORKSPACE/date/install/glim_ros2/glim_ros/lib:${LD_LIBRARY_PATH:-}"
source "$WORKSPACE/date/install/glim_ros2/setup.bash"
export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
set -u
cleanup() { jobs -pr | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

ros2 run glim_ros glim_rosnode --ros-args -p config_path:="$CONFIG_DIR" -p dump_path:="$OUTPUT_DIR/dump" >"$OUTPUT_DIR/glim.log" 2>&1 &
glim_pid=$!
sleep 5
ros2 bag record -o "$OUTPUT_DIR/trajectory" /glim_ros/odom /glim_ros/odom_scanend /glim_ros/odom_corrected /glim_ros/odom_scanend_corrected /glim_ros/lidar_odom /glim_ros/lidar_odom_corrected >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2
ros2 bag play "$BAG_DIR" --rate "$BAG_PLAY_RATE" >"$OUTPUT_DIR/play.log" 2>&1
sleep 30
kill -INT "$record_pid" 2>/dev/null || true
wait "$record_pid" || true
kill -INT "$glim_pid" 2>/dev/null || true
for _ in $(seq 1 120); do kill -0 "$glim_pid" 2>/dev/null || break; sleep 1; done
kill -TERM "$glim_pid" 2>/dev/null || true
wait "$glim_pid" || true
