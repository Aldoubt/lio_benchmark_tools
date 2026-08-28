# Phase-aware benchmark：本地验证与使用

本模块用于回答“算法在什么运动阶段开始出现轨迹差异、Z 漂移或资源压力”。没有独立 ground truth 时，所有轨迹误差仍然是相对选定 baseline 的诊断量，不等价于 ATE/RPE 或绝对精度。

## 1. 先跑代码自检

在仓库根目录：

```bash
git fetch origin
git switch feat/phase-aware-benchmark
git pull --ff-only
source /opt/ros/humble/setup.bash
bash evaluators/check_phase_pipeline.sh
```

自检会执行：

- phase analysis / plotting / clock recorder / manual facade 的 `py_compile`；
- `run_algorithm.sh` 的 `bash -n`；
- phase、clock-anchor、manual controller、CLI/postprocess 的聚焦 pytest。

这一步不回放大 bag，也不会改写已有 run。

## 2. 对已有 run 做离线 phase analysis

先看执行计划：

```bash
benchmark_base/bin/lio-benchmark phase-analysis \
  --run /path/to/existing_run \
  --baseline fast_livo2 \
  --dry-run
```

确认后执行：

```bash
benchmark_base/bin/lio-benchmark phase-analysis \
  --run /path/to/existing_run \
  --baseline fast_livo2
```

核心输出：

```text
metrics/phase_analysis.json
reports/phase_analysis.md
figures/phase_analysis/
├── phase_timeline.png
├── trajectory_error_by_phase.png
├── trajectory_error_by_phase_all.png
├── z_change_by_phase.png
├── z_change_by_phase_all.png
└── phase_dashboard.png
```

主轨迹图和 dashboard 只画 `selection_eligible=true` 的 health-valid 算法；带 `_all` 的图保留 Point-LIO、DLIO 等 health-fail 轨迹用于失败诊断，避免极端发散值把正常候选全部压扁。

phase builder 会把第一次持续运动之前的静止段标成 `PRE_MOTION_STATIC`，最后一次持续运动之后的静止段标成 `POST_MOTION_STATIC`。主轨迹图会排除这两个边缘静止区间，但保留路线中间真实发生的 `STATIONARY / STRAIGHT / TURN / HIGH_CURVATURE` phase。完整 timeline 仍保留所有 phase。

如果当前 run 有可用的 phase 级资源时间对齐，还会额外输出：

```text
cpu_by_phase.png
rss_growth_by_phase.png
```

如果 `time_alignment_mode=trajectory-only`，这两张 standalone 资源图不会生成；旧的同名文件如果存在会被删除，dashboard 中会明确显示资源 unavailable 及时间证据不足的原因，避免把空图或旧图误认为有效结果。

如果 `metrics/bag_analysis.json` 不存在，先执行：

```bash
benchmark_base/bin/lio-benchmark analyze-bag --run /path/to/existing_run
```

phase analysis 需要其中 LiDAR topic 的 `recorded_first_s` 与 `record_minus_header_s` 证据，不能把 rosbag recorded time 静默当作轨迹 header time。

## 3. 如何理解 time_alignment_mode

### `strict/clock-anchored`

新的 benchmark run 中存在有效 `raw/<algorithm>/clock_anchors.json`。resource sample 的 wall clock 先通过 `/clock` anchor 映射到 rosbag recorded time，再减去 LiDAR 的 `recorded_minus_header_s` median，得到 trajectory/header time。

### `approximate/lifecycle-aligned`

历史 run 没有 `/clock` anchors，但仍保存了：

- resource sample 的 wall-clock `at`；
- `metadata/run_status.json` 的 playback-running wall-clock event；
- `metrics/bag_analysis.json` 的 recorded/header 时间证据；
- 1.0x playback rate。

这种结果可以做阶段级趋势诊断，但不应把亚秒级 CPU 峰值和某个物理动作宣称为严格同步。

### `trajectory-only`

关键同步证据不足时，只输出轨迹 phase 指标。资源指标明确 unavailable，而不是伪造时间对齐。

## 4. 新 run 的 strict smoke 验证

不要先跑完整长 bag 或全算法。先选一个已经能稳定运行的算法做 20–30 s smoke，例如 FAST-LIVO2：

```bash
benchmark_base/bin/lio-benchmark run \
  --run /path/to/new_run \
  --algorithm fast_livo2 \
  --duration 30
```

结束后先检查：

```bash
python3 - <<'PY' /path/to/new_run/raw/fast_livo2/clock_anchors.json
import json, sys
p = json.load(open(sys.argv[1]))
print({
    "status": p.get("status"),
    "samples": p.get("samples"),
    "wall_time_backtracks": p.get("wall_time_backtracks"),
    "ros_time_backtracks": p.get("ros_time_backtracks"),
})
PY
```

期望至少满足：

```text
status = finished
samples > 2
wall_time_backtracks = 0
ros_time_backtracks = 0
```

随后确保该 run 已有 `metrics/bag_analysis.json` 与标准化轨迹，再执行：

```bash
benchmark_base/bin/lio-benchmark phase-analysis \
  --run /path/to/new_run \
  --baseline fast_livo2
```

最后检查：

```bash
python3 - <<'PY' /path/to/new_run/metrics/phase_analysis.json
import json, sys
p = json.load(open(sys.argv[1]))
print("mode:", p.get("time_alignment_mode"))
print("phases:", [(x["id"], x["state"], round(x["duration_s"], 2)) for x in p.get("phases", [])])
print("warnings:")
for item in p.get("warnings", []):
    print(" -", item)
PY
```

对于这次新 smoke，目标是看到 `strict/clock-anchored`。如果降级为 `trajectory-only`，优先检查 `clock_anchors.json`、`bag_analysis.json` 的 LiDAR recorded/header offset，以及 `resource_monitor.json.sample_history[].at`。

## 5. Phase 参数覆盖

默认阈值只是工程初值，可按数据覆盖：

```bash
benchmark_base/bin/lio-benchmark phase-analysis \
  --run /path/to/run \
  --baseline fast_livo2 \
  --phase-param stationary_speed_mps=0.04 \
  --phase-param turn_yaw_rate_deg_s=10 \
  --phase-param min_phase_duration_s=2.0
```

结果会把最终采用的阈值写入 `phase_parameters`，保证图和报告可追溯。

## 6. 场景语义边界

`PRE_MOTION_STATIC / POST_MOTION_STATIC / STATIONARY / STRAIGHT / TURN / HIGH_CURVATURE` 是从 baseline 轨迹自动得到的运动学 phase，不等价于“温室行间”“垄端转弯”等场景语义。农业场景语义需要在有对应温室地图、任务区或人工/自动语义证据时再叠加，不能从开阔测试场景的运动轨迹直接推断。

## 7. 当前验收边界

在真实 Ubuntu/ROS 数据机验证前，不把以下事项标记为最终通过：

- automatic runner 的真实 `/clock` QoS 与进程退出行为；
- manual controller 的真实 prepare/play/finalize 生命周期；
- 新 short smoke 是否能完整得到 strict wall→recorded→header→phase resource 链路。

历史 run 如果缺少 LiDAR recorded/header offset 证据，稳定降级到 `trajectory-only` 是正确行为，不视为 phase pipeline 失败。

本地验证时如果失败，保留终端输出，并优先附上 `clock_anchors.json`、`metrics/bag_analysis.json` 中 LiDAR topic、`resource_monitor.json` 的前后若干 sample，以及 `metrics/phase_analysis.json` 的 `time_alignment_*` 和 `warnings` 字段。
