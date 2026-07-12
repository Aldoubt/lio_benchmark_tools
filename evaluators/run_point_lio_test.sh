#!/usr/bin/env bash
set -eo pipefail

WORKSPACE=${WORKSPACE:-/home/yangxuan/ros2_ws}
BAG_DIR=${1:-"$WORKSPACE/date/mid360_init_state2"}
OUTPUT_DIR=${2:-"$WORKSPACE/date/output/point_lio"}
mkdir -p "$OUTPUT_DIR" "$OUTPUT_DIR/ros_logs"

source /opt/ros/humble/setup.bash
source "$WORKSPACE/install/setup.bash"
source "$WORKSPACE/date/install/point_dlio/setup.bash"
set -u
export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"

cleanup() { jobs -pr | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

python3 "$WORKSPACE/tools/lio_z_drift_evaluator/pointcloud2_to_livox_custom.py" >"$OUTPUT_DIR/converter.log" 2>&1 &
converter_pid=$!

ros2 run point_lio pointlio_mapping --ros-args \
  --params-file "$WORKSPACE/date/algorithms/point_lio_ros2/config/mid360.yaml" \
  -p common.lid_topic:=/lio_eval/livox_custom \
  -p publish.scan_publish_en:=false \
  -p publish.tf_send_en:=false \
  -p pcd_save.pcd_save_en:=false >"$OUTPUT_DIR/point_lio.log" 2>&1 &
lio_pid=$!
sleep 4

ros2 bag record -o "$OUTPUT_DIR/trajectory" /aft_mapped_to_init /path >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2
ros2 bag play "$BAG_DIR" --rate 1.0 >"$OUTPUT_DIR/play.log" 2>&1
sleep 4
kill -INT "$record_pid" 2>/dev/null || true
wait "$record_pid" || true
kill -INT "$lio_pid" "$converter_pid" 2>/dev/null || true
sleep 2

