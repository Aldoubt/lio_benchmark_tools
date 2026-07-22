#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: run_algorithm.sh <algorithm> <bag_dir> <output_dir> <algorithm_config> <manifest_path>" >&2
  exit 64
fi

algorithm=$1
bag_dir=$2
output_dir=$3
algorithm_config=$4
manifest_path=$5
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
run_dir=$(cd -- "$(dirname -- "$manifest_path")" && pwd)
status_script="$script_dir/../benchmark_base/lio_benchmark/run_status.py"

for required in "$bag_dir" "$algorithm_config" "$manifest_path"; do
  [[ -e "$required" ]] || { echo "missing required path: $required" >&2; exit 66; }
done
mkdir -p "$output_dir" "$output_dir/ros_logs"
if [[ -e "$output_dir/run_result.json" || -e "$output_dir/trajectory/metadata.yaml" ]]; then
  echo "refusing to overwrite previous algorithm output: $output_dir" >&2
  exit 73
fi
export ROS_LOG_DIR="$output_dir/ros_logs"
# Keep benchmark publishers, /tf, and /clock isolated from any robot stack that
# may already be running on the workstation.  Override only for a controlled CI.
export ROS_DOMAIN_ID="${LIO_BENCHMARK_ROS_DOMAIN_ID:-77}"

status_update() {
  local algorithm_state=$1 bag_state=$2 result_path=${3:-} reason=${4:-}
  local command=("$run_dir" --algorithm "$algorithm" --algorithm-state "$algorithm_state" --bag-playback "$bag_state")
  [[ -n "$result_path" ]] && command+=(--result "$result_path")
  [[ -n "$reason" ]] && command+=(--reason "$reason")
  python3 "$status_script" "${command[@]}" >/dev/null 2>&1 || echo "warning: unable to update run status" >&2
}

status_update running not_started

query() { python3 "$script_dir/manifest_query.py" "$manifest_path" "$1"; }
mapfile -t setup_scripts < <(python3 - "$manifest_path" "$algorithm" <<'PY'
import json,sys
data=json.load(open(sys.argv[1])); seen=set()
for value in data['dataset'].get('setup_scripts',[])+data['algorithms'][sys.argv[2]]['setup_scripts']:
 if value not in seen:
  print(value); seen.add(value)
PY
)
export LIO_BENCHMARK_ALGORITHM_WORKSPACE="$(python3 "$script_dir/manifest_query.py" "$manifest_path" "algorithms.$algorithm.workspace")"
mapfile -t algorithm_environment < <(python3 - "$manifest_path" "$algorithm" <<'PY'
import json,sys
for key,value in json.load(open(sys.argv[1]))['algorithms'][sys.argv[2]].get('environment',{}).items():
 if not key.startswith('LIO_BENCHMARK_') or not key.replace('_','').isalnum():
  raise SystemExit(f'invalid benchmark environment key: {key}')
 print(f'{key}={value}')
PY
)
for assignment in "${algorithm_environment[@]:-}"; do
  [[ -n "$assignment" ]] && export "$assignment"
done
for setup in "${setup_scripts[@]}"; do
  [[ "$setup" = /* ]] || setup="$(cd -- "$(dirname -- "$script_dir")" && pwd)/$setup"
  # shellcheck disable=SC1090
  set +u
  source "$setup"
  set -u
done

lidar_topic=$(query dataset.lidar_topic)
imu_topic=$(query dataset.imu_topic)
cloud_topic=$(query dataset.adapter_topics.pointcloud2)
imu_si_topic=$(query dataset.adapter_topics.imu_si)
lio_sam_topic=$(query dataset.adapter_topics.lio_sam_points)
cloud_adapter_path=$(query dataset.cloud_adapter.required_executable)
playback_rate=$(query playback_rate)
[[ "$playback_rate" == "1.0" || "$playback_rate" == "1" ]] || { echo "fair benchmark requires playback_rate=1.0" >&2; exit 65; }
resource_interval="${LIO_BENCHMARK_RESOURCE_INTERVAL_S:-}"
if [[ -z "$resource_interval" ]]; then
  resource_interval=$(query resource_monitor_interval_s 2>/dev/null || true)
  resource_interval=${resource_interval:-1.0}
fi
smoke_duration_s="${LIO_BENCHMARK_DURATION_S:-}"
if [[ -n "$smoke_duration_s" && ! "$smoke_duration_s" =~ ^[1-9][0-9]*$ ]]; then
  echo "LIO_BENCHMARK_DURATION_S must be a positive integer" >&2
  exit 65
fi

worker_pids=()
node_child_pids=()
node_pid=""
node_control_pid=""
record_pid=""
resource_monitor_pid=""
status_heartbeat_pid=""
play_pid=""
stop_process() {
  local pid=$1 signal=${2:-TERM} timeout_s=${3:-5}
  kill -"$signal" -- -"$pid" 2>/dev/null || kill -"$signal" "$pid" 2>/dev/null || return 0
  for ((wait_index=0; wait_index<timeout_s*10; wait_index++)); do
    kill -0 "$pid" 2>/dev/null || break
    [[ "$(ps -o stat= -p "$pid" 2>/dev/null)" == Z* ]] && break
    sleep 0.1
  done
  kill -KILL "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
cleanup() {
  [[ -n "$status_heartbeat_pid" ]] && stop_process "$status_heartbeat_pid" TERM
  status_heartbeat_pid=""
  [[ -n "$play_pid" ]] && stop_process "$play_pid" INT
  play_pid=""
  [[ -n "$record_pid" ]] && stop_process "$record_pid" INT
  [[ -n "$node_control_pid" ]] && stop_process "$node_control_pid" TERM
  for pid in "${node_child_pids[@]:-}"; do stop_process "$pid" TERM; done
  if [[ -n "$node_pid" ]]; then
    wait "$node_pid" 2>/dev/null || true
  fi
  [[ -n "$resource_monitor_pid" ]] && stop_process "$resource_monitor_pid" TERM
  for pid in "${worker_pids[@]:-}"; do stop_process "$pid" TERM; done
  if [[ ! -e "$output_dir/run_result.json" ]]; then
    status_update failed failed "" "runner exited before run_result.json"
  fi
}
trap cleanup EXIT INT TERM

start_cloud_adapter() {
  local destination=$1
  setsid --wait "$cloud_adapter_path" --ros-args \
    -p input_topic:="$lidar_topic" -p output_topic:="$destination" -p sort_by_time:=true \
    -p metrics_path:="$output_dir/input_validation.json" >"$output_dir/cloud_adapter.log" 2>&1 &
  worker_pids+=("$!")
}
start_imu_scaler() {
  setsid --wait python3 "$script_dir/scale_imu_acceleration.py" --ros-args \
    -p input_topic:="$imu_topic" -p output_topic:="$imu_si_topic" -p acceleration_scale:=9.80665 \
    -p output_frame_id:=livox_imu >"$output_dir/imu_scaler.log" 2>&1 &
  worker_pids+=("$!")
}

output_topics=()
algorithm_executable=$(query "algorithms.$algorithm.required_executables.0")
case "$algorithm" in
  kiss_icp)
    start_cloud_adapter "$cloud_topic"
    node_cmd=("$algorithm_executable" --ros-args --params-file "$algorithm_config" -p use_sim_time:=true -p publish_odom_tf:=false -r pointcloud_topic:="$cloud_topic")
    output_topics=(/kiss/odometry /kiss/trajectory)
    ;;
  mola_lo|mola_lio)
    start_cloud_adapter "$cloud_topic"
    [[ "$algorithm" == mola_lio ]] && start_imu_scaler
    mola_pipeline="$(ros2 pkg prefix mola_lidar_odometry)/share/mola_lidar_odometry/pipelines/lidar3d-gicp.yaml"
    mola_args=(lidar_topic_name:="$cloud_topic" use_sim_time:=true use_mola_gui:=False use_rviz:=False ignore_lidar_pose_from_tf:=true publish_localization_following_rep105:=False mola_tf_base_link:=livox_frame min_nearby_poses_occupied:=2 simplemap_min_nearby_poses:=2 mola_lo_pipeline:="$mola_pipeline")
    if [[ "$algorithm" == mola_lio ]]; then
      export IMU_POSE_X=-0.011 IMU_POSE_Y=-0.02329 IMU_POSE_Z=0.04412
      export IMU_POSE_YAW=0 IMU_POSE_PITCH=0 IMU_POSE_ROLL=0
      mola_args+=(imu_topic_name:="$imu_si_topic" use_imu_for_lio:=True imu_gravity_correction:=true mola_deskew_method:=MotionCompensationMethod::IMU ignore_imu_pose_from_tf:=true)
    else
      mola_args+=(use_imu_for_lio:=False imu_gravity_correction:=false mola_deskew_method:=MotionCompensationMethod::Linear)
    fi
    node_cmd=(ros2 launch mola_lidar_odometry ros2-lidar-odometry.launch.py "${mola_args[@]}")
    output_topics=(/tf /lidar_odometry/metadata /diagnostics)
    ;;
  fast_livo2)
    node_cmd=("$algorithm_executable" --ros-args --params-file "$algorithm_config" -p use_sim_time:=true)
    output_topics=(/aft_mapped_to_init /path)
    ;;
  point_lio)
    start_cloud_adapter "$cloud_topic"
    node_cmd=("$algorithm_executable" --ros-args --params-file "$algorithm_config" -p use_sim_time:=true)
    output_topics=(/aft_mapped_to_init)
    ;;
  dlio)
    start_cloud_adapter "$cloud_topic"; start_imu_scaler
    node_cmd=("$algorithm_executable" --ros-args --params-file "$algorithm_config/dlio.yaml" --params-file "$algorithm_config/params.yaml" -p use_sim_time:=true -r pointcloud:="$cloud_topic" -r imu:="$imu_si_topic")
    # DLIO's /path message grows for the whole run. Recording it causes the
    # unbounded nav_msgs/Path to trigger Fast-CDR buffer failures; /odom is
    # sufficient for canonical trajectory standardization.
    output_topics=(/odom)
    ;;
  glim_odometry|glim_full_slam)
    start_cloud_adapter "$cloud_topic"; start_imu_scaler
    python3 "$script_dir/prepare_glim_config.py" "$algorithm_config/config.yaml" "$output_dir/config" >"$output_dir/config_prepare.log"
    node_cmd=("$algorithm_executable" --ros-args -p use_sim_time:=true -p config_path:="$output_dir/config" -p dump_path:="$output_dir/dump")
    output_topics=(/glim_ros/odom /glim_ros/odom_scanend /glim_ros/odom_corrected /glim_ros/odom_scanend_corrected)
    ;;
  lio_sam_no_loop|lio_sam_loop)
    start_cloud_adapter "$lio_sam_topic"; start_imu_scaler
    node_cmd=(ros2 launch "$script_dir/launch/lio_sam_headless.launch.py" params_file:="$algorithm_config")
    output_topics=(/lio_sam/mapping/odometry /lio_sam/imu/odometry /lio_sam/mapping/path)
    ;;
  *) echo "unsupported algorithm: $algorithm" >&2; exit 64 ;;
esac

printf '%q ' "${node_cmd[@]}" >"$output_dir/actual_node_command.txt"; printf '\n' >>"$output_dir/actual_node_command.txt"
play_cmd=(ros2 bag play "$bag_dir" --rate 1.0 --clock --disable-keyboard-controls --topics "$lidar_topic" "$imu_topic")
if [[ -n "$smoke_duration_s" ]]; then
  playback_exec=(timeout --signal=INT --kill-after=15 "${smoke_duration_s}s" "${play_cmd[@]}")
else
  playback_exec=("${play_cmd[@]}")
fi
printf '%q ' "${playback_exec[@]}" >"$output_dir/actual_play_command.txt"; printf '\n' >>"$output_dir/actual_play_command.txt"
cp "$algorithm_config" "$output_dir/actual_config" 2>/dev/null || cp -R "$algorithm_config" "$output_dir/actual_config"

/usr/bin/time -v -o "$output_dir/resource_time.txt" setsid --wait "${node_cmd[@]}" >"$output_dir/stdout.log" 2>"$output_dir/stderr.log" &
node_pid=$!
setsid --wait python3 "$script_dir/resource_monitor.py" "$node_pid" --output "$output_dir/resource_monitor.json" --interval "$resource_interval" </dev/null >"$output_dir/resource_monitor.log" 2>&1 &
resource_monitor_pid=$!
status_heartbeat_loop() {
  local bag_state=$1 phase=$2
  while kill -0 "$node_pid" 2>/dev/null; do
    python3 "$status_script" "$run_dir" --algorithm "$algorithm" --heartbeat --bag-playback "$bag_state" --phase "$phase" >/dev/null 2>&1 || true
    sleep 1
  done
}
status_heartbeat_loop not_started algorithm_startup </dev/null >/dev/null 2>&1 &
status_heartbeat_pid=$!
sleep 5
kill -0 "$node_pid" 2>/dev/null || { echo "algorithm exited during startup" >&2; exit 70; }
node_control_pid=$(pgrep -P "$node_pid" | head -n 1 || true)
[[ -n "$node_control_pid" ]] || { echo "cannot identify ros2 node supervisor child" >&2; exit 70; }
mapfile -t node_child_pids < <(pgrep -P "$node_control_pid" || true)
if ((${#worker_pids[@]})); then
  for pid in "${worker_pids[@]}"; do
    kill -0 "$pid" 2>/dev/null || { echo "input adapter exited during startup: $pid" >&2; exit 70; }
  done
fi
setsid --wait ros2 bag record -o "$output_dir/trajectory" "${output_topics[@]}" </dev/null >"$output_dir/record.log" 2>&1 &
record_pid=$!
sleep 2
set +e
status_update running running
[[ -n "$status_heartbeat_pid" ]] && stop_process "$status_heartbeat_pid" TERM
status_heartbeat_pid=""
status_heartbeat_loop running playback </dev/null >/dev/null 2>&1 &
status_heartbeat_pid=$!
setsid --wait "${playback_exec[@]}" </dev/null >"$output_dir/play.log" 2>&1 &
play_pid=$!
wait "$play_pid"
play_exit_raw=$?
play_pid=""
set -e
play_exit=$play_exit_raw
[[ -n "$smoke_duration_s" && "$play_exit_raw" -eq 124 ]] && play_exit=0
sleep 5
stop_process "$record_pid" INT
record_pid=""
node_was_alive=false
kill -0 "$node_pid" 2>/dev/null && node_was_alive=true
node_shutdown_timeout=5
[[ "$algorithm" == "point_lio" ]] && node_shutdown_timeout=60
stop_process "$node_control_pid" TERM "$node_shutdown_timeout"
node_control_pid=""
for pid in "${node_child_pids[@]:-}"; do stop_process "$pid" TERM "$node_shutdown_timeout"; done
node_child_pids=()
wait "$node_pid" 2>/dev/null || node_exit_raw=$?
node_pid=""
[[ -n "$resource_monitor_pid" ]] && wait "$resource_monitor_pid" 2>/dev/null || true
resource_monitor_pid=""
[[ -n "$status_heartbeat_pid" ]] && stop_process "$status_heartbeat_pid" TERM
status_heartbeat_pid=""
node_exit_raw=${node_exit_raw:-0}
node_exit=$node_exit_raw
if [[ "$node_was_alive" == true && ("$node_exit_raw" -eq 130 || "$node_exit_raw" -eq 143) ]]; then
  node_exit=0
fi
trajectory_messages=$(python3 - "$output_dir/trajectory/metadata.yaml" <<'PY'
import sys,yaml
print(yaml.safe_load(open(sys.argv[1]))['rosbag2_bagfile_information']['message_count'])
PY
)
python3 - "$output_dir/run_result.json" "$output_dir" "$algorithm" "$play_exit" "$play_exit_raw" "$node_exit" "$node_exit_raw" "${smoke_duration_s:-}" "$trajectory_messages" <<'PY'
import json,sys
messages=int(sys.argv[9])
status='SUCCESS' if sys.argv[4]=='0' and sys.argv[6]=='0' and messages>0 else ('NO_ODOMETRY' if messages==0 else 'RUNTIME_CRASH')
duration=float(sys.argv[8]) if sys.argv[8] else None
json.dump({'algorithm':sys.argv[3],'output_dir':sys.argv[2],'status':status,'bag_play_exit_code':int(sys.argv[4]),'bag_play_exit_code_raw':int(sys.argv[5]),'algorithm_exit_code':int(sys.argv[6]),'algorithm_exit_code_raw':int(sys.argv[7]),'playback_rate':1.0,'smoke_duration_s':duration,'trajectory_messages':messages},open(sys.argv[1],'w'),indent=2)
PY
result_status=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$output_dir/run_result.json")
if [[ "$result_status" == "SUCCESS" ]]; then
  status_update completed completed "$output_dir/run_result.json"
else
  status_update failed failed "$output_dir/run_result.json" "$result_status"
fi
[[ "$play_exit" -eq 0 && "$node_exit" -eq 0 && "$trajectory_messages" -gt 0 ]]
