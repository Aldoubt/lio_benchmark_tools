# LIO Benchmark Tools

ROS 2 Humble 离线 LiDAR/LIO/SLAM 评测工具。当前分支已部署并登记 10 个独立实验配置：KISS-ICP、MOLA-LO、MOLA-LIO、FAST-LIVO2、Point-LIO、DLIO、GLIM odometry、GLIM full SLAM、LIO-SAM no-loop 和 LIO-SAM loop。

仓库只保存编排代码、manifest、参数、测试和必要 patch；外部算法源码、bag、构建目录和运行结果不进入 Git。外部工作区路径全部由 manifest 注入。

## 可迁移复现与版本锁定

本仓库当前锁定的十算法实验使用 ROS 2 Humble（ROS_VERSION=2）。算法源码的仓库、分支、40 位 commit、MOLA Humble 二进制包版本和 DLIO/GLIM patch 见 [十算法 ROS 2 版本锁定](benchmark_base/docs/ALGORITHM_VERSIONS_ROS2_HUMBLE.md) 及机器可读的 [版本锁定 JSON](benchmark_base/config/mapping_20260719_172810_versions.lock.json)。本次完整结果对应 `mapping_20260719_172810_full807_round1_001`。

迁移电脑时，先按锁定清单准备 ROS 2 Humble 和外部算法工作区，再把 `benchmark_base/config/mapping_20260719_172810.json` 中原电脑的绝对路径替换为新电脑路径。至少需要替换仓库根目录、算法工作区根目录、数据集目录和结果目录；不要修改算法的 `branch`、`commit`、参数文件和 patch 列表。

```bash
source /opt/ros/humble/setup.bash
benchmark_base/bin/lio-benchmark validate \
  --config benchmark_base/config/mapping_20260719_172810.json
benchmark_base/bin/lio-benchmark doctor \
  --config benchmark_base/config/mapping_20260719_172810.json
benchmark_base/bin/lio-benchmark commands \
  --config benchmark_base/config/mapping_20260719_172810.json
python3 -m pytest -q
```

验证通过后，使用新的唯一 run ID 执行完整实验；不要覆盖归档目录：

```bash
benchmark_base/bin/lio-benchmark init \
  --config benchmark_base/config/mapping_20260719_172810.json \
  --run-id mapping_20260719_172810_full807_reproduction_001
benchmark_base/bin/lio-benchmark run \
  --run /home/yangxuan/lio_benchmark_runs/mapping_20260719_172810_full807_reproduction_001
```

完成后可用 `benchmark_base/bin/lio-benchmark-viewer --run <run>` 查看三维点云、路径和右侧性能曲线；结果归档应包含该 run 的 `manifest.json`、`metrics/`、`figures/`、`reports/`、`standardized/` 和 `raw/`。

## 当前 MID360 检查点

```bash
source /opt/ros/humble/setup.bash

benchmark_base/bin/lio-benchmark validate \
  --config benchmark_base/config/navigation_20260719_164431.json

benchmark_base/bin/lio-benchmark doctor \
  --config benchmark_base/config/navigation_20260719_164431.json

benchmark_base/bin/lio-benchmark commands \
  --config benchmark_base/config/navigation_20260719_164431.json
```

当前状态是 `PRE_RUN_REVIEW_REQUIRED`：编译、配置、输入字段抽样和无 bag 节点启动已完成；尚未播放 bag。用户审阅后先执行 30–60 秒 smoke，再决定是否跑完整数据。

关键文档：

- [实现审计](benchmark_base/docs/IMPLEMENTATION_AUDIT.md)
- [算法部署与参数](benchmark_base/docs/ALGORITHM_INTEGRATION.md)
- [实验协议](benchmark_base/docs/EXPERIMENT_PROTOCOL.md)
- [MID360/LIO-SAM 限制](benchmark_base/docs/MID360_LIO_SAM_LIMITATIONS.md)
- [中文手册](benchmark_base/docs/USER_MANUAL_ZH.md)

## 公平性底线

- 所有 bag 播放固定 `--rate 1.0 --clock`。
- LiDAR-only、LiDAR–IMU odometry、full SLAM 分组，不做跨组总排名。
- 地图使用真实时间戳、SLERP 和完整 SE(3) 外参，不按轨迹百分比配扫描。
- 无独立真值时只输出 diagnostic，不生成 ATE/RPE 或“绝对精度”。
- 任何不兼容或失败配置输出明确失败状态，不生成伪结果。

## 手动 GUI

```bash
source /opt/ros/humble/setup.bash
benchmark_base/bin/lio-benchmark-gui \
  --run /home/yangxuan/lio_benchmark_runs/navigation_20260721_full2604_round1_001
```

选择 pending/failed 算法后依次点击“初始化/准备算法”和“开始播放”。“停止并保存”会收尾 recorder、算法和适配器，并写入 `run_result.json`；失败算法重试会进入 `raw/<algorithm>/attempt_<timestamp>_<pid>`，不会覆盖旧日志。无 DISPLAY 时可用同一生命周期的命令行入口：

```bash
python3 evaluators/manual_run_controller.py \
  --run /home/yangxuan/lio_benchmark_runs/navigation_20260721_full2604_round1_001 \
  --algorithm point_lio prepare
```

命令行 `prepare` 等待输入 `play` 或 `stop`；`run --auto-play --duration 20` 可执行短 smoke。报告按钮调用轨迹标准化/对比流程，只有成功的 FAST-LIVO2 轨迹已经标准化时才会继续生成基准地图。

GUI 的“运行队列”可以把算法加入列表后用“上移/下移”调整顺序，再点击“开始运行队列”。队列会等待当前算法的 bag 播放、recorder 收尾、结果校验和进程清理全部完成后才进入下一个；某个算法失败会记录结果并继续。队列进度保存到 `metadata/run_queue.json`。

资源曲线中的 CPU 是进程树的逻辑 CPU 总和：单个逻辑核满载为 100%，因此 205% 约等于同时占用两个逻辑核，属于正常的多线程统计方式，不是 CPU 数值溢出。

生成不依赖 ROS 消息读取的阶段性报告：

```bash
benchmark_base/bin/lio-benchmark preliminary-report \
  --run /home/yangxuan/lio_benchmark_runs/navigation_20260721_full2604_round1_001
```
