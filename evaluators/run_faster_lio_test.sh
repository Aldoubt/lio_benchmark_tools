#!/usr/bin/env bash
set -euo pipefail

WORKSPACE=${WORKSPACE:-$PWD}
BAG_INPUT=${1:?usage: run_faster_lio_test.sh BAG_DIR_OR_ROS1_BAG OUTPUT_DIR}
OUTPUT_DIR=${2:?usage: run_faster_lio_test.sh BAG_DIR_OR_ROS1_BAG OUTPUT_DIR}
BAG_PLAY_RATE=${BAG_PLAY_RATE:-1.0}
BENCHMARK_RUN_DIR=${BENCHMARK_RUN_DIR:?BENCHMARK_RUN_DIR is required}
BENCHMARK_GENERATED_CONFIG_DIR=${BENCHMARK_GENERATED_CONFIG_DIR:?BENCHMARK_GENERATED_CONFIG_DIR is required}
SOURCE_DIR=${BENCHMARK_FASTER_LIO_SOURCE:-$WORKSPACE/algorithms/faster-lio}
mkdir -p "$OUTPUT_DIR" "$BENCHMARK_GENERATED_CONFIG_DIR"

case "${ROS_DISTRO:-}" in
  melodic|noetic) ;;
  *)
    echo "Faster-LIO upstream is registered as ROS1 Melodic/Noetic; active ROS_DISTRO=${ROS_DISTRO:-<unset>}" >&2
    exit 64
    ;;
esac

if [[ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]]; then
  source "/opt/ros/$ROS_DISTRO/setup.bash"
fi
if [[ -f "$WORKSPACE/devel/setup.bash" ]]; then
  source "$WORKSPACE/devel/setup.bash"
elif [[ -f "$WORKSPACE/install/setup.bash" ]]; then
  source "$WORKSPACE/install/setup.bash"
fi
set -u

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "Faster-LIO source directory is missing: $SOURCE_DIR" >&2
  exit 65
fi
if ! rospack find faster_lio >/dev/null 2>&1; then
  echo "ROS1 package 'faster_lio' is not available in the sourced environment" >&2
  exit 65
fi

# The upstream implementation consumes ROS1 bags. A rosbag2 directory is never
# converted implicitly because that would hide an important benchmark input
# transformation. Supply an explicitly generated ROS1 bag through
# BENCHMARK_ROS1_BAG_FILE when the frozen dataset itself is rosbag2.
if [[ -f "$BAG_INPUT" ]]; then
  ROS1_BAG=$BAG_INPUT
elif [[ -n "${BENCHMARK_ROS1_BAG_FILE:-}" && -f "$BENCHMARK_ROS1_BAG_FILE" ]]; then
  ROS1_BAG=$BENCHMARK_ROS1_BAG_FILE
else
  echo "Faster-LIO requires a ROS1 .bag. For rosbag2 datasets set BENCHMARK_ROS1_BAG_FILE to an explicit converted artifact." >&2
  exit 66
fi

BASE_CONFIG=${BENCHMARK_FASTER_LIO_BASE_CONFIG:-$SOURCE_DIR/config/mid360.yaml}
if [[ ! -f "$BASE_CONFIG" ]]; then
  echo "Faster-LIO base config is missing: $BASE_CONFIG" >&2
  exit 67
fi
CALIBRATION_JSON="$BENCHMARK_GENERATED_CONFIG_DIR/calibration.json"
if [[ ! -f "$CALIBRATION_JSON" ]]; then
  echo "benchmark-generated calibration is missing: $CALIBRATION_JSON" >&2
  exit 67
fi
CONFIG="$BENCHMARK_GENERATED_CONFIG_DIR/benchmark.yaml"

python3 - "$BASE_CONFIG" "$CONFIG" "$BENCHMARK_RUN_DIR/manifest.json" "$CALIBRATION_JSON" <<'PY'
from pathlib import Path
import json
import re
import sys

source, output, manifest_path, calibration_path = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
cal = json.loads(calibration_path.read_text(encoding="utf-8"))
dataset = manifest["dataset"]
lidar_topic = dataset["topics"]["lidar"]
imu_topic = dataset["topics"]["imu"]
lidar_type_name = str(dataset.get("types", {}).get("lidar", ""))
lidar_type = 6 if "PointCloud2" in lidar_type_name else 1
translation = cal["translation_m"]
rotation = cal["rotation_row_major"]

def replace_scalar(pattern: str, replacement: str) -> None:
    global text
    text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"expected one Faster-LIO config match for {pattern!r}, got {count}")

replace_scalar(r'^(\s*lid_topic:\s*).*$' , rf'\1"{lidar_topic}"')
replace_scalar(r'^(\s*imu_topic:\s*).*$' , rf'\1"{imu_topic}"')
replace_scalar(r'^(\s*lidar_type:\s*).*$' , rf'\g<1>{lidar_type} # benchmark generated')
replace_scalar(r'^(\s*extrinsic_T:\s*).*$' , r'\g<1>[' + ", ".join(f"{v:.12g}" for v in translation) + ']')
replace_scalar(r'^(\s*extrinsic_R:\s*).*$' , r'\g<1>[' + ", ".join(f"{v:.12g}" for v in rotation) + ']')
replace_scalar(r'^(\s*pcd_save_en:\s*).*$' , r'\g<1>true # benchmark generated')
output.write_text(text, encoding="utf-8")
PY

export ROS_MASTER_URI=${ROS_MASTER_URI:-http://127.0.0.1:11321}
export ROS_LOG_DIR="$OUTPUT_DIR/ros_logs"
mkdir -p "$ROS_LOG_DIR"
cleanup() {
  jobs -pr | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

roscore -p "${ROS1_MASTER_PORT:-11321}" >"$OUTPUT_DIR/roscore.log" 2>&1 &
master_pid=$!
sleep 2
if ! kill -0 "$master_pid" 2>/dev/null; then
  echo "ROS1 master failed to start; see $OUTPUT_DIR/roscore.log" >&2
  exit 68
fi

rosparam set /use_sim_time true
rosparam load "$CONFIG"
(
  cd "$OUTPUT_DIR"
  rosrun faster_lio run_mapping_online >"$OUTPUT_DIR/faster_lio.log" 2>&1
) &
node_pid=$!
sleep 3
if ! kill -0 "$node_pid" 2>/dev/null; then
  echo "Faster-LIO failed to start; see $OUTPUT_DIR/faster_lio.log" >&2
  exit 69
fi

rostopic echo -p /Odometry >"$OUTPUT_DIR/odometry_raw.csv" 2>"$OUTPUT_DIR/odometry_echo.log" &
echo_pid=$!
rosbag record -O "$OUTPUT_DIR/faster_lio_outputs.bag" /Odometry /path /cloud_registered /cloud_registered_body \
  >"$OUTPUT_DIR/record.log" 2>&1 &
record_pid=$!
sleep 2

rosbag play "$ROS1_BAG" --rate "$BAG_PLAY_RATE" --clock \
  >"$OUTPUT_DIR/play.log" 2>&1
sleep 2

kill -INT "$echo_pid" "$record_pid" "$node_pid" 2>/dev/null || true
wait "$echo_pid" || true
if ! wait "$record_pid"; then
  echo "Faster-LIO output recorder failed; see $OUTPUT_DIR/record.log" >&2
  exit 70
fi
for _ in $(seq 1 20); do
  kill -0 "$node_pid" 2>/dev/null || break
  sleep 1
done
kill -TERM "$node_pid" 2>/dev/null || true
wait "$node_pid" || true

# Upstream PCD saving uses a relative PCD directory. Because the node runs with
# OUTPUT_DIR as cwd, any native scans.pcd remains inside the benchmark run.
if [[ ! -s "$OUTPUT_DIR/odometry_raw.csv" ]]; then
  echo "Faster-LIO produced no odometry CSV" >&2
  exit 71
fi
