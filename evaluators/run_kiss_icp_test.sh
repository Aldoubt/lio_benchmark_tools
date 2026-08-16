#!/usr/bin/env bash
set -eo pipefail

WORKSPACE=${WORKSPACE:-$PWD}
BAG_DIR=${1:?usage: run_kiss_icp_test.sh BAG_DIR OUTPUT_DIR}
OUTPUT_DIR=${2:?usage: run_kiss_icp_test.sh BAG_DIR OUTPUT_DIR}
BENCHMARK_RUN_DIR=${BENCHMARK_RUN_DIR:?BENCHMARK_RUN_DIR is required}
BENCHMARK_ROOT=${BENCHMARK_ROOT:?BENCHMARK_ROOT is required}
mkdir -p "$OUTPUT_DIR"

source /opt/ros/humble/setup.bash
if [[ -f "$WORKSPACE/install/setup.bash" ]]; then
  source "$WORKSPACE/install/setup.bash"
fi

eval "$(python3 "$BENCHMARK_ROOT/evaluators/emit_runtime_env.py" \
  --run "$BENCHMARK_RUN_DIR" --algorithm kiss_icp)"
export BENCHMARK_EXECUTION_RESOLUTION_METHOD BENCHMARK_RESOLVED_EXECUTABLE
export BENCHMARK_REPLAY_RATE BENCHMARK_REPLAY_START_OFFSET_S BENCHMARK_REPLAY_DURATION_S
export BAG_PLAY_RATE BAG_START_OFFSET BAG_DURATION
set -u

if ! ros2 pkg prefix kiss_icp >/dev/null 2>&1; then
  echo "KISS-ICP ROS2 package 'kiss_icp' is not available in the sourced environment" >&2
  exit 65
fi

LIDAR_TOPIC=$(python3 - "$BENCHMARK_RUN_DIR/manifest.json" <<'PY'
import json,sys
m=json.load(open(sys.argv[1]))
print(m['dataset']['topics']['lidar'])
PY
)
LIDAR_TYPE=$(python3 - "$BENCHMARK_RUN_DIR/manifest.json" <<'PY'
import json,sys
m=json.load(open(sys.argv[1]))
print(m['dataset']['types']['lidar'])
PY
)
INPUT_TOPIC="$LIDAR_TOPIC"

cleanup() { jobs -pr | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM
export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$ROS_LOG_DIR"

if [[ "$LIDAR_TYPE" == "livox_ros_driver2/msg/CustomMsg" ]]; then
  INPUT_TOPIC=/lio_benchmark/kiss_icp_points
  python3 "$BENCHMARK_ROOT/evaluators/livox_custom_to_pointcloud2.py" \
    --input-topic "$LIDAR_TOPIC" --output-topic "$INPUT_TOPIC" \
    >"$OUTPUT_DIR/converter.log" 2>&1 &
  converter_pid=$!
  sleep 2
  if ! kill -0 "$converter_pid" 2>/dev/null; then
    echo "Livox CustomMsg -> PointCloud2 converter failed; see $OUTPUT_DIR/converter.log" >&2
    exit 66
  fi
elif [[ "$LIDAR_TYPE" != "sensor_msgs/msg/PointCloud2" ]]; then
  echo "KISS-ICP adapter does not support LiDAR type: $LIDAR_TYPE" >&2
  exit 67
fi

estimator_cmd=(
  ros2 launch kiss_icp odometry.launch.py
  topic:="$INPUT_TOPIC" visualize:=false use_sim_time:=true
)
command_json=$(python3 - "${estimator_cmd[@]}" <<'PY'
import json,sys
print(json.dumps(sys.argv[1:]))
PY
)
python3 "$BENCHMARK_ROOT/evaluators/freeze_runtime_identity.py" \
  --run "$BENCHMARK_RUN_DIR" \
  --algorithm kiss_icp \
  --effective-command-json "$command_json"

"${estimator_cmd[@]}" >"$OUTPUT_DIR/kiss_icp.log" 2>&1 &
node_pid=$!
sleep 3
if ! kill -0 "$node_pid" 2>/dev/null || ! ros2 node list 2>/dev/null | grep -q '/kiss_icp_node'; then
  echo "KISS-ICP failed to start; see $OUTPUT_DIR/kiss_icp.log" >&2
  exit 68
fi

ros2 bag record -o "$OUTPUT_DIR/kiss_icp_outputs" \
  /kiss/odometry /kiss/frame /kiss/keypoints /kiss/local_map \
  >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2
if ! kill -0 "$record_pid" 2>/dev/null; then
  echo "KISS-ICP recorder failed to start; see $OUTPUT_DIR/record.log" >&2
  exit 69
fi

play_args=(
  ros2 bag play "$BAG_DIR"
  --rate "$BENCHMARK_REPLAY_RATE"
  --clock 100.0
  --start-offset "$BENCHMARK_REPLAY_START_OFFSET_S"
)
if [[ -n "$BENCHMARK_REPLAY_DURATION_S" ]]; then
  set +e
  timeout --signal=INT --kill-after=5s "${BENCHMARK_REPLAY_DURATION_S}s" \
    "${play_args[@]}" >"$OUTPUT_DIR/play.log" 2>&1
  play_status=$?
  set -e
  case "$play_status" in
    0|124|130) ;;
    *) echo "KISS-ICP bag replay failed with status $play_status" >&2; exit 71 ;;
  esac
else
  "${play_args[@]}" >"$OUTPUT_DIR/play.log" 2>&1
fi
sleep 2
kill -INT "$record_pid" 2>/dev/null || true
if ! wait "$record_pid"; then
  echo "KISS-ICP recorder exited with failure; see $OUTPUT_DIR/record.log" >&2
  exit 70
fi
kill -INT "$node_pid" 2>/dev/null || true
for _ in $(seq 1 20); do
  kill -0 "$node_pid" 2>/dev/null || break
  sleep 1
done
kill -TERM "$node_pid" 2>/dev/null || true
wait "$node_pid" || true
