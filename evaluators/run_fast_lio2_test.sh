#!/usr/bin/env bash
set -eo pipefail

WORKSPACE=${WORKSPACE:-$PWD}
BAG_DIR=${1:?usage: run_fast_lio2_test.sh BAG_DIR OUTPUT_DIR}
OUTPUT_DIR=${2:?usage: run_fast_lio2_test.sh BAG_DIR OUTPUT_DIR}
BAG_PLAY_RATE=${BAG_PLAY_RATE:-1.0}
BENCHMARK_RUN_DIR=${BENCHMARK_RUN_DIR:?BENCHMARK_RUN_DIR is required}
BENCHMARK_ROOT=${BENCHMARK_ROOT:?BENCHMARK_ROOT is required}
BENCHMARK_GENERATED_CONFIG_DIR=${BENCHMARK_GENERATED_CONFIG_DIR:?BENCHMARK_GENERATED_CONFIG_DIR is required}
BENCHMARK_COLLECT_NATIVE_MAP=${BENCHMARK_COLLECT_NATIVE_MAP:-0}
mkdir -p "$OUTPUT_DIR" "$BENCHMARK_GENERATED_CONFIG_DIR"

source /opt/ros/humble/setup.bash
if [[ -f "$WORKSPACE/install/setup.bash" ]]; then
  source "$WORKSPACE/install/setup.bash"
fi
set -u

if ! ros2 pkg prefix fast_lio >/dev/null 2>&1; then
  echo "FAST-LIO2 ROS2 package 'fast_lio' is not available in the sourced environment" >&2
  exit 65
fi

CONFIG="$BENCHMARK_GENERATED_CONFIG_DIR/benchmark.yaml"
prepare_args=(
  "$BENCHMARK_ROOT/evaluators/prepare_fast_lio2_config.py"
  --run "$BENCHMARK_RUN_DIR"
  --output "$CONFIG"
)
if [[ "$BENCHMARK_COLLECT_NATIVE_MAP" == "1" ]]; then
  prepare_args+=(--collect-native-map)
fi
python3 "${prepare_args[@]}"

export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$ROS_LOG_DIR"
cleanup() { jobs -pr | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

ros2 launch fast_lio mapping.launch.py \
  config_path:="$BENCHMARK_GENERATED_CONFIG_DIR" \
  config_file:=benchmark.yaml \
  rviz:=false use_sim_time:=true \
  >"$OUTPUT_DIR/fast_lio2.log" 2>&1 &
node_pid=$!
sleep 3
if ! kill -0 "$node_pid" 2>/dev/null || ! ros2 node list 2>/dev/null | grep -q '/laser_mapping'; then
  echo "FAST-LIO2 failed to start; see $OUTPUT_DIR/fast_lio2.log" >&2
  exit 66
fi

record_topics=(/Odometry /path /cloud_registered /cloud_registered_body)
if [[ "$BENCHMARK_COLLECT_NATIVE_MAP" == "1" ]]; then
  record_topics+=(/Laser_map)
fi
ros2 bag record -o "$OUTPUT_DIR/fast_lio2_outputs" "${record_topics[@]}" \
  >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2
if ! kill -0 "$record_pid" 2>/dev/null; then
  echo "FAST-LIO2 recorder failed to start; see $OUTPUT_DIR/record.log" >&2
  exit 67
fi

ros2 bag play "$BAG_DIR" --rate "$BAG_PLAY_RATE" --clock 100.0 \
  >"$OUTPUT_DIR/play.log" 2>&1
sleep 2

if [[ "$BENCHMARK_COLLECT_NATIVE_MAP" == "1" ]]; then
  if ! ros2 service call /map_save std_srvs/srv/Trigger '{}' \
    >"$OUTPUT_DIR/map_save.log" 2>&1; then
    echo "FAST-LIO2 native map save service failed; see $OUTPUT_DIR/map_save.log" >&2
  fi
fi

kill -INT "$record_pid" 2>/dev/null || true
if ! wait "$record_pid"; then
  echo "FAST-LIO2 recorder exited with failure; see $OUTPUT_DIR/record.log" >&2
  exit 68
fi
kill -INT "$node_pid" 2>/dev/null || true
for _ in $(seq 1 20); do
  kill -0 "$node_pid" 2>/dev/null || break
  sleep 1
done
kill -TERM "$node_pid" 2>/dev/null || true
wait "$node_pid" || true

if [[ "$BENCHMARK_COLLECT_NATIVE_MAP" == "1" ]]; then
  native="$BENCHMARK_GENERATED_CONFIG_DIR/native_map.pcd"
  if [[ -f "$native" ]]; then
    cp -f "$native" "$OUTPUT_DIR/native_map.pcd"
  fi
fi
