# LIO Benchmark Tools

ROS 2 Humble 离线 LiDAR/LIO/SLAM 多算法评测框架。当前仓库已经接入并跑通 10 个独立实验配置：KISS-ICP、MOLA-LO、MOLA-LIO、FAST-LIVO2、Point-LIO、DLIO、GLIM odometry、GLIM full SLAM、LIO-SAM no-loop 和 LIO-SAM loop。

这里的“10 个算法”更准确地说是 7 个算法家族下的 10 个可复现实验配置：GLIM odometry/full SLAM、LIO-SAM no-loop/loop、MOLA-LO/MOLA-LIO 分别是同一算法家族下的不同使用策略。框架的目标不是给出没有真值支撑的绝对排名，而是把输入契约、版本、参数、资源消耗、轨迹健康和相对地图诊断固定下来，让不同策略能在同一 bag 上被审计、复现和继续调参。

Git 跟踪部分只保存编排代码、manifest、参数、测试和必要 patch；外部算法源码、bag 原始数据、构建目录和完整运行产物不进入 Git。当前工作区的 `artifacts/` 是用于查看本轮结果的本机归档，外部工作区路径全部由 manifest 注入。

## 当前基线

当前完整对比结果归档在：

```text
artifacts/mapping_20260719_172810_full807_gravity_compare_002
```

这份归档是一个组合结果：大部分算法来自 `/home/yangxuan/lio_benchmark_runs/mapping_20260719_172810_full807_round1_001`，MOLA-LIO 覆盖为打开重力补偿后的 `/home/yangxuan/lio_benchmark_runs/mapping_20260719_172810_mola_gravity_full807_001`。组合后的标准化轨迹、地图、资源曲线和报告都已经重新生成。

| 项 | 值 |
|---|---|
| 结果版本 | `mapping_20260719_172810_full807_gravity_compare_002`，生成于 2026-07-22 |
| 运行状态 | `completed` |
| 数据集 | `date/mapping_20260719_172810` |
| rosbag2 storage | `sqlite3` |
| 时长 | `807.45 s` |
| 消息数 | `344567` |
| LiDAR | Livox MID360 CustomMsg，`/agt/sensors/lidar/custom` |
| IMU | `sensor_msgs/msg/Imu`，`/agt/sensors/imu/data` |
| 点时间 | `offset_time`，单位 ns，相对帧头 |
| IMU 加速度 | 原始单位为 `g`；需要 SI 的算法由 runner 转为 m/s^2 |
| 评测真值 | 无独立 ground truth |
| 回放 | `1.0x`，使用 `/clock`，串行运行算法 |

查看当前结果：

```bash
cd /home/yangxuan/lio_benchmark_tools

benchmark_base/bin/lio-benchmark-viewer \
  --run artifacts/mapping_20260719_172810_full807_gravity_compare_002
```

只显示部分算法：

```bash
benchmark_base/bin/lio-benchmark-viewer \
  --run artifacts/mapping_20260719_172810_full807_gravity_compare_002 \
  --algorithms fast_livo2,glim_odometry,mola_lio
```

查看器中的 Point-LIO 和 DLIO 会因为轨迹健康标记默认隐藏。需要复核它们时可以手动勾选，但异常尺度会压缩正常轨迹的显示范围。

## 版本锁定

本轮实验使用 Ubuntu 22.04、ROS 2 Humble。机器可读版本锁定文件是 [mapping_20260719_172810_versions.lock.json](benchmark_base/config/mapping_20260719_172810_versions.lock.json)，人工可读说明见 [十算法 ROS 2 版本锁定](benchmark_base/docs/ALGORITHM_VERSIONS_ROS2_HUMBLE.md)。迁移到另一台机器时，commit、patch 和参数文件应保持不变，只替换 manifest 中的绝对路径。

| 配置 | 分组 | 版本/来源 | 固定引用 | 本仓库额外 patch |
|---|---|---|---|---|
| KISS-ICP | LiDAR-only odometry | PRBonn/kiss-icp v1.3.0 | `b1683528` | 无 |
| MOLA-LO | LiDAR-only odometry | MOLA Humble binary：`mola_launcher 2.9.0`、`mola_lidar_odometry 2.2.1` | binary | 无 |
| MOLA-LIO | LiDAR-IMU odometry | MOLA Humble binary：`mola_launcher 2.9.0`、`mola_state_estimation 2.4.2`、`mola_lidar_odometry 2.2.1` | binary | 无 |
| FAST-LIVO2 | LiDAR-IMU odometry | `fast_livo` package，来自 `agt_navigation_v2` | `1e96f08f` | 无 |
| Point-LIO | LiDAR-IMU odometry | `point_lio` ROS 2 fork | `a8e2d0d5` | 无 |
| DLIO | LiDAR-IMU odometry | `direct_lidar_inertial_odometry` 1.1.1，`feature/ros2` | `c8acc371` | [spaciousness_bounds.patch](patches/dlio/spaciousness_bounds.patch) |
| GLIM odometry | LiDAR-IMU odometry | GLIM v1.2.2 CPU odometry | `faa264a1` | [gtsam_points_v1.2.2_boost_none.patch](patches/glim/gtsam_points_v1.2.2_boost_none.patch) |
| GLIM full SLAM | Full SLAM | GLIM v1.2.2 CPU full SLAM | `faa264a1` | [gtsam_points_v1.2.2_boost_none.patch](patches/glim/gtsam_points_v1.2.2_boost_none.patch) |
| LIO-SAM no-loop | Full SLAM | LIO-SAM ROS 2 package 1.0.0 | `08af3f32` | 无 |
| LIO-SAM loop | Full SLAM | LIO-SAM ROS 2 package 1.0.0 | `08af3f32` | 无 |

完整 40 位 commit、仓库 URL、分支、依赖和补丁说明以版本锁定 JSON 及每个 run 内冻结的 `manifest.json` 为准。DLIO 和 GLIM 的 patch 是构建前提，不能只 checkout 上游 commit。

## 十个配置的经典思路与本轮使用策略

所有配置的共同边界是：有效距离 `0.5--70 m`；逐点时间保留真实 `offset_time`；通用 PointCloud2 适配器输出 `x/y/z/intensity: float32`、`ring: uint16`、`time: float32 s`；IMU 算法使用已确认的 LiDAR--IMU 外参。FAST-LIVO2 使用原生 CustomMsg 输入；LIO-SAM 使用独立 MID360 适配器。下面的“经典之处”描述算法设计取向，“本轮策略”描述实际启用的配置，二者不要混为一谈。

### KISS-ICP

KISS-ICP 的特点是保持 LiDAR-only 里程计的最小必要复杂度：体素化局部地图、ICP 扫描匹配和自适应阈值组成一个紧凑的前端。它适合用作不依赖 IMU 的基准，也适合内存极紧的场景。

本轮启用扫描 deskew、`0.5 m` 体素地图、自适应阈值和 `0.5--70 m` 距离裁剪，不订阅 IMU。它回答的是“仅靠 LiDAR 匹配能到什么程度”，不应期待重力约束带来的竖直稳定性。

### MOLA-LO

MOLA-LO 的经典点在于模块化的 LiDAR 里程计流水线和 GICP 局部地图匹配。它把里程计、地图管理和传感器模型配置解耦，便于替换管线或在工程系统中组合。

本轮使用 `lidar3d-gicp.yaml`、线性 deskew 和最少 2 个邻近位姿构成局部地图；不使用 IMU。这个配置与 MOLA-LIO 构成“LiDAR-only 与 LiDAR-IMU”对照，但两者不是严格的单变量 A/B，不能把差异完全归因于某一个开关。

### MOLA-LIO

MOLA-LIO 在 MOLA 的局部地图/GICP 流水线上加入状态估计和 IMU 约束。它的关键价值是把 IMU deskew、姿态初始化和重力观测纳入 LiDAR 里程计，而不是仅依赖几何匹配。

本轮使用 SI IMU、IMU deskew、加速度 pitch/roll 初始化和 `imu_gravity_correction=true`，外参按 MOLA 定义注入。重力补偿主要改善 roll/pitch 可观性；它不能替代时间同步、平移外参、动态加速度建模或匹配退化处理。

### FAST-LIVO2

FAST-LIVO2 的原始设计是紧耦合 LiDAR--IMU--视觉里程计，核心取向是用迭代状态估计和局部地图高频更新同时处理多传感器约束。它的视觉通道是算法能力的一部分，但并非本轮比较输入。

本轮仅启用 LiDAR 和 IMU，`img_en=0`，保留重力估计/对齐、静态外参和局部地图迭代；相机参数仅用于满足上游节点初始化，不接收图像。因此本轮结论只适用于该项目的 LiDAR--IMU 使用方式，不能外推成 FAST-LIVO2 的视觉模式结论。

### Point-LIO

Point-LIO 的代表性思路是把 LiDAR 约束尽可能下沉到逐点级别，与 IMU 状态估计紧耦合，而不是只在整帧结束后做一次扫描级修正。它追求高带宽运动下的实时里程计能力，对点时间、扫描模型和 IMU 噪声设定也更敏感。

本轮使用 PointCloud2 适配输入、4 线 MID360 配置、重力对齐和固定外参；关闭无关的 `nav_msgs/Path` 累积发布以避免长 bag 的消息增长。当前结果发散，说明这套输入契约/参数组合还不能作为可用配置，不能据此否定 Point-LIO 的通用方法。

### DLIO

DLIO 的策略是直接 LiDAR--IMU 里程计：使用逐点时间进行 deskew，并配合体素化、自适应模式和空间/密度管理来维持匹配。它的优势在于直接处理连续运动下的点云约束，代价是系统面较大，对时间字段、外参和资源更敏感。

本轮输入为相对秒 PointCloud2、SI IMU 和按上游定义的逆向外参；开启 deskew、voxelization、adaptive 与 IMU calibration。为修复首帧上游 spaciousness 边界越界，构建时应用了记录在仓库内的单行 patch；这不改变算法策略，但属于可复现性的一部分。

### GLIM odometry

GLIM 将 LiDAR--IMU 里程计、局部建图、全局建图和位姿图优化拆分为可组合的模块。odometry 变体的重点是只保留前端状态估计，用较低的内存和时延提供局部里程计，而不是维护全局一致地图。

本轮使用 CPU 配置、逐点相对时间、SI IMU 和 `T_lidar_imu` 外参；关闭 local mapping 与 global mapping。它是“只要稳定导航前端”的 GLIM 基线。

### GLIM full SLAM

GLIM full SLAM 使用和 odometry 相同的前端，但打开局部子图、全局建图和位姿图校正。这一变体的经典取舍是以更多内存和后端工作换取闭环后的全局一致性。

本轮仍使用 CPU 前端、同一 LiDAR/IMU 输入契约和外参，只把 `enable_local_mapping` 与 `enable_global_mapping` 设为 true。因此它和 GLIM odometry 的对比直接反映是否维护全局建图后端的资源代价。

### LIO-SAM no-loop

LIO-SAM 的经典结构是特征提取、IMU 预积分和因子图优化，利用关键帧地图将局部 LiDAR 约束与 IMU 状态联系起来。no-loop 变体关闭回环，保留实时前端和因子图建图主链路。

本轮用独立适配器把 MID360 的真实 line 和相对秒送入 LIO-SAM，配置为 `N_SCAN=4`、GPS 禁用、4 核、`0.15 s` mapping interval，loop closure 关闭。MID360 的非重复扫描模式与经典机械式多线雷达模型并不完全等价，因此这个适配是重要的兼容性风险点。

### LIO-SAM loop

LIO-SAM loop 与 no-loop 使用同一前端和 IMU 预积分策略，差异是启用历史关键帧检索、ICP 验证和图优化闭环。它适合验证“闭环后端能否改善长路径全局一致性”，而不是替代传感器前端的正确 deskew 和标定。

本轮与 no-loop 共享输入、外参、特征阈值和 mapping 频率，只额外开启 `loopClosureEnableFlag=true`，搜索频率为 `1 Hz`。因此二者可以用于观察回环本身的资源和终点诊断变化。

## 当前 bag 的实测结论

下表来自归档的 [综合报告](artifacts/mapping_20260719_172810_full807_gravity_compare_002/reports/comprehensive_comparison.md)。`相对 FAST RMSE` 是初始 yaw 和平移对齐到 FAST-LIVO2 后的诊断量；它不是 ATE，也不是绝对精度。CPU 是算法进程树的逻辑 CPU 总和，`100%` 约等于一个逻辑核。

| 配置 | 健康状态 | 相对 FAST RMSE (m) | Z range (m) | 平均 CPU | 峰值 RSS (MiB) |
|---|---|---:|---:|---:|---:|
| KISS-ICP | 正常 | 2.107 | 13.756 | 102.0% | 96.5 |
| MOLA-LO | 正常 | 2.235 | 13.420 | 74.1% | 1569.1 |
| MOLA-LIO | 正常，观察对象 | 0.810 | 0.934 | 90.9% | 1072.1 |
| FAST-LIVO2 | 正常 | 0.000 | 0.637 | 124.3% | 976.2 |
| Point-LIO | 轨迹过短、发散 | 12619.424 | 15148.029 | 29.3% | 446.6 |
| DLIO | 发散 | 20.429 | 46.415 | 109.6% | 4142.6 |
| GLIM odometry | 正常 | 0.110 | 0.842 | 86.1% | 274.0 |
| GLIM full SLAM | 正常 | 0.177 | 0.767 | 87.0% | 981.6 |
| LIO-SAM no-loop | 正常 | 2.398 | 11.657 | 88.7% | 489.0 |
| LIO-SAM loop | 正常 | 2.544 | 11.737 | 97.1% | 481.8 |

对这一个 bag 和这一组参数，可以得出的结论是：

- **FAST-LIVO2 是当前导航前端首选。** 在不使用视觉输入的前提下，它的轨迹覆盖约 805.5 s、路径约 197.0 m、Z range 为 0.637 m，是稳定组中最小；代价是约 124.3% 平均 CPU 和约 976 MiB 峰值 RSS。
- **GLIM odometry 是当前最好的内存/稳定性折中。** 它相对 FAST-LIVO2 的诊断 RMSE 为 0.110 m、Z range 为 0.842 m，峰值 RSS 只有约 274 MiB。它关闭了全局建图，因此适合局部导航前端，不是闭环全局地图方案。
- **GLIM full SLAM 是当前全局建图首选。** 与 GLIM odometry 相比，打开 local/global mapping 和位姿图后峰值 RSS 增至约 982 MiB，但轨迹诊断仍稳定，适合需要闭环一致地图的场景。
- **MOLA-LIO 的重力补偿带来了明显的竖直改善，但仍需专项复核。** 其 Z range 为 0.934 m，远小于 MOLA-LO 的 13.420 m；不过两者模式并不只差一个变量，且 MOLA-LIO 相对 FAST-LIVO2 的诊断 RMSE 为 0.810 m、峰值 RSS 约 1.07 GiB，所以目前列为观察对象。
- **LiDAR-only 的 KISS-ICP 和 MOLA-LO 可作为无 IMU 基线，不应和 LiDAR--IMU 组做绝对总排名。** 两者路径长度仍处于正常环境尺度，但 Z range 约 13--14 m，表明这一数据上的竖直方向受限于没有 IMU 重力约束或等效约束。
- **Point-LIO 与 DLIO 不能因进程退出码为 SUCCESS 就进入候选。** Point-LIO 的路径长度约 63.6 km、Z range 约 15.1 km 且轨迹未覆盖完整 bag；DLIO 路径约 11.1 km、峰值 RSS 约 4.14 GiB、79 线程，并在标准化时清理了 903 个零/重复时间戳。这些都属于发散/异常信号，低 CPU 不是效率优势。
- **LIO-SAM 的 loop 变体降低了终点位移，但没有解决本轮竖直诊断。** no-loop/loop 的终点位移约为 1.44/0.57 m，平均 CPU 约为 88.7%/97.1%，而两者 Z range 都约为 11.7 m。回环后端不能替代可靠的逐点时间、IMU 和外参处理。

这些结论不等价于绝对精度排名：没有独立真值，不能把相对 RMSE、路径长度、Z range 或地图范围写成 ATE/RPE。单次完整回放也不能估计重复实验方差；最终上机选型应在目标设备、热稳态和至少三次重复实验下复测。

## 评测口径与公平性边界

- 所有算法以 `--rate 1.0 --clock` 回放；算法进程串行运行，避免互相抢占资源。
- LiDAR-only odometry、LiDAR--IMU odometry、full SLAM 分组报告；禁止跨组做一个总排名。
- 原始 MID360 点云经适配时保留真实 line 和 `offset_time`，按点相对时间稳定排序，不伪造 ring。
- 地图比较并不读取各算法内部地图：它将同一份原始点云按各算法的标准化轨迹、真实时间戳、平移插值、姿态 SLERP 和完整 SE(3) 外参重建，再以统一采样和 `0.12 m` voxel 下采样。因此它适合发现轨迹造成的 Z 漂移、回环错位和发散，不评价内部地图纹理或地图更新速度。
- 无独立真值时只输出轨迹覆盖率、路径长度、姿态/Z 范围、闭环端点差和地图一致性 proxy 等诊断量；不生成 ATE/RPE 或绝对精度结论。
- 运行失败、输入不兼容或轨迹健康异常应保留明确状态，不生成伪结果或用资源数据掩盖异常。

## 复现和运行

在当前机器上先准备 ROS 2 Humble、外部算法工作区、bag 和 adapter workspace。外部源码的精确版本、依赖、补丁和已知限制见 [算法部署与接入记录](benchmark_base/docs/ALGORITHM_INTEGRATION.md)。

```bash
cd /home/yangxuan/lio_benchmark_tools
source /opt/ros/humble/setup.bash

benchmark_base/bin/lio-benchmark validate \
  --config benchmark_base/config/mapping_20260719_172810.json

benchmark_base/bin/lio-benchmark doctor \
  --config benchmark_base/config/mapping_20260719_172810.json

benchmark_base/bin/lio-benchmark commands \
  --config benchmark_base/config/mapping_20260719_172810.json

python3 -m pytest -q
```

验证通过后必须使用新的 run ID，不能覆盖归档结果：

```bash
benchmark_base/bin/lio-benchmark init \
  --config benchmark_base/config/mapping_20260719_172810.json \
  --run-id mapping_20260719_172810_full807_reproduction_001

benchmark_base/bin/lio-benchmark run \
  --run /home/yangxuan/lio_benchmark_runs/mapping_20260719_172810_full807_reproduction_001
```

正式完整回放前应先对候选算法运行 30--60 s smoke，检查输入帧数、首个有效位姿、时间连续性、NaN/Inf、异常跳变、CPU/RSS 和退出状态。若要人工控制单算法生命周期，使用 GUI：

```bash
benchmark_base/bin/lio-benchmark-gui \
  --run /home/yangxuan/lio_benchmark_runs/mapping_20260719_172810_full807_reproduction_001
```

在 GUI 中选择 pending/failed 算法，依次点击“初始化/准备算法”和“开始播放”；“停止并保存”会收尾 recorder、算法和适配器，并写入 `run_result.json`。队列模式会按列表顺序等待当前算法完整收尾、校验和清理后再运行下一个，进度写入 `metadata/run_queue.json`。无 DISPLAY 时可使用：

```bash
python3 evaluators/manual_run_controller.py \
  --run /home/yangxuan/lio_benchmark_runs/mapping_20260719_172810_full807_reproduction_001 \
  --algorithm point_lio prepare
```

报告与可视化的产物包括 `manifest.json`、`metrics/`、`figures/`、`reports/`、`standardized/` 和 `raw/`。当前归档的详细分析可直接阅读：[综合报告](artifacts/mapping_20260719_172810_full807_gravity_compare_002/reports/comprehensive_comparison.md)、[机器可读结果](artifacts/mapping_20260719_172810_full807_gravity_compare_002/reports/comprehensive_comparison.json)、[资源汇总](artifacts/mapping_20260719_172810_full807_gravity_compare_002/figures/resource_curves/resource_summary.json)。

## 其他文档

- [中文使用手册](benchmark_base/docs/USER_MANUAL_ZH.md)
- [实验协议](benchmark_base/docs/EXPERIMENT_PROTOCOL.md)
- [实现审计](benchmark_base/docs/IMPLEMENTATION_AUDIT.md)
- [数据集要求](benchmark_base/docs/DATASET_REQUIREMENTS.md)
- [MID360 与 LIO-SAM 限制](benchmark_base/docs/MID360_LIO_SAM_LIMITATIONS.md)
- [当前基线和后续工作](benchmark_base/docs/CURRENT_BASELINE.md)
