# LIO Benchmark Tools

**Reproducible same-bag LiDAR–Inertial benchmarking for real agricultural environments**

这个仓库用于回答一个实际问题：**同一份真实 rosbag、同一套标定和相同地图重建口径下，不同 LIO / LiDAR–IMU SLAM 前端究竟会产生什么差异？**

它不是一个新的里程计算法，而是一套把“运行算法、冻结实验、标准化轨迹/地图、看点云差异、生成论文图、实时排查失效”解耦起来的研究工具。

## Same-bag visual comparison

真实 GIF 由同一个 frozen run 自动生成，不手工换视角、不删除失败区域：

```bash
benchmark_base/bin/lio-benchmark demo \
  --run /path/to/frozen/run \
  --output assets/demo/same_bag_map_comparison.gif
```

生成并确认内容后，仓库主页使用 GitHub README 的相对图片路径展示：

```markdown
![Same-bag LIO map comparison](assets/demo/same_bag_map_comparison.gif)
```

> 当前分支没有伪造占位 benchmark GIF；请先在本机对真实 bag 生成并审查该文件，再提交它。生成规则见 [`assets/demo/README.md`](assets/demo/README.md)。

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

### 1. Benchmark

```bash
lio-benchmark validate --config experiment.json
lio-benchmark init --config experiment.json --run-id gaas_a_001
lio-benchmark snapshot --run runs/gaas_a_001
lio-benchmark run-all --run runs/gaas_a_001
```

正式性能 benchmark 默认逐个运行算法，避免多个前端争用 CPU/GPU 后污染运行时间和实时行为。

### 2. Standardize + Inspector

```bash
lio-benchmark standardize trajectory \
  --run runs/gaas_a_001 \
  --algorithm point_lio \
  --input /path/to/point_lio_trajectory.csv \
  --source-topic /aft_mapped_to_init

lio-benchmark standardize map --run runs/gaas_a_001 --algorithm point_lio
lio-benchmark inspect --run runs/gaas_a_001 --color-mode height
```

V2 的统一地图使用 **LiDAR timestamp → trajectory timestamp interpolation**，位置线性插值、姿态 quaternion SLERP；不再使用旧脚本里的“scan 序号按比例对应 pose 序号”。

Inspector 支持：

- 多算法地图开关与叠加
- unified / native map 入口
- trajectory overlay
- height / intensity / algorithm coloring
- XY / XZ / YZ / perspective 固定视角
- ROI JSON preset
- camera JSON preset
- 保存当前相机 preset
- 导出当前截图

所有算法位于同一个 Open3D scene，因此切换显示时共享同一相机。

### 3. Paper report / README demo

```bash
lio-benchmark report --run runs/gaas_a_001
lio-benchmark demo --run runs/gaas_a_001 --algorithms fast_livo2 point_lio leg_kilo2_lidar_imu
```

输出包括 standardized trajectory/map 状态、地图对比图、轨迹图、运行时间、summary CSV、Markdown/HTML 报告，以及可选 README GIF。缺失结果会显示为 `MISSING/INVALID/FAIL`，不会被写成 0 分。

### 4. Live Debug

```bash
lio-benchmark live prepare \
  --dataset gaas_handheld_a \
  --algorithms fast_livo2 point_lio leg_kilo2_lidar_imu \
  --workspace ~/ros2_ws \
  --rate 0.5
```

工具生成一个可读 session，而不是把所有 ROS 进程藏在黑盒 supervisor 中：

```text
live_sessions/<session>/
├─ session.json
├─ env.sh
├─ 01_bag_play.sh
├─ 02_fast_livo2.sh
├─ 03_point_lio.sh
├─ 04_leg_kilo2_lidar_imu.sh
├─ commands.md
├─ logs/
├─ markers/
└─ rviz/
```

你可以分别开终端、慢放/暂停 bag、重启单个 estimator、检查 topic/TF，并用：

```bash
lio-benchmark mark \
  --session live_sessions/<session> \
  --algorithm <id> \
  --event repetitive_row_misregistration \
  --bag-time 84.32 \
  --note "parallel-row alias begins"
```

记录失效时间点，供后续提取局部点云、轨迹和日志。

## Fixed baselines

| Baseline | Benchmark role | Required input | Important note |
|---|---|---|---|
| FAST-LIVO2 | primary multimodal-capable front end | LiDAR + IMU | camera capability is recorded separately; LiDAR-IMU-only runs are not mislabeled visual |
| Point-LIO | point-wise LIO baseline | LiDAR + IMU | fixed same-bag baseline |
| Leg-KILO 2.0 | KILO-family baseline | LiDAR + IMU | common handheld benchmark fixes `leg_kinematics=false` |
| GLIM Odometry | optimization-based odometry entry | LiDAR + IMU | kept separate from global SLAM |
| GLIM Full SLAM | global-optimization entry | LiDAR + IMU | not directly ranked as if it were pure odometry |
| DLIO | direct LiDAR–inertial baseline | LiDAR + IMU | MID360 time/unit patches remain explicit provenance |

Leg-KILO 的本机 ROS1/ROS2 运行方式通过显式 adapter 记录，不在 benchmark 仓库里偷偷修改上游源码，详见 [`benchmark_base/docs/LEG_KILO_ADAPTER.md`](benchmark_base/docs/LEG_KILO_ADAPTER.md)。

## Standard artifact contract

```text
runs/<run_id>/
├─ manifest.json
├─ raw/<algorithm>/
├─ standardized/
│  ├─ trajectories/<algorithm>.csv
│  ├─ maps/<algorithm>/unified_map.ply
│  └─ maps/<algorithm>/map_metadata.json
├─ metrics/
├─ figures/
├─ reports/
├─ logs/
└─ metadata/
```

每张标准地图明确记录：

```text
map_source = NATIVE | UNIFIED_RECONSTRUCTION
algorithm_id
dataset_id
trajectory_source
voxel_m
point_count
timestamp matching statistics
generation command
```

原生算法地图和统一重建地图不会被悄悄混为同一种结果。

## Repository boundary

本仓库保存：

- benchmark orchestration / registry
- evaluation and standardization code
- algorithm adapters and audited patches
- ROI/camera presets
- paper/report/demo generators
- selected small README demo assets

本仓库**不保存**大型 rosbag、PCD/PLY run outputs、完整上游算法 clone，也不属于 Nav2、底盘控制或在线导航 runtime。

## Documentation

- [`benchmark_base/docs/V2_WORKFLOW.md`](benchmark_base/docs/V2_WORKFLOW.md) — V2 完整工作流
- [`benchmark_base/README.md`](benchmark_base/README.md) — run 目录与实验规则
- [`benchmark_base/docs/USER_MANUAL_ZH.md`](benchmark_base/docs/USER_MANUAL_ZH.md) — 历史原理/使用说明
- [`benchmark_base/docs/CURRENT_BASELINE.md`](benchmark_base/docs/CURRENT_BASELINE.md) — 旧 MID360 exploratory baseline
- [`docs/superpowers/specs/2026-08-15-lio-benchmark-v2-design.md`](docs/superpowers/specs/2026-08-15-lio-benchmark-v2-design.md) — V2 design contract

## License

Apache-2.0
