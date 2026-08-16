#!/usr/bin/env bash
set -eo pipefail

WORKSPACE=${WORKSPACE:-$PWD}
BAG_DIR=${1:-"$WORKSPACE/date/mid360_init_state2"}
OUTPUT_DIR=${2:-"$WORKSPACE/date/output"}
BENCHMARK_RUN_DIR=${BENCHMARK_RUN_DIR:?BENCHMARK_RUN_DIR is required}
BENCHMARK_ROOT=${BENCHMARK_ROOT:?BENCHMARK_ROOT is required}
mkdir -p "$OUTPUT_DIR"

unset AMENT_PREFIX_PATH CMAKE_PREFIX_PATH COLCON_PREFIX_PATH COLCON_CURRENT_PREFIX \
  LD_LIBRARY_PATH PYTHONPATH ROS_PACKAGE_PATH
source /opt/ros/humble/setup.bash
source "$WORKSPACE/install/setup.bash"
eval "$(python3 "$BENCHMARK_ROOT/evaluators/emit_runtime_env.py" \
  --run "$BENCHMARK_RUN_DIR" --algorithm fast_livo2)"
export BENCHMARK_EXECUTION_RESOLUTION_METHOD BENCHMARK_RESOLVED_EXECUTABLE
export BENCHMARK_REPLAY_RATE BENCHMARK_REPLAY_START_OFFSET_S BENCHMARK_REPLAY_DURATION_S
export BAG_PLAY_RATE BAG_START_OFFSET BAG_DURATION
source "$BENCHMARK_ROOT/evaluators/source_runtime_overlays.sh"
set -u

export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$ROS_LOG_DIR"
cleanup() { jobs -pr | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

estimator_cmd=(
  ros2 launch agt_mapping fast_livo2_mapping.launch.py
  start_lidar_self_filter:=false use_sim_time:=true save_pcd:=false
)
command_json=$(python3 - "${estimator_cmd[@]}" <<'PY'
import json,sys
print(json.dumps(sys.argv[1:]))
PY
)
python3 "$BENCHMARK_ROOT/evaluators/freeze_runtime_identity.py" \
  --run "$BENCHMARK_RUN_DIR" \
  --algorithm fast_livo2 \
  --effective-command-json "$command_json"

"${estimator_cmd[@]}" >"$OUTPUT_DIR/fast_livo.log" 2>&1 &
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
    *) echo "FAST-LIVO2 bag replay failed with status $play_status" >&2; exit 69 ;;
  esac
else
  "${play_args[@]}" >"$OUTPUT_DIR/play.log" 2>&1
fi
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
