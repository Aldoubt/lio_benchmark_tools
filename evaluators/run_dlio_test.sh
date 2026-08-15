#!/usr/bin/env bash
set -eo pipefail

WORKSPACE=${WORKSPACE:-/home/yangxuan/ros2_ws}
BAG_DIR=${1:-"$WORKSPACE/date/mid360_init_state2"}
OUTPUT_DIR=${2:-"$WORKSPACE/date/output/dlio"}
BAG_PLAY_RATE=${BAG_PLAY_RATE:-1.0}
mkdir -p "$OUTPUT_DIR" "$OUTPUT_DIR/ros_logs"
source /opt/ros/humble/setup.bash
source "$WORKSPACE/install/setup.bash"
source "$WORKSPACE/date/install/point_dlio/setup.bash"
export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
set -u
cleanup() { jobs -pr | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

python3 "$WORKSPACE/tools/lio_z_drift_evaluator/scale_imu_acceleration.py" >"$OUTPUT_DIR/imu_scaler.log" 2>&1 &
scaler_pid=$!
ros2 run direct_lidar_inertial_odometry dlio_odom_node --ros-args \
  --params-file "$WORKSPACE/date/dlio_test/dlio.yaml" --params-file "$WORKSPACE/date/dlio_test/params.yaml" \
  -r pointcloud:=/livox/lidar -r imu:=/lio_eval/imu_si -r odom:=/dlio/odom_node/odom \
  -r pose:=/dlio/odom_node/pose -r path:=/dlio/odom_node/path -r kf_pose:=/dlio/odom_node/keyframes \
  -r kf_cloud:=/dlio/odom_node/pointcloud/keyframe -r deskewed:=/dlio/odom_node/pointcloud/deskewed \
  >"$OUTPUT_DIR/dlio.log" 2>&1 &
dlio_pid=$!
sleep 5
ros2 bag record -o "$OUTPUT_DIR/trajectory" /dlio/odom_node/odom /dlio/odom_node/path >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2
ros2 bag play "$BAG_DIR" --rate "$BAG_PLAY_RATE" >"$OUTPUT_DIR/play.log" 2>&1
sleep 10
kill -INT "$record_pid" 2>/dev/null || true
wait "$record_pid" || true
kill -INT "$dlio_pid" "$scaler_pid" 2>/dev/null || true
sleep 3
