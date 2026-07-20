# 实现审计

审计基线：`main` 的 `f45135ee2407232eef2addaec23ac6fa6d380430`。开发分支：`feat/multi-algorithm-benchmark`。

## 审计结论

| 项目 | 开发前证据 | 本分支处理 |
|---|---|---|
| CLI | 单文件实现，仅覆盖部分编排命令 | 拆成 `lio_benchmark` 包，增加 schema v2、registry、doctor、迁移和 dry-run |
| 路径 | runner、`dataset.env` 存在开发机绝对路径 | 算法路径进入 manifest；setup helper 由 runner 注入 workspace |
| 播放倍率 | FAST-LIVO2 历史脚本为 2.0，其余多为 1.0 | 统一 runner 强制 `--rate 1.0 --clock`，非 1.0 直接失败 |
| 输出话题 | 多处写死且未集中登记 | 每个算法在 manifest 登记；runner 只负责按配置运行和录制 |
| 地图时间关联 | 历史地图脚本按扫描进度百分比配轨迹 | 新插值模块使用真实时间戳、线性平移和四元数 SLERP |
| 外参 | 历史地图逻辑仅加平移，忽略旋转 | 使用完整 SE(3)，并测试正向、逆向变换 |
| 点时间 | 历史 PointCloud2 读取存在 FLOAT64/UINT64 误解释风险 | datatype-aware parser；CustomMsg 明确 `uint32 ns -> float32 s` |
| 无真值命名 | 历史输出把无真值诊断量称为 error | 改为 diagnostic；没有真值时禁止生成 ATE/RPE |
| run 覆盖 | 旧脚本可写入已有结果目录 | run 和算法输出目录均拒绝覆盖 |

## 数据审计

- bag：`navigation_20260719_164431`，SQLite3，2604.25236426 秒，1,163,666 条消息。
- LiDAR：`/agt/sensors/lidar/custom`，`livox_ros_driver2/msg/CustomMsg`，26,043 帧。
- IMU：`/agt/sensors/imu/data`，`sensor_msgs/msg/Imu`，514,000 条。
- IMU 加速度模长中位数约 0.9907，按现有设备约定确定为 g；需要 SI 的算法由统一适配器乘 9.80665。
- bag 内已有 odometry 和 TF 是被测系统历史输出，不是独立真值。
- 50 帧只读抽样的完整证据见 `development/PRE_RUN_INPUT_VALIDATION.json`。

## 已知风险

1. `lidar_to_imu` 来自现有项目基线；`lidar_to_base` 是尚未实车复核的测量值，因此 base-frame 地图只可标记为 provisional。
2. MID360 非重复扫描中 `line=0..3` 是真实硬件线号，但不等于机械式 LiDAR 的规则扫描行。LIO-SAM 必须先通过 30–60 秒输入/轨迹健康检查，失败则报告 `BLOCKED_INPUT_MODEL`。
3. MOLA 2.9.0 在外部连续 SIGINT 下可能触发 `Resource deadlock avoided`；正常处理完数据后应只发送一次关闭信号。
4. 当前没有真值，只允许无真值诊断，不允许输出绝对精度排名。

## 审计命令

```bash
git status --short
git branch --show-current
git rev-parse HEAD
find . -maxdepth 4 -type f | sort
ros2 bag info navigation_20260719_164431
python3 -m pytest -q
benchmark_base/bin/lio-benchmark doctor --config benchmark_base/config/navigation_20260719_164431.json
```
