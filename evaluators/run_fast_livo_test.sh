#!/usr/bin/env bash
set -eo pipefail

WORKSPACE=${WORKSPACE:-/home/yangxuan/ros2_ws}
BAG_DIR=${1:-"$WORKSPACE/date/mid360_init_state2"}
OUTPUT_DIR=${2:-"$WORKSPACE/date/output"}
mkdir -p "$OUTPUT_DIR"

source /opt/ros/humble/setup.bash
source "$WORKSPACE/install/setup.bash"
set -u
export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$ROS_LOG_DIR"

cleanup() {
  jobs -pr | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

ros2 launch fast_livo mapping_mid360_lio.launch.py use_rviz:=false >"$OUTPUT_DIR/fast_livo.log" 2>&1 &
node_pid=$!
sleep 3
ros2 bag record -o "$OUTPUT_DIR/fast_livo_trajectory" /aft_mapped_to_init /path >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2
ros2 bag play "$BAG_DIR" --rate 2.0 >"$OUTPUT_DIR/play.log" 2>&1
sleep 3
kill -INT "$record_pid" 2>/dev/null || true
wait "$record_pid" || true
kill -INT "$node_pid" 2>/dev/null || true
wait "$node_pid" || true
