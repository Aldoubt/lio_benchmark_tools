# Phase-aware LIO Benchmark 设计

日期：2026-08-28

## 1. 目标

在现有多算法完整回放、轨迹标准化、资源监控和相对 FAST-LIVO2 诊断之上，增加一个独立的 **phase-aware benchmark** 子系统，用来回答：

- 算法在哪一个运动阶段开始产生明显轨迹差异或 Z 漂移；
- 某一阶段是否同时出现 CPU burst、RSS 增长、线程扩张等资源压力；
- 这些现象是持续累积、转弯触发，还是初始化/回程附近出现；
- 无独立 ground truth 时，所有结果仍保持 relative/diagnostic 语义，不冒充 ATE/RPE。

本子系统不得继续膨胀 `plot_comparison_dashboard.py`，而应作为独立分析入口和独立结果目录存在。

## 2. 当前时间信息审计

### 已有信息

`evaluators/resource_monitor.py` 的每个资源样本已经保存：

- `elapsed_s`：resource monitor 自身的 monotonic elapsed time；
- `at`：带时区 wall-clock ISO 时间；
- `cpu_percent`、`rss_bytes`、`threads`、`write_bytes`。

`metadata/run_status.json` 已保存生命周期事件，事件中包含 wall-clock `at`、算法名、bag playback 状态和 phase。现有 runner 在 1.0x 下使用：

```text
ros2 bag play ... --rate 1.0 --clock
```

因此历史 run 可以由：

```text
resource sample wall time
        ↕
run_status playback-running event wall time
        ↕
manifest / bag start time
```

恢复近似 bag 进度。

### 当前缺口

历史 runner 在资源监控启动后仍有算法启动等待、recorder 启动等步骤；`bag_playback=running` 事件和真实第一帧 `/clock` 之间存在不可直接观测的进程启动延迟。因此旧 run 的 wall→bag 映射不能标记为 strict/exact。

## 3. 时间同步策略

实现两种明确分级的同步模式，不混用口径。

### 3.1 `strict/clock-anchored`（未来正式实验）

新增独立 `clock_anchor_recorder.py`，订阅 `/clock`，周期性记录：

```json
{
  "wall_time_ns": 0,
  "at": "ISO-8601",
  "ros_time_ns": 0,
  "ros_time_s": 0.0,
  "sequence": 0
}
```

输出到算法 raw 目录，例如：

```text
raw/<algorithm>/clock_anchors.json
```

设计约束：

- 它是独立小进程，不把 ROS 订阅逻辑塞进 `resource_monitor.py`；
- resource monitor 继续只负责 psutil 资源采样；
- runner 和 manual controller 都要在算法 prepare 阶段启动 clock recorder，并在 finalize 时可靠停止；
- phase analysis 用 wall-clock 在相邻 clock anchors 之间做分段线性插值，从而把 resource sample 映射到 ROS/bag time；
- 插值结果必须带 `time_alignment_mode=strict/clock-anchored`。

### 3.2 `approximate/lifecycle-aligned`（历史 run 兼容）

如果没有 `clock_anchors.json`，但存在：

- resource sample 的 `at`；
- `run_status.json` 中该算法进入 `bag_playback=running` 的事件；
- manifest/bag 的起始时间和 1.0x playback rate；

则允许生成近似映射。

近似模式必须：

- 输出 `time_alignment_mode=approximate/lifecycle-aligned`；
- 保存所用生命周期锚点和估计偏移；
- 报告中明确禁止把亚秒级事件对应关系当严格证据；
- 不存在足够锚点时降级为 `trajectory-only`，绝不伪造同步资源指标。

## 4. Phase 定义

Phase 由选定 baseline（默认 FAST-LIVO2）的标准化轨迹自动生成，所有候选算法共享同一组时间窗口，避免每个算法独立切段导致不可比较。

### 4.1 主运动状态

基于统一重采样后的 baseline 轨迹计算：

- 线速度 `speed_mps`；
- yaw rate `yaw_rate_rad_s`；
- 平面曲率 `curvature_1pm`；
- 到起点距离 `distance_to_start_m`。

首版主状态：

```text
INITIALIZATION
STATIONARY
STRAIGHT
TURN
HIGH_CURVATURE
```

其中：

- `INITIALIZATION`：从轨迹开始到首次持续运动成立之前；
- `STATIONARY`：速度低于阈值；
- `TURN`：yaw rate 超过阈值；
- `HIGH_CURVATURE`：非静止状态下曲率超过阈值；
- `STRAIGHT`：其余有效运动区间。

`RETURN_NEAR_START` 不作为互斥主状态，而作为空间 tag；这样“回程中的转弯”仍可同时表达为 `TURN + return_near_start=true`。

### 4.2 阈值和去抖

阈值必须机器可读、写入结果 metadata，并允许 CLI 覆盖。首版默认值只作为工程默认，不宣称具有跨数据集普适性：

```text
resample_hz = 10
stationary_speed_mps = 0.05
turn_yaw_rate_deg_s = 8.0
high_curvature_1pm = 0.12
min_phase_duration_s = 1.5
sustained_motion_s = 2.0
near_start_radius_m = 3.0
```

短于 `min_phase_duration_s` 的碎片段应按相邻状态和持续时间规则合并，避免标签抖动。

## 5. 每阶段指标

### 5.1 轨迹指标

候选轨迹沿用现有 initial-yaw + translation 对齐，不重新发明另一套坐标口径。

每个 phase 至少输出：

```text
samples
coverage_ratio
max_sample_gap_s
relative_position_rmse_m
relative_position_p95_m
relative_z_rmse_m
z_change_m
roll_range_deg
pitch_range_deg
```

没有独立 ground truth 时，这些指标统一标记：

```text
metric_class = relative-to-baseline/diagnostic/non-ground-truth
```

### 5.2 资源指标

当时间同步可用时，每阶段输出：

```text
resource_samples
cpu_median_percent
cpu_mean_percent
cpu_p95_percent
cpu_peak_percent
rss_start_mib
rss_end_mib
rss_growth_mib
rss_peak_mib
threads_p95
threads_peak
```

资源指标必须带 `time_alignment_mode`。`trajectory-only` 模式下这些字段应为 unavailable/null，并说明原因。

## 6. CLI 与模块边界

新增独立入口：

```bash
benchmark_base/bin/lio-benchmark phase-analysis \
  --run /path/to/run \
  --baseline fast_livo2
```

推荐模块拆分：

```text
evaluators/clock_anchor_recorder.py
    未来实验严格 wall↔ROS time 锚点记录

evaluators/phase_analysis.py
    时间对齐、phase 切分、指标聚合、JSON/Markdown 输出

evaluators/plot_phase_analysis.py
    只负责读取 phase_analysis.json 画图

benchmark_base/lio_benchmark/postprocess.py
benchmark_base/lio_benchmark/entry.py
    只做 CLI 编排
```

`phase_analysis.py` 不依赖 rosbag 回放；对于已有 standardized trajectory 和资源记录的 run，它应可离线重复执行。

## 7. 输出契约

机器可读：

```text
metrics/phase_analysis.json
```

人工报告：

```text
reports/phase_analysis.md
```

图：

```text
figures/phase_analysis/
├── phase_timeline.png
├── trajectory_error_by_phase.png
├── z_change_by_phase.png
├── cpu_by_phase.png
├── rss_growth_by_phase.png
└── phase_dashboard.png
```

`phase_analysis.json` 顶层至少包含：

```text
schema_version
baseline
metric_class
time_alignment_mode
time_alignment_evidence
phase_parameters
phases
algorithms
warnings
```

## 8. 历史 807 s run 的处理原则

对 `/home/yangxuan/lio_benchmark_runs/mapping_20260719_172810_full807_round1_001`：

1. 优先检查 `metadata/run_status.json` 是否仍保留每个算法 playback-running 事件；
2. 如果事件足够，生成 `approximate/lifecycle-aligned` 阶段资源分析；
3. 如果事件不足，只做 trajectory phase analysis，资源部分明确 unavailable；
4. 不重新跑完整 807 s bag 只是为了补历史 strict clock anchors；
5. 下一轮正式重复实验再启用 `strict/clock-anchored`。

## 9. 测试策略

遵循 TDD，优先使用纯 Python 合成数据，不要求 ROS 才能验证核心逻辑。

必须覆盖：

- lifecycle approximate mapping 的正常和缺失锚点降级；
- clock-anchor piecewise interpolation；
- INITIALIZATION/STATIONARY/STRAIGHT/TURN/HIGH_CURVATURE 切段；
- phase 短片段合并；
- baseline 和 candidate 在共同时间窗内的 phase 指标；
- CPU median/mean/P95、RSS growth、thread P95 聚合；
- health-fail 算法保留但不进入默认 selection summary；
- 无资源时间对齐时 trajectory-only 不生成伪资源数值；
- CLI dry-run 能正确展开 phase-analysis 命令。

ROS 集成测试单独验证：

- `/clock` recorder 能生成单调/可解释锚点；
- automatic runner 和 manual controller 都正确启动/停止 recorder；
- 一次短 smoke run 能得到 `strict/clock-anchored` phase report。

## 10. 非目标

本阶段明确不做：

- 自动识别“第几垄/哪一排温室”等场景语义；
- 把 FAST-LIVO2 当绝对真值；
- 新增更多 LIO 算法；
- 为历史 run 伪造 `/clock`；
- 把所有功能继续塞进现有 comparison dashboard；
- 在没有重复实验之前输出统计显著性结论。

## 11. 验收标准

首个可接受版本满足：

1. `phase-analysis --run ... --baseline fast_livo2` 可离线执行；
2. 对历史 run 明确显示 approximate 或 trajectory-only；
3. 对未来 short smoke 能显示 strict/clock-anchored；
4. 至少可区分直行/转弯/静止类阶段并输出可追溯阈值；
5. 每阶段能同时读取轨迹和资源指标（同步可用时）；
6. 不改变现有 `visualize`、`compare`、resource dashboard 的结果口径；
7. 没有 ground truth 时不会生成 ATE/RPE 或绝对精度措辞。
