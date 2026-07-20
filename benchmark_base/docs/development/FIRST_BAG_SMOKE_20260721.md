# 第一次 bag smoke 运行记录

数据集：`navigation_20260719_164431`。日期：2026-07-21。所有正式 smoke 均固定 60 秒、`--rate 1.0 --clock`，且只重放原始 LiDAR 和 IMU。未运行完整 2604 秒 bag。

## 最终有效结果

| 配置 | 结果 run | 输入 LiDAR 帧 | 主要轨迹 | 有效位姿 | 时间健康 | 状态 |
|---|---|---:|---|---:|---|---|
| KISS-ICP | `_005` | 597 | `/kiss/odometry` | 597 | 0 倒退，0 NaN/Inf | SUCCESS |
| MOLA-LO | `_005` | 594 | `/tf` `map->livox_frame` | 592 | 0 倒退，0 NaN/Inf | SUCCESS |
| MOLA-LIO | `_005` | 597 | `/tf` `map->livox_frame` | 594 | 0 倒退，0 NaN/Inf | SUCCESS |
| FAST-LIVO2 | `_006` | 原生输入 | `/aft_mapped_to_init` | 594 | 0 倒退，0 NaN/Inf | SUCCESS |
| Point-LIO | `_006` | 597 | `/aft_mapped_to_init` | 1189 | 28 次原始严格倒退，0 NaN/Inf | SUCCESS_WITH_STANDARDIZATION_REQUIRED |
| DLIO | `_009` | 597 | `/odom` | 6689 | 216 个零时间、733 个重复时间、0 严格倒退、0 NaN/Inf | SUCCESS_WITH_STANDARDIZATION_REQUIRED |
| GLIM odometry | `_007` | 597 | `/glim_ros/odom` | 567 | 0 倒退，0 NaN/Inf | SUCCESS |
| GLIM full SLAM | `_007` | 597 | `/glim_ros/odom_corrected` | 566 | 0 倒退，0 NaN/Inf | SUCCESS |
| LIO-SAM no-loop | `_006` | 593 | `/lio_sam/mapping/odometry` | 212 | 0 倒退，0 NaN/Inf | SUCCESS |
| LIO-SAM loop | `_007` | 572 | `/lio_sam/mapping/odometry` | 279 | 0 倒退，0 NaN/Inf | SUCCESS |

完整 run 根目录是 `/home/yangxuan/lio_benchmark_runs/`，表中 `_005` 等是 `navigation_20260719_smoke60_20260721_005` 的缩写。每个算法目录含冻结 manifest、实际命令、配置副本、轨迹 bag、日志、输入验证和退出状态。

LIO-SAM 同时成功记录了高频 IMU odometry：no-loop 11,508 条，loop 11,281 条。DLIO 最终记录 6,689 条 odometry 和 564 条 Path；其输出定时器导致零/重复时间，标准化阶段必须按任务书移除零时间并排序去重。Point-LIO 的同一输出话题包含交错发布，标准化阶段同样必须按传感器时间排序，不能直接按录制顺序评测。

## 首轮运行发现并落地的修复

1. ROS Humble setup 与 `set -u` 不兼容：setup 时临时关闭 nounset。
2. Humble 无 `ros2 bag play --duration`：runner 使用有界 timeout，并保留 raw/normalized 退出码。
3. 初始 Python adapter 无法稳定达到 10 Hz：新增 Release C++ adapter；最终通常处理 572–597 帧，输出点时间无倒退。
4. 输入 playback 只包含 LiDAR/IMU，避免历史 `/tf`、odometry 和 bag 内 `/clock` 污染。
5. 单节点算法改用 manifest 中的真实 executable，清理其进程树，避免下一次 bag 时间从头开始时造成 timestamp rewind。
6. DLIO PointCloud2 需要 Reliable publisher；adapter 已调整为 Reliable 输出。
7. GLIM 的 ROS odometry publisher 位于 `librviz_viewer.so`；仅启用该发布扩展，不启动 GUI。
8. LIO-SAM 增加 `livox_imu -> livox_frame` 静态标定 TF，并修正高频 IMU odometry 话题。
9. DLIO 上游 `computeSpaciousness()` 存在一位越界，补丁见 `patches/dlio/spaciousness_bounds.patch`。
10. DLIO negative crop box 是自车滤波而非最大量程，参数从错误的 70 m 修正为 1 m。
11. DLIO 真实输出是 `/odom`、`/path`，已修正录制配置。

## 保留的失败证据

`_001` 至 `_004`、`_008` 是 runner、性能和 DLIO 诊断过程，均未覆盖或删除。`_005` 中 Point-LIO 的收尾失败来自运行时修改 runner 文件，后续 `_006` 已在干净进程环境重跑成功。所有最终表格只引用明确成功的 run。

## 当前限制与下一步

- 当前 bag 没有独立真值，不生成 ATE/RPE 或绝对精度结论。
- 本报告只证明 60 秒输入兼容、节点健康和轨迹可生成，不代表完整 bag 稳定性或算法优劣。
- LIO-SAM 对 MID360 非重复扫描的长期可靠性仍需完整包验证；当前 adapter 没有虚构 ring。
- 用户审阅本报告后，下一阶段才是统一标准化这批 smoke 轨迹，随后决定是否运行完整 bag。
