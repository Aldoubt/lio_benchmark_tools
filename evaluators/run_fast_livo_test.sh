#!/usr/bin/env bash
set -eo pipefail

WORKSPACE=${WORKSPACE:-$PWD}
BAG_DIR=${1:-"$WORKSPACE/date/mid360_init_state2"}
OUTPUT_DIR=${2:-"$WORKSPACE/date/output"}
BAG_PLAY_RATE=${BAG_PLAY_RATE:-1.0}
mkdir -p "$OUTPUT_DIR"

source /opt/ros/humble/setup.bash
source "$WORKSPACE/install/setup.bash"
set -u
export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$ROS_LOG_DIR"
cleanup() { jobs -pr | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

ros2 launch agt_mapping fast_livo2_mapping.launch.py \
  start_lidar_self_filter:=false use_sim_time:=true save_pcd:=false \
  >"$OUTPUT_DIR/fast_livo.log" 2>&1 &
node_pid=$!
sleep 3
if ! kill -0 "$node_pid" 2>/dev/null || ! ros2 node list 2>/dev/null | grep -q '/fast_livo2_backend'; then
  echo "FAST-LIVO2 failed to start; see $OUTPUT_DIR/fast_livo.log" >&2
  exit 66
fi
ros2 bag record -o "$OUTPUT_DIR/fast_livo_trajectory" /aft_mapped_to_init /path >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2
if ! kill -0 "$record_pid" 2>/dev/null; then
  echo "trajectory recorder failed to start; see $OUTPUT_DIR/record.log" >&2
  exit 67
fi
ros2 bag play "$BAG_DIR" --rate "$BAG_PLAY_RATE" --clock 100.0 >"$OUTPUT_DIR/play.log" 2>&1
sleep 3
kill -INT "$record_pid" 2>/dev/null || true
if ! wait "$record_pid"; then
  echo "trajectory recorder exited with failure; see $OUTPUT_DIR/record.log" >&2
  exit 68
fi
kill -INT "$node_pid" 2>/dev/null || true
for _ in $(seq 1 30); do
  kill -0 "$node_pid" 2>/dev/null || break
  sleep 1
done
kill -TERM "$node_pid" 2>/dev/null || true
wait "$node_pid" || true
