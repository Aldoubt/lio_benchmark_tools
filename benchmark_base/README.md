# Benchmark Base

配置驱动的 ROS 2 离线评测基座。manifest v2 固定数据集、单位、外参、算法版本、输入输出话题、runner 和配置；每次实验写入独立、不可覆盖的 run 目录。

## 审阅流程

```bash
source /opt/ros/humble/setup.bash
CFG=benchmark_base/config/navigation_20260719_164431.json

benchmark_base/bin/lio-benchmark validate --config "$CFG"
benchmark_base/bin/lio-benchmark doctor --config "$CFG"
benchmark_base/bin/lio-benchmark commands --config "$CFG"
python3 -m pytest -q
```

`commands` 只打印命令，不运行算法。创建正式 run：

```bash
benchmark_base/bin/lio-benchmark init --config "$CFG" --run-id <unique-id>
benchmark_base/bin/lio-benchmark run --run /home/yangxuan/lio_benchmark_runs/<unique-id> --dry-run
```

用户批准之前不要去掉 `--dry-run`。

## Run 目录

```text
<run>/
├── manifest.json
├── raw/<algorithm>/
├── standardized/trajectories/
├── standardized/maps/
├── metrics/
├── figures/
├── reports/
├── logs/
└── metadata/
```

runner 为每个配置保存实际节点命令、固定 1.0 倍速的播放命令、实际参数副本、ROS 日志、`/usr/bin/time -v` 和退出状态。ROS domain 默认隔离为 77，避免录入工作站上已运行的机器人 `/tf`。

## 分组

- `lidar_only_odometry`：KISS-ICP、MOLA-LO。
- `lidar_imu_odometry`：FAST-LIVO2、Point-LIO、DLIO、GLIM odometry、MOLA-LIO。
- `full_slam`：GLIM full SLAM、LIO-SAM no-loop、LIO-SAM loop。

详细版本、字段、参数与限制见 [ALGORITHM_INTEGRATION.md](docs/ALGORITHM_INTEGRATION.md)。
