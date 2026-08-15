#!/usr/bin/env bash
set -eo pipefail

WORKSPACE=${WORKSPACE:-$PWD}
BAG_DIR=${1:?usage: run_lio_sam_test.sh BAG_DIR OUTPUT_DIR}
OUTPUT_DIR=${2:?usage: run_lio_sam_test.sh BAG_DIR OUTPUT_DIR}
BAG_PLAY_RATE=${BAG_PLAY_RATE:-1.0}
BENCHMARK_RUN_DIR=${BENCHMARK_RUN_DIR:?BENCHMARK_RUN_DIR is required}
BENCHMARK_ROOT=${BENCHMARK_ROOT:?BENCHMARK_ROOT is required}
BENCHMARK_GENERATED_CONFIG_DIR=${BENCHMARK_GENERATED_CONFIG_DIR:?BENCHMARK_GENERATED_CONFIG_DIR is required}
LIO_SAM_WS=${LIO_SAM_WS:-$WORKSPACE/algorithms/LIO-SAM_MID360_ROS2_PKG/ros2}
LIO_SAM_SOURCE=${LIO_SAM_SOURCE:-$LIO_SAM_WS/src/LIO-SAM_MID360_ROS2}
mkdir -p "$OUTPUT_DIR" "$BENCHMARK_GENERATED_CONFIG_DIR"

source /opt/ros/humble/setup.bash
if [[ -f "$WORKSPACE/install/setup.bash" ]]; then
  source "$WORKSPACE/install/setup.bash"
fi
if [[ -f "$LIO_SAM_WS/install/setup.bash" ]]; then
  source "$LIO_SAM_WS/install/setup.bash"
fi
set -u

if ! ros2 pkg prefix lio_sam >/dev/null 2>&1; then
  echo "LIO-SAM ROS2 package 'lio_sam' is not available in the sourced environment" >&2
  exit 65
fi
if [[ ! -f "$LIO_SAM_SOURCE/config/params.yaml" ]]; then
  echo "LIO-SAM MID360 ROS2 source/template not found: $LIO_SAM_SOURCE" >&2
  exit 66
fi

CONFIG="$BENCHMARK_GENERATED_CONFIG_DIR/benchmark.yaml"
python3 "$BENCHMARK_ROOT/evaluators/prepare_lio_sam_config.py" \
  --run "$BENCHMARK_RUN_DIR" \
  --source "$LIO_SAM_SOURCE" \
  --output "$CONFIG"

export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$ROS_LOG_DIR"
cleanup() { jobs -pr | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

nodes=(
  lio_sam_imuPreintegration
  lio_sam_imageProjection
  lio_sam_featureExtraction
  lio_sam_mapOptimization
)
for executable in "${nodes[@]}"; do
  ros2 run lio_sam "$executable" --ros-args --params-file "$CONFIG" \
    >"$OUTPUT_DIR/${executable}.log" 2>&1 &
  sleep 1
done
sleep 3
for node_name in lio_sam_imuPreintegration lio_sam_imageProjection lio_sam_featureExtraction lio_sam_mapOptimization; do
  if ! ros2 node list 2>/dev/null | grep -q "/${node_name}"; then
    echo "LIO-SAM node failed to start: $node_name" >&2
    exit 67
  fi
done

ros2 bag record -o "$OUTPUT_DIR/lio_sam_outputs" \
  /lio_sam/mapping/odometry \
  /lio_sam/mapping/odometry_incremental \
  /lio_sam/mapping/path \
  /lio_sam/mapping/trajectory \
  /lio_sam/mapping/map_global \
  /lio_sam/mapping/cloud_registered \
  /lio_sam/mapping/cloud_registered_raw \
  /odometry/imu /odometry/imu_incremental \
  >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2
if ! kill -0 "$record_pid" 2>/dev/null; then
  echo "LIO-SAM recorder failed to start; see $OUTPUT_DIR/record.log" >&2
  exit 68
fi

ros2 bag play "$BAG_DIR" --rate "$BAG_PLAY_RATE" --clock 100.0 \
  >"$OUTPUT_DIR/play.log" 2>&1
sleep 3

safe_run_id=$(basename "$BENCHMARK_RUN_DIR" | tr -c 'A-Za-z0-9_.-' '_')
native_rel="/.cache/lio_benchmark/${safe_run_id}/lio_sam_native"
native_abs="$HOME${native_rel}"
mkdir -p "$(dirname "$native_abs")"
if ros2 service call /lio_sam/save_map lio_sam/srv/SaveMap \
  "{resolution: 0.2, destination: '$native_rel'}" \
  >"$OUTPUT_DIR/save_map.log" 2>&1; then
  if [[ -f "$native_abs/GlobalMap.pcd" ]]; then
    cp -f "$native_abs/GlobalMap.pcd" "$OUTPUT_DIR/native_map.pcd"
    cp -f "$native_abs/trajectory.pcd" "$OUTPUT_DIR/native_trajectory.pcd" 2>/dev/null || true
    cp -f "$native_abs/transformations.pcd" "$OUTPUT_DIR/native_transformations.pcd" 2>/dev/null || true
  fi
else
  echo "LIO-SAM save_map service failed; Native Map will be marked missing unless another upstream export exists" >&2
fi

kill -INT "$record_pid" 2>/dev/null || true
if ! wait "$record_pid"; then
  echo "LIO-SAM recorder exited with failure; see $OUTPUT_DIR/record.log" >&2
  exit 69
fi
cleanup
