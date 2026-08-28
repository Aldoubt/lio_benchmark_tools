# Phase-aware LIO Benchmark 设计

日期：2026-08-28

## 1. 目标

在现有多算法完整回放、轨迹标准化、资源监控和相对 FAST-LIVO2 诊断之上，增加独立的 **phase-aware benchmark** 子系统，用来回答：

- 算法在哪一个运动阶段开始产生明显轨迹差异或 Z 漂移；
- 某一阶段是否同时出现 CPU burst、RSS 增长、线程扩张等资源压力；
- 这些现象是持续累积、转弯触发，还是初始化/回程附近出现；
- 无独立 ground truth 时，所有结果仍保持 relative/diagnostic 语义，不冒充 ATE/RPE。

本子系统不得继续膨胀 `plot_comparison_dashboard.py`，而应作为独立分析入口和独立结果目录存在。

## 2. 当前时间信息审计

`evaluators/resource_monitor.py` 已有 wall-clock `at` 和 monotonic `elapsed_s`；`metadata/run_status.json` 已有生命周期 wall-clock 事件；`evaluators/analyze_bag.py` 已有 recorded/header 时间统计。因此仓库已有 wall-clock、rosbag recorded time、message header time 三条时间证据链。

历史 runner 中 `bag_playback=running` 与真实第一帧 `/clock` 之间仍有不可观测启动延迟，所以旧 run 只能做 approximate 对齐。`/clock` 又对应 rosbag recorded/playback time，而标准化轨迹通常沿用消息 header stamp，因此 phase analysis 不能静默假定二者相等。

## 3. 时间同步策略

### `strict/clock-anchored`

未来正式实验新增独立 `clock_anchor_recorder.py`，订阅 `/clock` 并记录 wall time 与 ROS time 到 `raw/<algorithm>/clock_anchors.json`。resource monitor 继续只做 psutil 资源采样；automatic runner 和 manual controller 在 prepare/finalize 中管理 recorder 生命周期。

phase analysis 先用 clock anchors 把资源 wall time 映射到 rosbag recorded time，再利用 `metrics/bag_analysis.json` 中 LiDAR topic 的 `record_minus_header_s` 把 recorded time 映射到 trajectory/header time。默认使用 median offset，同时保存 std/min/max evidence；缺失或波动明显时 warning，不假定 0。

### `approximate/lifecycle-aligned`

历史 run 没有 clock anchors 时，如果 resource sample `at`、run_status playback-running 事件、bag_analysis recorded/header 统计以及 1.0x playback rate 都存在，则按 lifecycle wall anchor 近似恢复 recorded time，再应用 recorded→header offset。关键证据缺失时降级为 `trajectory-only`，绝不伪造资源同步。

## 4. Phase 定义

所有算法共享 baseline（默认 FAST-LIVO2）生成的 phase。首版互斥状态与固定优先级为：`INITIALIZATION > STATIONARY > TURN > HIGH_CURVATURE > STRAIGHT`；`RETURN_NEAR_START` 只作为空间 tag。

默认阈值：

```text
resample_hz = 10
stationary_speed_mps = 0.05
turn_yaw_rate_deg_s = 8.0
high_curvature_1pm = 0.12
min_phase_duration_s = 1.5
sustained_motion_s = 2.0
near_start_radius_m = 3.0
```

短于最小时长的碎片段：左右同状态则合并；否则合并到持续更长的相邻 phase；平局优先前一 phase。只在 baseline 有效时间域生成 phase，域外资源样本记为 `outside_phase_window`。

## 5. 每阶段指标

轨迹指标：`samples / coverage_ratio / max_sample_gap_s / relative_position_rmse_m / relative_position_p95_m / relative_z_rmse_m / z_change_m / roll_range_deg / pitch_range_deg`。

资源指标：`resource_samples / cpu_median_percent / cpu_mean_percent / cpu_p95_percent / cpu_peak_percent / rss_start_mib / rss_end_mib / rss_growth_mib / rss_peak_mib / threads_p95 / threads_peak / outside_phase_window_samples`。

无 ground truth 时统一 `metric_class=relative-to-baseline/diagnostic/non-ground-truth`。trajectory-only 模式资源字段为 null/unavailable。

## 6. CLI 与模块边界

```bash
benchmark_base/bin/lio-benchmark phase-analysis \
  --run /path/to/run \
  --baseline fast_livo2
```

模块：

```text
evaluators/clock_anchor_recorder.py
evaluators/phase_analysis.py
evaluators/plot_phase_analysis.py
benchmark_base/lio_benchmark/postprocess.py
benchmark_base/lio_benchmark/entry.py
```

`phase_analysis.py` 不依赖 rosbag 回放；已有 standardized trajectory、bag_analysis 和资源记录足够时可离线重复执行。

## 7. 输出契约

```text
metrics/phase_analysis.json
reports/phase_analysis.md
figures/phase_analysis/
├── phase_timeline.png
├── trajectory_error_by_phase.png
├── z_change_by_phase.png
├── cpu_by_phase.png
├── rss_growth_by_phase.png
└── phase_dashboard.png
```

JSON 顶层至少包含：`schema_version / baseline / metric_class / time_alignment_mode / time_alignment_evidence / clock_to_trajectory_offset / phase_parameters / phases / algorithms / warnings`。

## 8. 历史 807 s run

先检查 run_status playback-running 事件和已有 bag_analysis recorded/header 时间证据。两者足够时生成 `approximate/lifecycle-aligned`；任一关键证据不足时只做 trajectory phase analysis。不重新跑完整 807 s bag 只为补历史 clock anchors；下一轮正式重复实验启用 strict。

## 9. 测试策略

遵循 TDD。纯 Python 合成数据覆盖 lifecycle approximate mapping、clock-anchor piecewise interpolation、recorded→header offset、状态优先级、phase 去抖、共同时间窗轨迹指标、CPU/RSS/thread 聚合、health-fail 保留、trajectory-only 降级、CLI dry-run。ROS 集成测试单独验证 `/clock` recorder、automatic/manual runner 生命周期和 short smoke strict phase report。

## 10. 非目标

不自动识别温室语义；不把 FAST-LIVO2 当绝对真值；不新增更多 LIO 算法；不为历史 run 伪造 `/clock`；不继续膨胀 comparison dashboard；不在没有重复实验前输出统计显著性结论。

## 11. 验收标准

1. `phase-analysis --run ... --baseline fast_livo2` 可离线执行；
2. 历史 run 明确显示 approximate 或 trajectory-only；
3. 未来 short smoke 显示 strict/clock-anchored；
4. 至少区分直行/转弯/静止类阶段并输出可追溯阈值；
5. 同步可用时每阶段同时输出轨迹和资源指标；
6. strict/approximate 都保存完整时间证据，不静默假定 recorded time 等于 header time；
7. 不改变现有 visualize/compare/resource dashboard 口径；
8. 无 ground truth 时不生成 ATE/RPE 或绝对精度措辞。
