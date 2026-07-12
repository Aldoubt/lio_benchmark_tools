# LIO Benchmark Tools

独立于机器人导航与控制系统的 ROS 2 LiDAR-IMU 离线评测工具仓库。

## 仓库边界

本仓库只管理：

- bag、IMU、时间戳和轨迹分析代码；
- FAST-LIVO2、Point-LIO、GLIM、DLIO 的运行适配脚本；
- 标准实验清单、run 目录契约和报告模板；
- 为上游 ROS 2 分支准备的、可审计的必要补丁。

本仓库不管理：

- rosbag2、PCD、PLY、PNG 等数据或结果；
- ROS `build/`、`install/`、`log/`；
- FAST-LIVO2、Point-LIO、GLIM、DLIO 的完整源码 clone；
- 导航、Nav2、底盘驱动和控制系统源码。

## 目录

```text
lio_benchmark_tools/
├── benchmark_base/     # 配置驱动的实验编排
├── evaluators/         # 分析器、转换器和算法运行适配
└── patches/            # 上游算法必要补丁
```

## 在任意 ROS 2 工作区使用

```bash
git clone <your-lio-benchmark-tools-url>
cd /path/to/ros2_ws

/path/to/lio_benchmark_tools/benchmark_base/bin/lio-benchmark validate \
  --config /path/to/experiment.json
```

实验清单中的 `workspace` 指向算法所在 ROS 2 工作区；工具仓库不要求放在工作区内部。当前为了便于迁移，暂放在 `/home/yangxuan/ros2_ws/lio_benchmark_tools`，它自身有独立 `.git`，并被父仓库忽略。

详细流程见 [benchmark_base/README.md](benchmark_base/README.md)，当前 MID360 基线见 [benchmark_base/docs/CURRENT_BASELINE.md](benchmark_base/docs/CURRENT_BASELINE.md)。

## DLIO 说明

当前 DLIO ROS 2 `feature/ros2` 分支处理大纪元 Livox 纳秒时间时需要补丁：

```bash
git -C /path/to/direct_lidar_inertial_odometry apply \
  /path/to/lio_benchmark_tools/patches/dlio_ros2/mid360_time_handling.patch
```

应用前应确认目标 commit，并将 patch 状态写入实验快照。

