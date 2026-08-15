#!/usr/bin/env bash
set -euo pipefail

WORKSPACE=${WORKSPACE:-$PWD}
BAG_DIR=${1:?usage: run_slict_test.sh ROSBAG2_DIR OUTPUT_DIR}
OUTPUT_DIR=${2:?usage: run_slict_test.sh ROSBAG2_DIR OUTPUT_DIR}
BAG_PLAY_RATE=${BAG_PLAY_RATE:-1.0}
BENCHMARK_GENERATED_CONFIG_DIR=${BENCHMARK_GENERATED_CONFIG_DIR:?BENCHMARK_GENERATED_CONFIG_DIR is required}
SOURCE_DIR=${BENCHMARK_SLICT_SOURCE:-$WORKSPACE/algorithms/slict}
SOURCE_CONFIG=${BENCHMARK_SLICT_CONFIG:-}
USE_LIVOX_CONVERTER=${BENCHMARK_SLICT_USE_LIVOX_CONVERTER:-0}
mkdir -p "$OUTPUT_DIR" "$BENCHMARK_GENERATED_CONFIG_DIR"

if [[ "${ROS_DISTRO:-}" != "jazzy" ]]; then
  echo "SLICT current master is registered for ROS 2 Jazzy; active ROS_DISTRO=${ROS_DISTRO:-<unset>}" >&2
  exit 64
fi
source /opt/ros/jazzy/setup.bash
if [[ -f "$WORKSPACE/install/setup.bash" ]]; then
  source "$WORKSPACE/install/setup.bash"
fi
set -u

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "SLICT source directory is missing: $SOURCE_DIR" >&2
  exit 65
fi
if ! ros2 pkg prefix slict >/dev/null 2>&1; then
  echo "ROS 2 package 'slict' is not available in the sourced Jazzy environment" >&2
  exit 65
fi
if [[ ! -d "$BAG_DIR" || ! -f "$BAG_DIR/metadata.yaml" ]]; then
  echo "SLICT adapter requires a ROS 2 bag directory: $BAG_DIR" >&2
  exit 66
fi

# SLICT has many dataset-specific timing/extrinsic parameters. The benchmark
# therefore requires an explicit, reviewed config rather than silently copying
# one of upstream's public-dataset files and pretending it fits a new bag.
if [[ -z "$SOURCE_CONFIG" || ! -f "$SOURCE_CONFIG" ]]; then
  echo "Set BENCHMARK_SLICT_CONFIG to a reviewed dataset-specific SLICT YAML." >&2
  echo "It must explicitly encode lidar/imu topics, point timestamp handling and LiDAR-to-body extrinsics." >&2
  exit 67
fi
CONFIG="$BENCHMARK_GENERATED_CONFIG_DIR/benchmark.yaml"
cp -f "$SOURCE_CONFIG" "$CONFIG"

export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$ROS_LOG_DIR" "$OUTPUT_DIR/slict_log"
cleanup() { jobs -pr | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

converter_pid=""
if [[ "$USE_LIVOX_CONVERTER" == "1" ]]; then
  if ! ros2 pkg executables slict | grep -q 'slict_livox_to_ouster'; then
    echo "SLICT Livox converter executable is unavailable" >&2
    exit 68
  fi
  ros2 run slict slict_livox_to_ouster --ros-args --params-file "$CONFIG" \
    >"$OUTPUT_DIR/livox_converter.log" 2>&1 &
  converter_pid=$!
fi

ros2 run slict slict_sensorsync --ros-args --params-file "$CONFIG" \
  >"$OUTPUT_DIR/sensorsync.log" 2>&1 &
sync_pid=$!
ros2 run slict slict_estimator --ros-args --params-file "$CONFIG" \
  -p autoexit:=true -p log_dir:="$OUTPUT_DIR/slict_log" \
  >"$OUTPUT_DIR/estimator.log" 2>&1 &
estimator_pid=$!
ros2 run slict slict_imu_odom --ros-args --params-file "$CONFIG" \
  >"$OUTPUT_DIR/imu_odom.log" 2>&1 &
imu_pid=$!

sleep 4
for spec in "sensorsync:$sync_pid" "estimator:$estimator_pid" "imu_odom:$imu_pid"; do
  name=${spec%%:*}; pid=${spec##*:}
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "SLICT $name failed to start; inspect $OUTPUT_DIR/${name}.log" >&2
    exit 69
  fi
done
if [[ -n "$converter_pid" ]] && ! kill -0 "$converter_pid" 2>/dev/null; then
  echo "SLICT Livox converter failed to start; inspect $OUTPUT_DIR/livox_converter.log" >&2
  exit 69
fi

# Until a selected SLICT implementation/output-role mapping is validated on a
# real dataset, retain all ROS graph evidence instead of inventing canonical
# trajectory topic names in the adapter.
ros2 bag record -a -o "$OUTPUT_DIR/slict_outputs" \
  >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2
if ! kill -0 "$record_pid" 2>/dev/null; then
  echo "SLICT output recorder failed to start; see $OUTPUT_DIR/record.log" >&2
  exit 70
fi

ros2 bag play "$BAG_DIR" --rate "$BAG_PLAY_RATE" --clock 100.0 \
  >"$OUTPUT_DIR/play.log" 2>&1
sleep 3

kill -INT "$record_pid" "$sync_pid" "$estimator_pid" "$imu_pid" ${converter_pid:+"$converter_pid"} 2>/dev/null || true
if ! wait "$record_pid"; then
  echo "SLICT output recorder exited with failure; see $OUTPUT_DIR/record.log" >&2
  exit 71
fi
for pid in "$sync_pid" "$estimator_pid" "$imu_pid" ${converter_pid:+"$converter_pid"}; do
  kill -TERM "$pid" 2>/dev/null || true
done
wait "$sync_pid" || true
wait "$estimator_pid" || true
wait "$imu_pid" || true
if [[ -n "$converter_pid" ]]; then wait "$converter_pid" || true; fi

if [[ ! -f "$OUTPUT_DIR/slict_outputs/metadata.yaml" ]]; then
  echo "SLICT run produced no recorded ROS output bag" >&2
  exit 72
fi
