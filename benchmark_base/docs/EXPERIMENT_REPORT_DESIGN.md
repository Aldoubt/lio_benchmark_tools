# 实验报告与诊断软件设计

## 目标

报告分为三个层级：

1. 生命周期完整性：bag 播放、算法退出、recorder 收尾、轨迹 metadata、输入校验和资源监控。
2. 轨迹健康性：消息数、时间范围、时间倒退、重复时间戳、姿态有效性和标准化状态。
3. 算法对比：按 `lidar_only_odometry`、`lidar_imu_odometry` 和 `full_slam` 分组，输出诊断指标；有独立 ground truth 时再增加 ATE/RPE。

没有 ground truth 时，报告不能把路径长度、Z 漂移或基准对齐 RMSE 写成绝对精度排名。

## 数据流

```text
manifest.json + run_status.json
        |
        +-- raw/<algorithm>/run_result.json
        +-- raw/<algorithm>/trajectory/metadata.yaml
        +-- raw/<algorithm>/resource_monitor.json
        +-- raw/<algorithm>/*.log
        |
        +--> generate_experiment_report.py
        |       +--> preliminary_experiment_report.json
        |       +--> preliminary_experiment_report.md
        |
        +--> standardize_trajectory / summarize_smoke_run
        +--> evaluation metrics
        +--> FAST-LIVO2 baseline map (条件满足时)
```

初步报告不读取 rosbag 消息，因此可以在其它算法仍运行时生成；标准化和地图阶段才读取轨迹/输入 bag。

## 状态分级

| 分类 | 含义 |
|---|---|
| `SUCCESS` | 生命周期、保存校验和日志均无高等级异常 |
| `SUCCESS_WITH_WARNINGS` | 成功保存，但存在时间同步、数据丢弃或已知 warning |
| `SUCCESS_NEEDS_REVIEW` | 成功保存，但存在 ERROR、子进程异常或结果字段不一致 |
| `RUNTIME_CRASH` | 算法进程异常退出；即使有部分轨迹，也不能作为成功结果 |
| `NO_ODOMETRY` | bag 可收尾但轨迹消息为零或无有效轨迹 |
| `SAVE_FAILED` | 算法可能运行，但轨迹/校验/结果保存不完整 |
| `RUNNING` / `PENDING` | 尚未形成最终结果 |

报告会保留原始日志示例和计数，不把 `INFO` 中普通的“error”字段误判为异常。CPU 是进程树逻辑 CPU 总和，100% 代表一个逻辑核。

## 当前阶段必要软件

- `generate_experiment_report.py`：无 ROS 依赖的生命周期/资源/日志初筛。
- `summarize_smoke_run.py`：读取轨迹消息并生成标准化 CSV/TUM 与诊断比较。
- `visualize_baseline_maps.py`：仅在 FAST-LIVO2 成功且标准化轨迹存在时生成相对基准地图。
- GUI queue worker：串行执行算法，记录 `metadata/run_queue.json`，失败后继续后续项目。

后续可增加：每核 CPU、GPU 利用率/显存、磁盘吞吐和 bag 播放进度的统一 sampler，并把这些数据写入同一份 time-series resource schema。

## 当前 run 的阶段性判读

当前长 bag run 已经产生 10 个算法条目：8 个有最终结果，1 个仍在运行，1 个以 `RUNTIME_CRASH` 结束。`SUCCESS` 只表示生命周期和保存校验通过，不等价于轨迹质量合格。

需要优先复核的现象包括：

- DLIO 的 `NotEnoughMemoryException`，属于运行时崩溃。
- LIO-SAM no-loop 的 IMU preintegration 子进程异常，但当前结果被生命周期逻辑归为 SUCCESS，应在报告中标记 `SUCCESS_NEEDS_REVIEW`。
- FAST-LIVO2、Point-LIO 的 lidar loop-back 日志，以及 FAST-LIVO2 的大量硬时间滞后日志，需检查时间同步和输入/输出时间语义。
- MOLA-LIO 的 deskew 时间间隔警告和 status 中残留的旧 reason。
- LIO-SAM loop 结束后才能锁定完整报告。
