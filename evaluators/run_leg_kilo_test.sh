#!/usr/bin/env bash
set -euo pipefail

BAG_DIR=${1:?"usage: run_leg_kilo_test.sh <rosbag2_dir> <output_dir>"}
OUTPUT_DIR=${2:?"usage: run_leg_kilo_test.sh <rosbag2_dir> <output_dir>"}
mkdir -p "$OUTPUT_DIR"

# Upstream Leg-KILO 2.0 is currently published/tested as a ROS1/catkin project.
# This repository therefore does not silently rewrite it into ROS2 or guess a
# rosbag1<->rosbag2 conversion path. Point this shim at the locally validated
# adapter that you already use to run Leg-KILO on MID360+IMU data.
LOCAL_ADAPTER=${LEG_KILO_ADAPTER_BIN:-}

cat >"$OUTPUT_DIR/benchmark_adapter_contract.json" <<EOF
{
  "algorithm": "Leg-KILO 2.0",
  "benchmark_mode": "lidar_imu",
  "leg_kinematics": false,
  "bag_dir": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$BAG_DIR"),
  "local_adapter": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$LOCAL_ADAPTER")
}
EOF

if [[ -z "$LOCAL_ADAPTER" ]]; then
  cat >&2 <<'EOF'
Leg-KILO fixed baseline is registered, but no local execution adapter is configured.

Upstream Leg-KILO 2.0 is ROS1/catkin. Set LEG_KILO_ADAPTER_BIN to an executable
wrapper that has already been validated on this machine. The wrapper contract is:

  <adapter> <rosbag2_directory> <benchmark_output_directory>

The wrapper is responsible for the explicit ROS1/ROS2 bridge/conversion or local
ROS2 port used in your existing standalone Leg-KILO workflow. Do not hide source
patches or bag conversion inside lio_benchmark_tools.
EOF
  exit 64
fi

if [[ ! -x "$LOCAL_ADAPTER" ]]; then
  echo "LEG_KILO_ADAPTER_BIN is not executable: $LOCAL_ADAPTER" >&2
  exit 65
fi

"$LOCAL_ADAPTER" "$BAG_DIR" "$OUTPUT_DIR"
