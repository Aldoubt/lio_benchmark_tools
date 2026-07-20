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
playback_rate=$(query playback_rate)
[[ "$playback_rate" == "1.0" || "$playback_rate" == "1" ]] || { echo "fair benchmark requires playback_rate=1.0" >&2; exit 65; }
smoke_duration_s="${LIO_BENCHMARK_DURATION_S:-}"
if [[ -n "$smoke_duration_s" && ! "$smoke_duration_s" =~ ^[1-9][0-9]*$ ]]; then
  echo "LIO_BENCHMARK_DURATION_S must be a positive integer" >&2
  exit 65
fi

worker_pids=()
stop_process() {
  local pid=$1 signal=${2:-TERM}
  kill -"$signal" "$pid" 2>/dev/null || return 0
  for _ in {1..50}; do
    kill -0 "$pid" 2>/dev/null || break
    [[ "$(ps -o stat= -p "$pid" 2>/dev/null)" == Z* ]] && break
    sleep 0.1
  done
  kill -KILL "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
cleanup() {
  for pid in "${worker_pids[@]:-}"; do stop_process "$pid" TERM; done
}
trap cleanup EXIT INT TERM

start_cloud_adapter() {
  local destination=$1
  python3 "$script_dir/adapters/custommsg_to_pointcloud2.py" --ros-args \
    -p input_topic:="$lidar_topic" -p output_topic:="$destination" -p sort_by_time:=true \
    -p metrics_path:="$output_dir/input_validation.json" >"$output_dir/cloud_adapter.log" 2>&1 &
  worker_pids+=("$!")
}
start_imu_scaler() {
  python3 "$script_dir/scale_imu_acceleration.py" --ros-args \
    -p input_topic:="$imu_topic" -p output_topic:="$imu_si_topic" -p acceleration_scale:=9.80665 \
    -p output_frame_id:=livox_imu >"$output_dir/imu_scaler.log" 2>&1 &
  worker_pids+=("$!")
}

output_topics=()
case "$algorithm" in
  kiss_icp)
    start_cloud_adapter "$cloud_topic"
    node_cmd=(ros2 launch kiss_icp odometry.launch.py topic:="$cloud_topic" config_file:="$algorithm_config" visualize:=false use_sim_time:=true publish_odom_tf:=false)
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
    node_cmd=(ros2 run fast_livo fastlivo_mapping --ros-args --params-file "$algorithm_config" -p use_sim_time:=true)
    output_topics=(/aft_mapped_to_init /path)
    ;;
  point_lio)
    start_cloud_adapter "$cloud_topic"
    node_cmd=(ros2 run point_lio pointlio_mapping --ros-args --params-file "$algorithm_config" -p use_sim_time:=true)
    output_topics=(/aft_mapped_to_init /path)
    ;;
  dlio)
    start_cloud_adapter "$cloud_topic"; start_imu_scaler
    node_cmd=(ros2 run direct_lidar_inertial_odometry dlio_odom_node --ros-args --params-file "$algorithm_config/dlio.yaml" --params-file "$algorithm_config/params.yaml" -p use_sim_time:=true -r pointcloud:="$cloud_topic" -r imu:="$imu_si_topic")
    output_topics=(/dlio/odom_node/odom /dlio/odom_node/path)
    ;;
  glim_odometry|glim_full_slam)
    start_cloud_adapter "$cloud_topic"; start_imu_scaler
    python3 "$script_dir/prepare_glim_config.py" "$algorithm_config" "$output_dir/config" >"$output_dir/config_prepare.log"
    node_cmd=(ros2 run glim_ros glim_rosnode --ros-args -p use_sim_time:=true -p config_path:="$output_dir/config" -p dump_path:="$output_dir/dump")
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

/usr/bin/time -v -o "$output_dir/resource_time.txt" "${node_cmd[@]}" >"$output_dir/stdout.log" 2>"$output_dir/stderr.log" &
node_pid=$!
sleep 5
kill -0 "$node_pid" 2>/dev/null || { echo "algorithm exited during startup" >&2; exit 70; }
node_control_pid=$(pgrep -P "$node_pid" | head -n 1 || true)
[[ -n "$node_control_pid" ]] || { echo "cannot identify ros2 node supervisor child" >&2; exit 70; }
for pid in "${worker_pids[@]:-}"; do
  kill -0 "$pid" 2>/dev/null || { echo "input adapter exited during startup: $pid" >&2; exit 70; }
done
ros2 bag record -o "$output_dir/trajectory" "${output_topics[@]}" >"$output_dir/record.log" 2>&1 &
record_pid=$!
sleep 2
set +e
"${playback_exec[@]}" >"$output_dir/play.log" 2>&1
play_exit_raw=$?
set -e
play_exit=$play_exit_raw
[[ -n "$smoke_duration_s" && "$play_exit_raw" -eq 124 ]] && play_exit=0
sleep 5
stop_process "$record_pid" INT
node_was_alive=false
kill -0 "$node_pid" 2>/dev/null && node_was_alive=true
stop_process "$node_control_pid" TERM
wait "$node_pid" 2>/dev/null || node_exit_raw=$?
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
python3 - "$output_dir/run_result.json" "$algorithm" "$play_exit" "$play_exit_raw" "$node_exit" "$node_exit_raw" "${smoke_duration_s:-}" "$trajectory_messages" <<'PY'
import json,sys
messages=int(sys.argv[8])
status='SUCCESS' if sys.argv[3]=='0' and sys.argv[5]=='0' and messages>0 else ('NO_ODOMETRY' if messages==0 else 'RUNTIME_CRASH')
duration=float(sys.argv[7]) if sys.argv[7] else None
json.dump({'algorithm':sys.argv[2],'status':status,'bag_play_exit_code':int(sys.argv[3]),'bag_play_exit_code_raw':int(sys.argv[4]),'algorithm_exit_code':int(sys.argv[5]),'algorithm_exit_code_raw':int(sys.argv[6]),'playback_rate':1.0,'smoke_duration_s':duration,'trajectory_messages':messages},open(sys.argv[1],'w'),indent=2)
PY
[[ "$play_exit" -eq 0 && "$node_exit" -eq 0 && "$trajectory_messages" -gt 0 ]]
