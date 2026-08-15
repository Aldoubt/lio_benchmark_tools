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
NOT_TESTED
```

Preflight 负责检查：

```text
source path
runner adapter
ROS distro contract
required modalities
required dataset capabilities
calibration status
extrinsic convention
```

不要把算法未安装、系统版本不匹配或数据输入不兼容写成算法失败

## 5. Offline benchmark

正式 benchmark 默认一次只跑一个算法：

```bash
lio-benchmark run --run <run> --algorithm fast_livo2
lio-benchmark run --run <run> --algorithm fast_lio2
```

必要时：

```bash
lio-benchmark run-all --run <run>
```

正式默认：

```text
BAG_PLAY_RATE=1.0
```

失败日志保留，不自动删除

每个 adapter 遵守：

```text
preflight
prepare
run
collect
```

`prepare` 只能生成 run-local config/remap/calibration，不允许修改 upstream source tree

## 6. Freeze common LiDAR scan sampling

Unified Map 不再让每个算法自己选择“差不多的一批 scan”

先生成：

```text
standardized/map_sampling/selected_scans.csv
```

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

执行示例：

```bash
lio-benchmark standardize trajectory \
  --run <run> \
  --algorithm point_lio \
  --input /path/to/raw_trajectory.csv \
  --source-topic /odom
```

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

## 9. Display Alignment

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

## 10. Inspect maps interactively

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

## 11. Generate reports

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

## 12. Generate README Demo

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

## 13. Live Debug

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

## 14. Recommended integration order on a new machine

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
trajectory monotonic timestamps
NaN / Inf
trajectory duration coverage
Unified Map match ratio
native-map provenance
logs / failure evidence
```

## 15. Research use

工程仓库可以保留全部可运行 baseline，但论文正文不需要堆满算法

推荐：

```text
Engineering benchmark
= Core suite + available Research baselines

Paper main comparison
= representative algorithms from distinct families + frozen datasets
```

跨场景使用时，只新增 Dataset Registry / calibration / experiment manifest，不应该为每个新场景重写 benchmark core
