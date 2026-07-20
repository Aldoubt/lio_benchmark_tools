# LIO Benchmark Tools 中文使用手册

## 1. 环境与部署

目标系统是 Ubuntu 22.04、ROS 2 Humble、Python 3、CMake 和 colcon。算法源码应放在独立 overlay，例如 `/home/yangxuan/lio_benchmark_algorithms/<algorithm>_ws`；路径只写入 dataset manifest，不写进通用脚本。

本机已固定 KISS-ICP v1.3.0、MOLA Humble 2.9.0/LO 2.2.1、LIO-SAM ros2、Point-LIO ROS2 fork、DLIO feature/ros2、GLIM v1.2.2 和 gtsam_points v1.2.2。精确 commit、依赖、补丁和已知限制见 `ALGORITHM_INTEGRATION.md`。

## 2. 新数据集

输入是包含 `metadata.yaml` 的 rosbag2 目录。先生成 manifest：

```bash
benchmark_base/bin/lio-benchmark create-manifest \
  --bag /path/to/bag_dir \
  --output benchmark_base/config/my_dataset.json
```

自动无法确认的 IMU 单位、时间语义和外参会保留为 `UNRESOLVED`，必须由标定或只读数据分析确认，不能猜测。

## 3. 预检

```bash
source /opt/ros/humble/setup.bash
benchmark_base/bin/lio-benchmark validate --config <manifest.json>
benchmark_base/bin/lio-benchmark doctor --config <manifest.json>
```

doctor 检查 ROS/Python、bag storage、metadata、话题类型、输出权限、setup、runner、配置和算法可执行文件。缺少真值不阻止算法运行，但禁止真值指标；缺少可靠 LiDAR–IMU 外参时只能运行 LiDAR-only 组。

## 4. 输入适配

当前 MID360 CustomMsg 适配器输出：

```text
x/y/z/intensity: FLOAT32
ring: UINT16，来自真实 line
time: FLOAT32，扫描帧头后的秒
```

原始 line 交错会导致点数组时间倒退，因此适配器按 `offset_time` 稳定排序。需要 SI 的算法使用 IMU scaler 将 g 乘 9.80665；FAST-LIVO2 与 Point-LIO 使用各自已验证的 g 配置。

## 5. 创建和审阅 run

```bash
benchmark_base/bin/lio-benchmark init --config <manifest.json> --run-id <unique-id>
benchmark_base/bin/lio-benchmark commands --run <run-dir>
benchmark_base/bin/lio-benchmark run --run <run-dir> --dry-run
```

run 不允许覆盖。正式运行前应审阅冻结的 manifest、每个配置和打印出的命令。

## 6. 实验顺序

先跑 30–60 秒 smoke，检查输入计数、首次有效位姿、时间连续性、NaN/Inf、异常跳变、CPU/RSS 和退出状态。只有用户审阅通过后才跑完整 bag。完整实验固定 1.0 倍速，并建议每个配置重复三次。

## 7. 评测口径

轨迹按真实传感器时间排序，剔除零时间、报告重复和倒退。多算法仅比较共同有效时间区间。地图通过线性平移 + 四元数 SLERP 插值，并应用完整旋转和平移外参。

有真值时可做 SE(3) 对齐和 ATE/RPE；无真值时只报告轨迹覆盖率、路径长度、Z/姿态范围、闭环端点差和地图一致性 proxy，均标记为 diagnostic。

## 8. 当前审阅入口

当前 manifest 是 `benchmark_base/config/navigation_20260719_164431.json`，suite 是 `benchmark_base/suites/greenhouse_v1.yaml`，状态为 `PRE_RUN_REVIEW_REQUIRED`。本阶段没有执行 bag playback。
