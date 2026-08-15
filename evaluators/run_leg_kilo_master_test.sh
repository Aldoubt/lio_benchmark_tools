#!/usr/bin/env bash
set -eo pipefail

WORKSPACE=${WORKSPACE:-$PWD}
BAG_DIR=${1:?usage: run_leg_kilo_master_test.sh BAG_DIR OUTPUT_DIR}
OUTPUT_DIR=${2:?usage: run_leg_kilo_master_test.sh BAG_DIR OUTPUT_DIR}
BAG_PLAY_RATE=${BAG_PLAY_RATE:-1.0}
BENCHMARK_RUN_DIR=${BENCHMARK_RUN_DIR:?BENCHMARK_RUN_DIR is required}
BENCHMARK_ROOT=${BENCHMARK_ROOT:?BENCHMARK_ROOT is required}
BENCHMARK_GENERATED_CONFIG_DIR=${BENCHMARK_GENERATED_CONFIG_DIR:?BENCHMARK_GENERATED_CONFIG_DIR is required}
LEG_KILO_SOURCE=${LEG_KILO_SOURCE:-$WORKSPACE/algorithms/Leg-KILO}
mkdir -p "$OUTPUT_DIR" "$BENCHMARK_GENERATED_CONFIG_DIR"

source /opt/ros/humble/setup.bash
if [[ -f "$WORKSPACE/install/setup.bash" ]]; then
  source "$WORKSPACE/install/setup.bash"
fi
if [[ -f "$LEG_KILO_SOURCE/install/setup.bash" ]]; then
  source "$LEG_KILO_SOURCE/install/setup.bash"
fi
set -u

if ! ros2 pkg prefix legkilo >/dev/null 2>&1; then
  echo "Leg-KILO ROS2 package 'legkilo' is not available in the sourced environment" >&2
  exit 65
fi
if [[ ! -f "$LEG_KILO_SOURCE/legkilo/config/m3dgr_mid360.yaml" ]]; then
  echo "Leg-KILO current-master source/template not found: $LEG_KILO_SOURCE" >&2
  exit 66
fi

CONFIG="$BENCHMARK_GENERATED_CONFIG_DIR/benchmark.yaml"
python3 "$BENCHMARK_ROOT/evaluators/prepare_leg_kilo_config.py" \
  --run "$BENCHMARK_RUN_DIR" \
  --source "$LEG_KILO_SOURCE" \
  --output "$CONFIG"

RUNTIME_RESULT_PATH=$(python3 - "$BENCHMARK_GENERATED_CONFIG_DIR/adapter_config_metadata.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['upstream_runtime_result_path'])
PY
)

export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$ROS_LOG_DIR"
cleanup() { jobs -pr | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

node_cmd=(ros2 run legkilo legkilo_node "--config_file=$CONFIG")
if [[ -z "${DISPLAY:-}" ]]; then
  if command -v xvfb-run >/dev/null 2>&1; then
    node_cmd=(xvfb-run -a "${node_cmd[@]}")
  else
    echo "Leg-KILO current master creates its viewer at startup; DISPLAY is unset and xvfb-run is unavailable" >&2
    exit 67
  fi
fi

(
  cd "$LEG_KILO_SOURCE"
  "${node_cmd[@]}"
) >"$OUTPUT_DIR/leg_kilo.log" 2>&1 &
node_pid=$!
sleep 4
if ! kill -0 "$node_pid" 2>/dev/null || ! ros2 node list 2>/dev/null | grep -q '/legkilo/legkilo'; then
  echo "Leg-KILO failed to start; see $OUTPUT_DIR/leg_kilo.log" >&2
  exit 68
fi

ros2 bag record -o "$OUTPUT_DIR/leg_kilo_outputs" \
  /Odometry /path /cloud_registered /cloud_registered_body \
  >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2
if ! kill -0 "$record_pid" 2>/dev/null; then
  echo "Leg-KILO recorder failed to start; see $OUTPUT_DIR/record.log" >&2
  exit 69
fi

ros2 bag play "$BAG_DIR" --rate "$BAG_PLAY_RATE" --clock 100.0 \
  >"$OUTPUT_DIR/play.log" 2>&1
sleep 3

kill -INT "$record_pid" 2>/dev/null || true
if ! wait "$record_pid"; then
  echo "Leg-KILO recorder exited with failure; see $OUTPUT_DIR/record.log" >&2
  exit 70
fi
kill -INT "$node_pid" 2>/dev/null || true
for _ in $(seq 1 30); do
  kill -0 "$node_pid" 2>/dev/null || break
  sleep 1
done
kill -TERM "$node_pid" 2>/dev/null || true
wait "$node_pid" || true

if [[ -d "$RUNTIME_RESULT_PATH" ]]; then
  mkdir -p "$OUTPUT_DIR/leg_kilo_runtime"
  cp -a "$RUNTIME_RESULT_PATH"/. "$OUTPUT_DIR/leg_kilo_runtime/"
else
  echo "Leg-KILO runtime result directory was not produced: $RUNTIME_RESULT_PATH" >&2
fi
