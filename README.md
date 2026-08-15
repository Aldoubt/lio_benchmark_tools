# LIO Benchmark Tools

**Reproducible same-bag LiDAR odometry / LIO / SLAM benchmarking for real robotic environments**

这个仓库用于回答一个实际问题：

> 给定同一份冻结传感器数据、同一套标定和同一套地图重建规则，不同 LiDAR odometry / LIO / SLAM 前端究竟会产生什么差异，应该如何解释这些差异

它不是一个新的定位算法，而是一套把 **算法运行、实验冻结、轨迹/地图标准化、交互式点云检查、论文图表、README Demo、实时失效排查** 解耦起来的研究工具

## Same-bag visual comparison

README Demo 由 frozen run 自动生成，不手工换视角、不删除失败区域

```bash
benchmark_base/bin/lio-benchmark demo \
  --run /path/to/frozen/run \
  --display-alignment START_XY_YAW \
  --output assets/demo/same_bag_map_comparison.gif
```

生成并人工审查真实数据结果后，主页直接使用仓库相对路径展示

```markdown
![Same-bag LIO map comparison](assets/demo/same_bag_map_comparison.gif)
```

> 当前仓库不提交伪造的占位 benchmark GIF，真实 GIF 只从可审计的 frozen run 生成

## Why this repository exists

传统“算法 A 的 PCD vs 算法 B 的 PCD”并不天然公平，因为最终地图同时包含：

```text
trajectory estimation
+ algorithm-native map representation
+ filtering / keyframes / submaps
+ backend optimization
+ loop closure
```

因此本仓库把结果拆成两种地图

```text
Algorithm
├─ Native Map
│  └─ upstream algorithm's own mapping result
│
└─ Unified Map
   └─ same raw LiDAR + same selected scans + same calibration
      + algorithm standardized trajectory + same reconstruction rules
```

`Native Map` 回答“完整系统最终能输出什么地图”

`Unified Map` 回答“只看这条估计轨迹，在统一地图重建口径下几何一致性如何”

二者不会被悄悄混为同一种结果

## Baseline suite

### Core baselines

| ID | Algorithm | Representative family | Effective input / role |
|---|---|---|---|
| `fast_livo2` | FAST-LIVO2 | direct ESKF, multimodal-capable | LiDAR + IMU reference, optional vision profile separated |
| `fast_lio2` | FAST-LIO2 | direct IESKF scan-to-map | classical filter LIO |
| `point_lio` | Point-LIO | point-wise ESKF | high-rate / point-wise LIO |
| `dlio` | DLIO | direct continuous-time LIO | motion-compensation baseline |
| `lio_sam` | LIO-SAM | feature + factor graph | factor-graph LIO |
| `glim_odometry` / `glim_full_slam` | GLIM | direct multi-scan + factor graph | odometry and globally optimized mapping roles |
| `leg_kilo` | current `ouguangjun/Leg-KILO` master | two-stage ESKF + hybrid voxel + backend | modern hybrid LIO/SLAM |
| `kiss_icp` | KISS-ICP | LiDAR-only ICP | LiDAR-only control |

### Research baselines

| ID | Algorithm | Role | Environment policy |
|---|---|---|---|
| `faster_lio` | Faster-LIO | efficiency / sparse-voxel research | official ROS1 Melodic/Noetic path, no hidden Humble port |
| `slict` | SLICT current master | surfel continuous-time optimization | official ROS2 Jazzy path, no hidden Humble port |

Historical `leg_kilo2_lidar_imu` remains a `LEGACY` implementation identity and is never silently relabeled as current `leg_kilo`

## Three comparison views

报告不会把所有结果硬塞进一个总排行榜，而是分开生成：

```text
Common LiDAR + IMU Odometry
System Mapping
Control / Extension
```

例如 KISS-ICP 的 LiDAR-only 结果不会和 LiDAR+IMU 结果伪装成同输入条件，GLIM Full SLAM 也不会当成纯 odometry 排名

## Display Alignment

跨算法展示默认支持：

```text
NONE
START_XY_YAW
```

`START_XY_YAW` 只消除各算法任意的初始 XY 原点与初始 yaw

它**不会**消除：

```text
initial Z
roll / pitch
subsequent drift
scale error
non-rigid map distortion
```

也不会修改：

```text
standardized trajectory
Native Map
Unified Map
scientific metrics
```

Alignment 只作为独立的 derived display metadata 保存，Inspector、Report、Demo 共用同一个显示契约

## Four workflows

```text
Dataset Registry + Algorithm Registry
                 │
      ┌──────────┼──────────┬─────────────┐
      │          │          │             │
 Benchmark    Inspector   Report/Demo   Live Debug
      │          │          │             │
 repeatable   3D compare   paper/GIF    bag + nodes
  runs        same camera   figures      manual debug
```

### 1. Frozen benchmark

```bash
lio-benchmark validate --config experiment.json
lio-benchmark init --config experiment.json --run-id greenhouse_001
lio-benchmark snapshot --run runs/greenhouse_001
lio-benchmark preflight --run runs/greenhouse_001
lio-benchmark run --run runs/greenhouse_001 --algorithm fast_livo2
```

正式 benchmark 默认逐个运行算法，`BAG_PLAY_RATE=1.0`，避免多个前端争用 CPU/GPU 污染运行时间和实时行为

Preflight 会把问题区分为：

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

不会因为算法没安装就伪记为 PASS

### 2. Standardize + Inspector

```bash
lio-benchmark standardize trajectory \
  --run runs/greenhouse_001 \
  --algorithm point_lio \
  --input /path/to/trajectory.csv \
  --source-topic /odom

lio-benchmark standardize map --run runs/greenhouse_001 --algorithm point_lio

lio-benchmark inspect \
  --run runs/greenhouse_001 \
  --map-kind unified \
  --color-mode height \
  --display-alignment START_XY_YAW
```

统一重建使用：

```text
LiDAR timestamp
      ↓
standardized trajectory
      ↓
linear position interpolation
quaternion shortest-arc SLERP
      ↓
canonical calibration
      ↓
Unified Map
```

不再使用旧版“scan 序号按比例对应 pose 序号”

Inspector 支持多算法开关、Native/Unified Map、trajectory overlay、共享 height/intensity 色标、XY/XZ/YZ/Perspective、ROI preset、camera preset 和截图导出

### 3. Paper report / README demo

```bash
lio-benchmark report \
  --run runs/greenhouse_001 \
  --display-alignment START_XY_YAW

lio-benchmark demo \
  --run runs/greenhouse_001 \
  --algorithms fast_livo2 fast_lio2 point_lio leg_kilo \
  --display-alignment START_XY_YAW
```

Report / Demo 使用同一：

```text
frozen run
ROI
map kind
Display Alignment
comparison bounds
height scale
camera path
```

缺失、失败、阻塞结果保持 `MISSING/FAIL/BLOCKED`，不会被写成 0 分

### 4. Live Debug

```bash
lio-benchmark live prepare \
  --dataset greenhouse_mid360 \
  --algorithms fast_livo2 fast_lio2 point_lio \
  --workspace ~/ros2_ws \
  --rate 0.5
```

工具生成可读的 bag/node/session 脚本，而不是把 ROS 进程藏进黑盒 supervisor

发现异常时可以记录：

```bash
lio-benchmark mark \
  --session live_sessions/<session> \
  --algorithm point_lio \
  --event repetitive_row_misregistration \
  --bag-time 84.32 \
  --note "parallel-row alias begins"
```

后续可围绕 marker 对齐局部点云、轨迹与日志

## Standard artifact contract

```text
runs/<run_id>/
├─ manifest.json
├─ configs/generated/<algorithm>/
├─ raw/<algorithm>/
├─ standardized/
│  ├─ trajectories/
│  ├─ map_sampling/selected_scans.csv
│  └─ maps/<algorithm>/
│     ├─ native/
│     │  ├─ map.*
│     │  └─ metadata.json
│     └─ unified/
│        ├─ map.ply
│        └─ metadata.json
├─ metrics/
├─ figures/
│  └─ display_alignment/
├─ reports/
├─ logs/
└─ metadata/algorithms/<algorithm>/
```

旧 V2 路径仍保留兼容入口，例如：

```text
standardized/trajectories/<algorithm>.csv
standardized/maps/<algorithm>/unified_map.ply
standardized/maps/<algorithm>/map_metadata.json
```

## Reproducibility

每个 algorithm × dataset run 尽可能冻结：

```text
source repository / branch / commit
source dirty state
adapter identity
algorithm parameters + hash
effective sensor modalities
canonical calibration source/status
algorithm-specific extrinsic convention
bag identity/hash
bag replay rate
run command
environment snapshot
raw output
standardized output
failures / blockers
```

未知信息写 `UNKNOWN`，不猜

## Verified reference smoke

本仓库已使用真实温室 MID360 bag 完成 FAST-LIVO2 V2 reference smoke：

```text
full replay                 622.99 s
LiDAR frames                6230
standardized trajectory     6227 samples
selected map scans          1246
matched scans               1238 / 1246 = 99.36%
unified map                 772,631 points
```

这一轮证明了真实 bag → trajectory → timestamp association → Unified Map → Inspector / Report 的核心链路

该数据集当时的 LiDAR–IMU 外参数值尚未完成正式确认，因此地图仍按 `DIAGNOSTIC_ONLY / BLOCKED_CALIBRATION` 对待，不把诊断结果包装成正式算法排名

## Repository boundary

本仓库保存：

- benchmark orchestration / registry
- dataset and algorithm contracts
- adapters and explicit compatibility patches
- standardization / calibration / map-sampling logic
- Display Alignment / ROI / camera presets
- Inspector / report / demo generators
- selected small README assets

本仓库不保存大型 rosbag、完整 run PCD/PLY、完整上游算法 clone，也不属于机器人导航 runtime

## Documentation

- [`benchmark_base/docs/V2_WORKFLOW.md`](benchmark_base/docs/V2_WORKFLOW.md) — 当前完整工作流
- [`benchmark_base/docs/adapters/`](benchmark_base/docs/adapters/) — algorithm adapter contracts
- [`benchmark_base/README.md`](benchmark_base/README.md) — run 目录和实验规则
- [`benchmark_base/docs/USER_MANUAL_ZH.md`](benchmark_base/docs/USER_MANUAL_ZH.md) — 原理与历史使用说明
- [`docs/superpowers/specs/2026-08-15-lio-benchmark-v2-design.md`](docs/superpowers/specs/2026-08-15-lio-benchmark-v2-design.md) — V2 design
- [`docs/superpowers/specs/2026-08-15-lio-baseline-suite-design.md`](docs/superpowers/specs/2026-08-15-lio-baseline-suite-design.md) — baseline suite / two-map / Display Alignment contract

## License

Apache-2.0
