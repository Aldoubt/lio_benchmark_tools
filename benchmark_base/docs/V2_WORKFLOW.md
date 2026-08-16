# LIO Benchmark Tools V2 / Baseline Suite Workflow

## 1. Register a dataset

从模板复制：

```bash
cp benchmark_base/registry/datasets/example_mid360.json \
   benchmark_base/registry/datasets/my_scene.json
```

至少冻结：

```text
dataset_id
bag_dir
sha256 when available
environment / acquisition
topics and message types
point-time field / unit
canonical LiDAR→IMU calibration
calibration source
calibration status = CONFIRMED | UNCONFIRMED
```

Canonical calibration 统一定义为：

```text
p_imu = R_li * p_lidar + t_li
```

如果算法需要 IMU→LiDAR，benchmark core 生成：

```text
R_il = R_li^T
t_il = -R_li^T * t_li
```

不要修改原始 bag 来适配某一个算法，不要把相同数组直接复制给外参方向相反的算法

`UNCONFIRMED` calibration 可以用于诊断，但 LiDAR+IMU 正式比较必须标记为 `DIAGNOSTIC_ONLY / BLOCKED_CALIBRATION`

## 2. Select baseline families

查看 registry：

```bash
lio-benchmark list algorithms
lio-benchmark show algorithm fast_lio2
lio-benchmark show algorithm leg_kilo
```

### Core

```text
fast_livo2
fast_lio2
point_lio
dlio
lio_sam
glim_odometry
glim_full_slam
leg_kilo
kiss_icp
```

其中 `glim_odometry` 和 `glim_full_slam` 是同一个 GLIM family 的两个 runnable mode

### Research

```text
faster_lio
slict
```

Research baseline 允许被机器环境阻塞

当前选择的官方环境契约：

```text
Faster-LIO -> ROS1 Melodic/Noetic
SLICT master -> Ubuntu 24.04 / ROS2 Jazzy
```

主 Humble 机器对这两个算法返回 `BLOCKED_ENVIRONMENT` 是正确行为，不应为了“凑齐算法”做隐藏移植

### Legacy

```text
leg_kilo2_lidar_imu
```

它保留历史身份，不等于当前 `ouguangjun/Leg-KILO` master

## 3. Create a frozen run

复制 `benchmark_base/config/experiment.template.json`，填写 workspace、output_root、dataset ID 和算法列表

```bash
lio-benchmark validate --config experiment.json
lio-benchmark init --config experiment.json --run-id scene_001
lio-benchmark snapshot --run /path/to/runs/scene_001
```

`manifest.json` 是该 run 的冻结契约，后续 registry 修改不会回写历史 run

### 3.1. Freeze replay and machine-specific executable choices

Source manifest 可以显式增加：

```json
{
  "execution_overrides": {
    "fast_lio2": {
      "executable": "/absolute/path/to/fastlio_mapping"
    }
  },
  "replay": {
    "rate": 1.0,
    "start_offset_s": 0.0,
    "duration_s": 15.0
  }
}
```

`execution_overrides` 只用于当前实验/当前机器，不修改 Algorithm Registry。执行解析严格只有：

```text
EXPLICIT_EXECUTABLE_OVERRIDE
REGISTRY_DEFAULT_EXECUTION
```

不扫描 `$HOME`、`$WORKSPACE/build` 或其它常见目录。显式 executable 缺失、不是普通文件、无执行权限或无法 fingerprint 时返回 `BLOCKED_EXECUTION`，不回退到另一个实现。

`replay` 默认：

```text
rate = 1.0
start_offset_s = 0.0
duration_s = null   # run to bag end
```

run 初始化后，这些值写入 frozen `manifest.json`。后续 shell 变量 `BAG_PLAY_RATE / BAG_START_OFFSET / BAG_DURATION` 只是从 frozen manifest 派生的兼容变量，不再拥有覆盖权。

### 3.2. Freeze per-algorithm ROS runtime overlays

算法依赖独立 ROS workspace 时，不要求用户在运行 benchmark 前手工 source，也不把机器路径写进全局 Algorithm Registry。Source manifest 显式冻结：

```json
{
  "runtime_overlays": {
    "kiss_icp": [
      "/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash"
    ]
  }
}
```

当前版本只支持 **per-algorithm overlays**，不提供 global overlay。每个值必须是有序、非空、无重复的绝对 setup-script 路径列表；key 必须属于当前选择的 algorithm。

正式环境顺序固定为：

```text
/opt/ros/<distro>/setup.bash
        ↓
<workspace>/install/setup.bash, if present
        ↓
runtime_overlays[algorithm][0]
        ↓
runtime_overlays[algorithm][1]
        ↓
...
```

新 frozen run 的 preflight/runner 在构造这条链之前清除 caller 继承的 ROS overlay 路径变量，因此交互终端里已有的 `AMENT_PREFIX_PATH / CMAKE_PREFIX_PATH / COLCON_PREFIX_PATH / LD_LIBRARY_PATH / PYTHONPATH / ROS_PACKAGE_PATH` 不能让一个未声明 overlay 的 formal run 偶然通过。

不允许扫描 `$HOME`、build tree、`/tmp` 或其它目录猜 overlay；不自动 clone/build/install。声明路径缺失、不是普通文件、source 失败或最终 runtime package 不可见时，结果是 `BLOCKED_ENVIRONMENT`。

## 4. Preflight before running algorithms

先运行：

```bash
lio-benchmark preflight --run <run>
```

或只检查一个算法：

```bash
lio-benchmark preflight --run <run> --algorithm fast_lio2
```

状态语义：

```text
PASS
FAIL_IMPLEMENTATION
FAIL_ALGORITHM
BLOCKED_ENVIRONMENT
BLOCKED_DEPENDENCY
BLOCKED_INPUT
BLOCKED_CALIBRATION
BLOCKED_EXECUTION
NOT_TESTED
```

Preflight 负责检查：

```text
explicit execution override
frozen runtime overlay stack
runtime ROS package availability
source path as provenance evidence when applicable
runner adapter
ROS distro contract
required modalities
required dataset capabilities
calibration status
extrinsic convention
```

对于带 `runtime_overlays` 的新 frozen run，preflight 不使用 caller 的 ambient overlay 作为 package 证据，而是从基础 ROS + workspace + frozen algorithm overlays 重新构造正式环境。

显式 executable 已经给定且可执行时，缺少 registry `local_path_hint` 不应覆盖这个事实；对于 ROS package execution，`local_path_hint` 也不再代替真实 runtime package availability gate。runner、输入、ROS 环境、标定等 gate 仍独立生效。

不要把算法未安装、系统版本不匹配、执行文件无效、overlay 缺失或数据输入不兼容写成算法失败。

## 5. Offline benchmark and Runtime Identity

正式 benchmark 默认一次只跑一个算法：

```bash
lio-benchmark run --run <run> --algorithm fast_livo2
lio-benchmark run --run <run> --algorithm fast_lio2
```

必要时：

```bash
lio-benchmark run-all --run <run>
```

每个 adapter 遵守：

```text
preflight
prepare
run
collect
```

`prepare` 只能生成 run-local config/remap/calibration，不允许修改 upstream source tree

### 5.1. Runtime identity is frozen before estimator startup

runner 在正式 ROS/workspace/runtime-overlay 环境已经按 frozen contract source 后、estimator 启动之前写：

```text
metadata/algorithms/<algorithm>/runtime_identity.json
```

最低证据包括：

```text
identity_status = FROZEN | BLOCKED_EXECUTION
resolution_method
requested/resolved executable
executable SHA256 / size / mtime
registry package
runtime package / package prefix when applicable
runtime overlay setup path / SHA256 / size, in frozen order
source git root / remote / commit / branch / dirty when provable
source_relationship = REGISTRY_MATCH | REGISTRY_MISMATCH | UNKNOWN_SOURCE
effective command
effective config path + SHA256
ROS distro / workspace
bag path
frozen replay interval
```

每个 frozen setup script 在 estimator 启动前独立 fingerprint。最终 `runtime_package_prefix` 单独记录，不猜多个 overlay 中到底哪一层“拥有”该 package。

`EXPLICIT_EXECUTABLE_OVERRIDE` 是合法执行方式，不是错误状态。即使它对应的源码与 registry 默认实现不同，只要 binary 已被精确 fingerprint，这个事实就被保留；source relationship 独立记录。

同一个 run 已经存在 runtime identity 时，不允许静默覆盖或重跑。创建新的 run ID。

runner source overlay 阶段使用保留返回码 `65` 表示 runtime environment failure；如果 overlay 在 preflight 后、estimator 启动前失效，run metadata 仍写 `BLOCKED_ENVIRONMENT`，而不是错误归类为 `FAIL_ALGORITHM`。

### 5.2. Current finite-replay migration scope

当前目标机 finite-replay / runtime-identity smoke 首先迁移并验证：

```text
fast_livo2
fast_lio2
kiss_icp
```

其它 baseline 仍保留其各自 adapter 状态。除非相应 runner 已实现并验证同一 replay/runtime identity contract，否则不能因为 core manifest 支持 `replay` 就宣称该 adapter 已完成有限时长回放验证。

失败日志保留，不自动删除

## 6. Freeze common LiDAR scan sampling

Unified Map 不再让每个算法自己选择“差不多的一批 scan”

先生成：

```bash
lio-benchmark standardize scan-manifest --run <run>
```

输出：

```text
standardized/map_sampling/selected_scans.csv
standardized/map_sampling/metadata.json
```

默认 scan window 直接读取 frozen run `replay`：

```text
source = RUN_MANIFEST_REPLAY
```

因此一个 15 s smoke 不会把 source bag 后面几百秒的 scan 计为 unmatched。

显式 derived diagnostic 仍可使用：

```bash
lio-benchmark standardize scan-manifest \
  --run <run> \
  --start-offset-s 2 \
  --duration-s 5 \
  --overwrite
```

这种结果必须记录：

```text
source = CLI_OVERRIDE
```

历史 run 仍可使用 `LEGACY_REPLAY_WINDOW`，完全没有 replay 信息的老 run 才是 `FULL_BAG_DEFAULT`。

所有 Unified Maps 使用同一个 selected scan manifest

它至少记录：

```text
scan_index
timestamp_s
timestamp_source
bag_record_time_s
lidar_topic
selected
```

如果某算法无法匹配其中一帧，该帧保持在公共 manifest 中，并计入该算法 `unmatched_scan_count`

## 7. Standardize trajectories

兼容路径仍为：

```text
standardized/trajectories/<algorithm>.csv
```

标准列：

```text
timestamp_s
x_m y_m z_m
qx qy qz qw
roll_rad pitch_rad yaw_rad
source_topic
```

如果 upstream 已经提供轨迹 CSV，继续使用：

```bash
lio-benchmark standardize trajectory \
  --run <run> \
  --algorithm point_lio \
  --input /path/to/raw_trajectory.csv \
  --source-topic /odom
```

如果轨迹由 benchmark runner 记录在 `raw/<algorithm>/` 下的 ROS 2 bag，使用 run-native 入口：

```bash
lio-benchmark standardize trajectory-from-run \
  --run <run> \
  --algorithm fast_livo2
```

它自动从 frozen algorithm contract 读取 trajectory output topic，只在 `raw/<algorithm>/` 下寻找包含该 topic 的单一 ROS 2 bag，并支持：

```text
nav_msgs/msg/Odometry
geometry_msgs/msg/PoseStamped
geometry_msgs/msg/PoseWithCovarianceStamped
```

时间戳策略固定为：

```text
HEADER_STAMP_ELSE_BAG_RECORD_TIME
```

这个阶段只做表示转换。它不会执行：

```text
tracked-frame conversion
world-gauge / gravity alignment
LiDAR-IMU calibration transform
START_XY_YAW
interpolation / resampling
warm-up trimming
accuracy scoring
```

同时写：

```text
metadata/algorithms/<algorithm>/trajectory_standardization.json
```

已有 standardized trajectory 时直接 fail closed，本阶段没有 `--overwrite`。

统一地图的 pose association 必须使用：

```text
LiDAR timestamp
↓
trajectory adjacent timestamps
↓
linear position interpolation
quaternion shortest-arc SLERP
```

禁止退回 normalized-index / scan-index matching

## 8. Produce Native Map and Unified Map

### Native Map

必须来自 upstream 算法自己的 mapping system

```text
standardized/maps/<algorithm>/native/
├─ map.*
└─ metadata.json
```

状态：

```text
AVAILABLE
NOT_PROVIDED
FAILED
```

如果算法没有真正的 native global map，写 `NOT_PROVIDED`

禁止把 benchmark 自己累计的点云叫 Native Map

### Unified Map

```bash
lio-benchmark standardize map --run <run> --algorithm point_lio
```

输出：

```text
standardized/maps/<algorithm>/unified/map.ply
standardized/maps/<algorithm>/unified/metadata.json
```

兼容 V2：

```text
standardized/maps/<algorithm>/unified_map.ply
standardized/maps/<algorithm>/map_metadata.json
```

Unified Map 固定使用：

```text
same bag
same selected scans
same canonical calibration
algorithm standardized trajectory
same near-range filter
same point sampling
same voxel rule
same reconstruction code
```

## 9. Runtime provenance and frame audit

先保留运行时事实，再做事后审计：

```text
runtime_identity.json
        ↓
trajectory standardization evidence
        ↓
trajectory frame audit
        ↓
post-run source/package enrichment
        ↓
runtime provenance verdict
```

执行：

```bash
lio-benchmark audit trajectory-frames \
  --run <run> \
  --algorithms fast_livo2 fast_lio2 kiss_icp

lio-benchmark audit runtime-provenance \
  --run <run> \
  --algorithms fast_livo2 fast_lio2 kiss_icp
```

新 run：

```text
identity_evidence_source = RUNTIME_IDENTITY
```

旧 run 没有 runtime identity 时：

```text
identity_evidence_source = LEGACY_RECONSTRUCTED
```

binary / overlay identity 与 frame semantics 是不同 gate。精确知道运行的是哪个 executable、source 了哪个 setup 文件，并不会自动把 `odom -> sensor` 解释为 registry 声明的 `camera_init -> body`。

## 10. Display Alignment

Display Alignment 是 derived visualization，不是科学数据处理

支持：

```text
NONE
START_XY_YAW
```

默认：

```text
START_XY_YAW
```

它只使初始：

```text
X = 0
Y = 0
yaw = 0
```

它不去掉：

```text
Z
roll / pitch
subsequent drift
scale error
non-rigid distortion
```

并且永远不写回：

```text
standardized trajectory
Native Map
Unified Map
scientific metrics
```

元数据保存在：

```text
figures/display_alignment/
```

Runnable ID 的 role 从 frozen registry 推导，例如 `glim_full_slam` 的 alignment metadata 是 `SYSTEM_MAPPING`，不是硬编码 `ODOMETRY`

## 11. Inspect maps interactively

```bash
lio-benchmark inspect \
  --run <run> \
  --algorithms fast_livo2 fast_lio2 point_lio leg_kilo \
  --map-kind unified \
  --color-mode height \
  --display-alignment START_XY_YAW
```

可以切：

```text
map-kind = unified | native
color-mode = height | intensity | algorithm
```

Inspector 使用同一个 Open3D scene，算法切换共享 camera

跨算法 height/intensity coloring 使用公共 scalar range，不按算法单独 autoscale

支持：

```text
XY / XZ / YZ / Perspective
ROI preset
camera preset
Save Camera Preset
Export Screenshot
```

## 12. Generate reports

```bash
lio-benchmark report \
  --run <run> \
  --display-alignment START_XY_YAW
```

报告包含：

```text
metrics/summary.csv
trajectory comparison
XY / XZ / YZ Unified Map comparison
shared height scale
runtime comparison
reports/report.md
reports/report.html
```

结果按三类 view 分开：

```text
Common LiDAR+IMU Odometry
System Mapping
Control / Extension
```

不生成一个跨输入条件、跨后端语义的总排名

没有 Ground Truth 时，不把首尾位移、Z 差等冒充 ATE 真值误差

## 13. Diagnostic bundle

将本轮小型诊断证据打成单一上传包：

```bash
lio-benchmark bundle --run <run>
```

默认包含：

```text
manifest / run status
runtime_identity.json
trajectory_standardization.json
runtime provenance
trajectory frame audit
diagnostic CSV
Common Scan Manifest
Unified Map metadata
benchmark Git HEAD / status / local diff
```

不包含：

```text
raw rosbag
DB3 / MCAP
PLY / PCD
executable binary
report / PNG (default)
```

需要 report/PNG：

```bash
lio-benchmark bundle --run <run> --include-reports
```

## 14. Generate README Demo

```bash
lio-benchmark demo \
  --run <run> \
  --algorithms fast_livo2 fast_lio2 point_lio leg_kilo \
  --display-alignment START_XY_YAW \
  --output assets/demo/same_bag_map_comparison.gif
```

所有算法必须共享：

```text
same frozen run
same ROI
same Unified Map contract
same Display Alignment mode
same plot bounds
same height scale
same camera path
same viewport
```

`ffmpeg` 缺失时只保留帧并给出合成命令，不影响 benchmark 本体

最终小体积 GIF 必须人工检查后再提交

## 15. Live Debug

Live Debug 与正式性能 benchmark 分开

```bash
lio-benchmark live prepare \
  --dataset my_scene \
  --algorithms fast_livo2 fast_lio2 point_lio \
  --workspace ~/ros2_ws \
  --rate 0.5
```

生成可读的 bag/node/session 脚本，用于：

```text
暂停/慢放 bag
重启单个 estimator
观察 topic / TF
观察 registered cloud / map
记录失败起点
```

事件标记：

```bash
lio-benchmark mark \
  --session <session> \
  --algorithm point_lio \
  --event repetitive_row_misregistration \
  --bag-time 84.32 \
  --note "row alias begins after turn"
```

## 16. Current green-house three-algorithm Runtime Contract smoke

目标机专用配置：

```text
benchmark_base/config/green_house_three_runtime_smoke.json
```

它冻结：

```text
algorithms = fast_livo2, fast_lio2, kiss_icp
FAST-LIO2 executable = /home/yangxuan/RM-NAV/build/fast_lio/fastlio_mapping
KISS runtime overlay = /home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash
replay = 15 s @ 1.0x
output root = /home/yangxuan/lio_benchmark_runs/green_house
```

### 16.1. Fresh-shell runtime overlay gate

目标机 runtime-overlay acceptance 必须从新的 shell 开始。只 source 基础 ROS distro：

```bash
cd /home/yangxuan/lio_benchmark_tools
git pull --ff-only
source /opt/ros/humble/setup.bash
```

在正式 preflight / run 之前**不要**手工 source：

```text
/home/yangxuan/agt_navigation_v2/install/setup.bash
/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash
```

benchmark 必须自己从 frozen manifest 重建这两层环境，否则不能证明 runtime overlay contract 生效。

创建新 run：

```bash
CONFIG=/home/yangxuan/lio_benchmark_tools/benchmark_base/config/green_house_three_runtime_smoke.json
RUN_ID="green_house_runtime_overlay_$(date +%Y%m%d_%H%M%S)"
RUN="/home/yangxuan/lio_benchmark_runs/green_house/$RUN_ID"
export RUN

benchmark_base/bin/lio-benchmark validate --config "$CONFIG"
benchmark_base/bin/lio-benchmark init --config "$CONFIG" --run-id "$RUN_ID"
benchmark_base/bin/lio-benchmark snapshot --run "$RUN"
benchmark_base/bin/lio-benchmark preflight \
  --run "$RUN" \
  --allow-diagnostic-calibration

echo "preflight rc=$?"
```

当前数据集 LiDAR–IMU calibration 仍是 diagnostic/unverified，因此 required gate 是：

```text
FAST-LIVO2 -> BLOCKED_CALIBRATION, runnable=true, diagnostic_only=true
FAST-LIO2  -> BLOCKED_CALIBRATION, runnable=true, diagnostic_only=true
KISS-ICP   -> PASS, runnable=true, diagnostic_only=false
preflight rc=0
```

先只运行 KISS，证明它不依赖 caller 手工 source：

```bash
benchmark_base/bin/lio-benchmark run \
  --run "$RUN" \
  --algorithm kiss_icp \
  --allow-diagnostic-calibration

echo "kiss run rc=$?"
```

检查：

```text
metadata/algorithms/kiss_icp/runtime_identity.json
metadata/run_kiss_icp.json
raw/kiss_icp/
```

runtime identity 至少要求：

```text
identity_status = FROZEN
runtime_package = kiss_icp
runtime_package_prefix = /home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/kiss_icp
runtime_overlays[0].setup_path = /home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash
runtime_overlays[0].setup_sha256 is non-empty
runtime_overlays[0].setup_size_bytes > 0
```

目标机这道 gate 尚未完成前，不把 runtime overlays 写成真实机器 PASS。

### 16.2. Full three-algorithm diagnostic smoke

Fresh-shell KISS gate 成功后，才继续同一个新 run 的三个算法诊断回放：

```bash
for ALG in fast_livo2 fast_lio2; do
  benchmark_base/bin/lio-benchmark run \
    --run "$RUN" \
    --algorithm "$ALG" \
    --allow-diagnostic-calibration || break
done
```

KISS 已在 16.1 单独执行，不要在同一个 run 上重复执行，否则 immutable runtime identity 会正确拒绝重跑。

把三个 run-local raw trajectory bag 标准化：

```bash
for ALG in fast_livo2 fast_lio2 kiss_icp; do
  benchmark_base/bin/lio-benchmark standardize trajectory-from-run \
    --run "$RUN" \
    --algorithm "$ALG" || break
done
```

然后冻结公共 scan selection 并做 frame/provenance audit：

```bash
benchmark_base/bin/lio-benchmark standardize scan-manifest --run "$RUN"

benchmark_base/bin/lio-benchmark audit trajectory-frames \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp

benchmark_base/bin/lio-benchmark audit runtime-provenance \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp
```

重建三张 Unified Map：

```bash
for ALG in fast_livo2 fast_lio2 kiss_icp; do
  benchmark_base/bin/lio-benchmark standardize map \
    --run "$RUN" --algorithm "$ALG" || break
done

benchmark_base/bin/lio-benchmark bundle --run "$RUN"
```

Runtime + trajectory standardization gate 至少确认：

```text
3 × runtime_identity.json exist
KISS runtime overlay setup fingerprint is frozen
3 × trajectory_standardization.json exist
3 × standardized trajectory CSV exist and are non-empty
FAST-LIO2 resolution_method = EXPLICIT_EXECUTABLE_OVERRIDE
FAST-LIO2 resolved executable + SHA256 are non-empty
all three replay.duration_s = 15.0
scan manifest source = RUN_MANIFEST_REPLAY
runtime provenance identity_evidence_source = RUNTIME_IDENTITY
frame audit remains independent
```

完成这道 gate 后再进入 Relative SE(3) Motion Benchmark，避免把 implementation/gauge 问题混成 estimator drift。

## 17. Recommended integration order on a new machine

先短段 smoke，再完整 bag

推荐顺序：

```text
1. FAST-LIVO2 reference
2. FAST-LIO2
3. KISS-ICP
4. current Leg-KILO master
5. Point-LIO
6. DLIO
7. LIO-SAM
8. GLIM odometry / full SLAM
9. Faster-LIO where ROS1 environment exists
10. SLICT where Jazzy environment exists
```

每个算法至少检查：

```text
startup
full/partial bag consumption
runtime identity
runtime overlay evidence when declared
trajectory standardization evidence
trajectory monotonic timestamps
NaN / Inf
trajectory duration coverage
Unified Map match ratio
native-map provenance
logs / failure evidence
```

## 18. Research use

工程仓库可以保留全部可运行 baseline，但论文正文不需要堆满算法

推荐：

```text
Engineering benchmark
= Core suite + available Research baselines

Paper main comparison
= representative algorithms from distinct families + frozen datasets
```

跨场景使用时，只新增 Dataset Registry / calibration / experiment manifest，不应该为每个新场景重写 benchmark core