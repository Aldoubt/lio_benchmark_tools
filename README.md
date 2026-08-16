# LIO Benchmark Tools

**Reproducible same-bag LiDAR odometry / LIO / SLAM benchmarking for real robotic environments**

这个仓库用于回答一个实际问题：

> 给定同一份冻结传感器数据、同一套标定和同一套地图重建规则，不同 LiDAR odometry / LIO / SLAM 前端究竟会产生什么差异，应该如何解释这些差异

它不是一个新的定位算法，而是一套把 **算法运行、实验冻结、轨迹/地图标准化、交互式点云检查、论文图表、README Demo、实时失效排查** 解耦起来的研究工具

## Same-bag visual comparison

README Demo 由 frozen run 自动生成，不手工换视角、不删除失败区域

```bash
benchmark_base/bin/lio-benchmark demo \
  --run /path/to/frozen/run \
  --display-alignment START_XY_YAW \
  --output assets/demo/same_bag_map_comparison.gif
```

生成并人工审查真实数据结果后，主页直接使用仓库相对路径展示

```markdown
![Same-bag LIO map comparison](assets/demo/same_bag_map_comparison.gif)
```

> 当前仓库不提交伪造的占位 benchmark GIF，真实 GIF 只从可审计的 frozen run 生成

## Why this repository exists

传统“算法 A 的 PCD vs 算法 B 的 PCD”并不天然公平，因为最终地图同时包含：

```text
trajectory estimation
+ algorithm-native map representation
+ filtering / keyframes / submaps
+ backend optimization
+ loop closure
```

因此本仓库把结果拆成两种地图

```text
Algorithm
├─ Native Map
│  └─ upstream algorithm's own mapping result
│
└─ Unified Map
   └─ same raw LiDAR + same selected scans + same calibration
      + algorithm standardized trajectory + same reconstruction rules
```

`Native Map` 回答“完整系统最终能输出什么地图”

`Unified Map` 回答“只看这条估计轨迹，在统一地图重建口径下几何一致性如何”

二者不会被悄悄混为同一种结果

## Baseline suite

### Core baselines

| ID | Algorithm | Representative family | Effective input / role |
|---|---|---|---|
| `fast_livo2` | FAST-LIVO2 | direct ESKF, multimodal-capable | LiDAR + IMU reference, optional vision profile separated |
| `fast_lio2` | FAST-LIO2 | direct IESKF scan-to-map | classical filter LIO |
| `point_lio` | Point-LIO | point-wise ESKF | high-rate / point-wise LIO |
| `dlio` | DLIO | direct continuous-time LIO | motion-compensation baseline |
| `lio_sam` | LIO-SAM | feature + factor graph | factor-graph LIO |
| `glim_odometry` / `glim_full_slam` | GLIM | direct multi-scan + factor graph | odometry and globally optimized mapping roles |
| `leg_kilo` | current `ouguangjun/Leg-KILO` master | two-stage ESKF + hybrid voxel + backend | modern hybrid LIO/SLAM |
| `kiss_icp` | KISS-ICP | LiDAR-only ICP | LiDAR-only control |

### Research baselines

| ID | Algorithm | Role | Environment policy |
|---|---|---|---|
| `faster_lio` | Faster-LIO | efficiency / sparse-voxel research | official ROS1 Melodic/Noetic path, no hidden Humble port |
| `slict` | SLICT current master | surfel continuous-time optimization | official ROS2 Jazzy path, no hidden Humble port |

Historical `leg_kilo2_lidar_imu` remains a `LEGACY` implementation identity and is never silently relabeled as current `leg_kilo`

## Three comparison views

报告不会把所有结果硬塞进一个总排行榜，而是分开生成：

```text
Common LiDAR + IMU Odometry
System Mapping
Control / Extension
```

例如 KISS-ICP 的 LiDAR-only 结果不会和 LiDAR+IMU 结果伪装成同输入条件，GLIM Full SLAM 也不会当成纯 odometry 排名

## Display Alignment

跨算法展示默认支持：

```text
NONE
START_XY_YAW
```

`START_XY_YAW` 只消除各算法任意的初始 XY 原点与初始 yaw

它**不会**消除：

```text
initial Z
roll / pitch
subsequent drift
scale error
non-rigid map distortion
```

也不会修改：

```text
standardized trajectory
Native Map
Unified Map
scientific metrics
```

Alignment 只作为独立的 derived display metadata 保存，Inspector、Report、Demo 共用同一个显示契约

## Four workflows

```text
Dataset Registry + Algorithm Registry
                 │
      ┌──────────┼──────────┬─────────────┐
      │          │          │             │
 Benchmark    Inspector   Report/Demo   Live Debug
      │          │          │             │
 repeatable   3D compare   paper/GIF    bag + nodes
  runs        same camera   figures      manual debug
```

### 1. Frozen benchmark

```bash
lio-benchmark validate --config experiment.json
lio-benchmark init --config experiment.json --run-id greenhouse_001
lio-benchmark snapshot --run runs/greenhouse_001
lio-benchmark preflight --run runs/greenhouse_001
lio-benchmark run --run runs/greenhouse_001 --algorithm fast_livo2
```

正式 benchmark 默认逐个运行算法，避免多个前端争用 CPU/GPU 污染运行时间和实时行为

Preflight 会把问题区分为：

```text
PASS
FAIL_IMPLEMENTATION
FAIL_ALGORITHM
BLOCKED_ENVIRONMENT
BLOCKED_DEPENDENCY
BLOCKED_INPUT
BLOCKED_CALIBRATION
BLOCKED_EXECUTION
NOT_TESTED
```

不会因为算法没安装、显式 executable 不存在或环境不满足就伪记为 PASS

### Runtime Execution Contract

机器相关的真实执行路径不写进全局 Algorithm Registry，而由 experiment manifest 显式冻结。例如：

```json
{
  "execution_overrides": {
    "fast_lio2": {
      "executable": "/absolute/path/to/fastlio_mapping"
    }
  },
  "runtime_overlays": {
    "kiss_icp": [
      "/absolute/path/to/kiss_icp_ws/install/setup.bash"
    ]
  },
  "replay": {
    "rate": 1.0,
    "start_offset_s": 0.0,
    "duration_s": 15.0
  }
}
```

执行解析只有两条路径：

```text
EXPLICIT_EXECUTABLE_OVERRIDE
REGISTRY_DEFAULT_EXECUTION
```

`runtime_overlays` 是按算法冻结的有序 ROS overlay 列表。正式 preflight 和正式 runner 都按固定顺序重建环境：

```text
/opt/ros/<distro>/setup.bash
        ↓
<workspace>/install/setup.bash
        ↓
runtime_overlays[algorithm][0..N]
        ↓
runtime package evidence
        ↓
runtime identity freeze
        ↓
estimator startup
```

新 frozen run 不把交互终端里预先存在的 `AMENT_PREFIX_PATH / CMAKE_PREFIX_PATH / LD_LIBRARY_PATH / PYTHONPATH` 当作未声明 algorithm overlay 的执行证据。声明的 overlay 缺失、不是普通文件、source 失败或 source 后目标 runtime package 仍不可见时返回 `BLOCKED_ENVIRONMENT`。runner 在 preflight 后遇到同类环境失效时保留退出码 `65 -> BLOCKED_ENVIRONMENT`，不会误写成 `FAIL_ALGORITHM`。

工具不会扫描 `$HOME`、`$WORKSPACE/build`、`/tmp` 或其它猜测路径。显式 override 不存在、不可执行或无法 fingerprint 时直接 `BLOCKED_EXECUTION`，不会偷偷回退到另一个 binary；runtime overlay 也不会自动 clone/build/install 或寻找替代路径。

算法真正启动前会写入：

```text
metadata/algorithms/<algorithm>/runtime_identity.json
```

其中冻结至少包含：

```text
resolution method
requested/resolved executable
binary SHA256 / size / mtime
registry package vs runtime package/prefix
runtime overlay setup path + SHA256 + size
source git facts when provable
effective command
effective config + SHA256
workspace / ROS distro
bag path
replay rate / start / duration
```

`runtime_identity.json` 与 trajectory frame audit 是两个独立 gate：binary / overlay 已经精确冻结，并不意味着 `odom -> sensor` 之类的 frame mismatch 可以被忽略。

同一个 run 已经存在 runtime identity 时禁止静默重跑；需要重新执行算法时创建新的 run ID。

当前有限时长 runtime smoke 的目标机迁移先覆盖：

```text
fast_livo2
fast_lio2
kiss_icp
```

其它 baseline 保留各自 adapter 状态，在对应 runner 完成同一 execution/replay contract 迁移前，不会被文档伪装成已验证有限时长 replay。

### 2. Standardize + Inspector

外部/upstream 已经提供 CSV 时继续使用原入口：

```bash
lio-benchmark standardize trajectory \
  --run runs/greenhouse_001 \
  --algorithm point_lio \
  --input /path/to/trajectory.csv \
  --source-topic /odom
```

如果算法是由 benchmark runner 运行，并把轨迹记录成 `raw/<algorithm>/` 下的 ROS 2 bag，则直接从 frozen run 标准化：

```bash
lio-benchmark standardize trajectory-from-run \
  --run runs/greenhouse_001 \
  --algorithm fast_livo2
```

该入口只做 raw pose message → standardized CSV 的表示转换，不做 tracked-frame 变换、world-gauge/gravity 对齐、外参变换、显示对齐、插值重采样或 warm-up 裁剪。它同时写入：

```text
metadata/algorithms/<algorithm>/trajectory_standardization.json
```

已有 `standardized/trajectories/<algorithm>.csv` 时直接拒绝覆盖。

随后继续：

```bash
lio-benchmark standardize map --run runs/greenhouse_001 --algorithm fast_livo2

lio-benchmark inspect \
  --run runs/greenhouse_001 \
  --map-kind unified \
  --color-mode height \
  --display-alignment START_XY_YAW
```

统一重建使用：

```text
LiDAR timestamp
      ↓
standardized trajectory
      ↓
linear position interpolation
quaternion shortest-arc SLERP
      ↓
canonical calibration
      ↓
Unified Map
```

不再使用旧版“scan 序号按比例对应 pose 序号”

Inspector 支持多算法开关、Native/Unified Map、trajectory overlay、共享 height/intensity 色标、XY/XZ/YZ/Perspective、ROI preset、camera preset 和截图导出

### 3. Paper report / README demo

```bash
lio-benchmark report \
  --run runs/greenhouse_001 \
  --display-alignment START_XY_YAW

lio-benchmark demo \
  --run runs/greenhouse_001 \
  --algorithms fast_livo2 fast_lio2 point_lio leg_kilo \
  --display-alignment START_XY_YAW
```

Report / Demo 使用同一：

```text
frozen run
ROI
map kind
Display Alignment
comparison bounds
height scale
camera path
```

缺失、失败、阻塞结果保持 `MISSING/FAIL/BLOCKED`，不会被写成 0 分

### 4. Live Debug

```bash
lio-benchmark live prepare \
  --dataset greenhouse_mid360 \
  --algorithms fast_livo2 fast_lio2 point_lio \
  --workspace ~/ros2_ws \
  --rate 0.5
```

工具生成可读的 bag/node/session 脚本，而不是把 ROS 进程藏进黑盒 supervisor

发现异常时可以记录：

```bash
lio-benchmark mark \
  --session live_sessions/<session> \
  --algorithm point_lio \
  --event repetitive_row_misregistration \
  --bag-time 84.32 \
  --note "parallel-row alias begins"
```

后续可围绕 marker 对齐局部点云、轨迹与日志

## Diagnostic bundle

一次诊断结束后，不需要再手工复制一组 CSV / JSON / metadata。默认将小型诊断证据打成一个可上传的压缩包：

```bash
benchmark_base/bin/lio-benchmark bundle --run /path/to/frozen/run
```

默认输出：

```text
<run>/reports/bundles/<run_id>_diagnostic_bundle.tar.gz
```

默认包包含 manifest、runtime identity、trajectory standardization metadata、audit/diagnostic CSV/JSON、Common Scan Manifest、各算法 Unified Map metadata，以及打包时的 benchmark Git HEAD / status / local diff。它不会包含 `raw/`、rosbag 数据库、`.ply` / `.pcd` 地图、报告或 PNG 图。

需要把现有 report 和诊断图一并交给 reviewer 时：

```bash
benchmark_base/bin/lio-benchmark bundle \
  --run /path/to/frozen/run \
  --include-reports
```

`bundle` 只打包已有 artifact，不会重新运行算法、地图标准化或报告生成，也不会修改现有 run artifact；除最终 `.tar.gz` 外不创建 staging 文件。

## Standard artifact contract

```text
runs/<run_id>/
├─ manifest.json
├─ configs/generated/<algorithm>/
├─ raw/<algorithm>/
├─ standardized/
│  ├─ trajectories/
│  ├─ map_sampling/selected_scans.csv
│  └─ maps/<algorithm>/
│     ├─ native/
│     │  ├─ map.*
│     │  └─ metadata.json
│     └─ unified/
│        ├─ map.ply
│        └─ metadata.json
├─ metrics/
├─ figures/
│  └─ display_alignment/
├─ reports/
├─ logs/
└─ metadata/
   ├─ algorithms/<algorithm>/runtime_identity.json
   ├─ algorithms/<algorithm>/trajectory_standardization.json
   ├─ frame_audit/
   └─ runtime_provenance/
```

旧 V2 路径仍保留兼容入口，例如：

```text
standardized/trajectories/<algorithm>.csv
standardized/maps/<algorithm>/unified_map.ply
standardized/maps/<algorithm>/map_metadata.json
```

## Reproducibility

每个 algorithm × dataset run 尽可能冻结：

```text
source repository / branch / commit
source dirty state
adapter identity
runtime executable realpath + SHA256
execution resolution method
runtime overlay setup path + SHA256 + size
effective command + config hash
frozen replay interval
algorithm parameters + hash
effective sensor modalities
canonical calibration source/status
algorithm-specific extrinsic convention
bag identity/hash
environment snapshot
raw output
standardized output
failures / blockers
```

未知信息写 `UNKNOWN`，不猜

## Verified reference smoke

本仓库已使用真实温室 MID360 bag 完成 FAST-LIVO2 V2 reference smoke：

```text
full replay                 622.99 s
LiDAR frames                6230
standardized trajectory     6227 samples
selected map scans          1246
matched scans               1238 / 1246 = 99.36%
unified map                 772,631 points
```

这一轮证明了真实 bag → trajectory → timestamp association → Unified Map → Inspector / Report 的核心链路

该数据集当时的 LiDAR–IMU 外参数值尚未完成正式确认，因此地图仍按 `DIAGNOSTIC_ONLY / BLOCKED_CALIBRATION` 对待，不把诊断结果包装成正式算法排名

三算法 Runtime Execution Contract + runtime overlays + trajectory-from-run 的目标机验证使用独立配置：

```text
benchmark_base/config/green_house_three_runtime_smoke.json
```

该配置冻结 KISS-ICP 的持久 runtime overlay，而不是依赖交互终端手工 source 或历史 `/tmp` 安装目录。目标机正式验证必须从仅 source 基础 ROS distro 的 fresh shell 创建新的 run ID。目标机验证完成前，README 不声明这条新 runtime/trajectory standardization 链路已通过真实机器回放。

## Repository boundary

本仓库保存：

- benchmark orchestration / registry
- dataset and algorithm contracts
- runtime execution identity / provenance contracts
- adapters and explicit compatibility patches
- standardization / calibration / map-sampling logic
- Display Alignment / ROI / camera presets
- Inspector / report / demo generators
- selected small README assets

本仓库不保存大型 rosbag、完整 run PCD/PLY、完整上游算法 clone，也不属于机器人导航 runtime

## Documentation

- [`benchmark_base/docs/V2_WORKFLOW.md`](benchmark_base/docs/V2_WORKFLOW.md) — 当前完整工作流
- [`benchmark_base/docs/adapters/`](benchmark_base/docs/adapters/) — algorithm adapter contracts
- [`benchmark_base/README.md`](benchmark_base/README.md) — run 目录和实验规则
- [`benchmark_base/docs/USER_MANUAL_ZH.md`](benchmark_base/docs/USER_MANUAL_ZH.md) — 原理与历史使用说明
- [`docs/superpowers/specs/2026-08-15-lio-benchmark-v2-design.md`](docs/superpowers/specs/2026-08-15-lio-benchmark-v2-design.md) — V2 design
- [`docs/superpowers/specs/2026-08-15-lio-baseline-suite-design.md`](docs/superpowers/specs/2026-08-15-lio-baseline-suite-design.md) — baseline suite / two-map / Display Alignment contract
- [`docs/superpowers/specs/2026-08-16-diagnostic-bundle-design.md`](docs/superpowers/specs/2026-08-16-diagnostic-bundle-design.md) — diagnostic bundle contract
- [`docs/superpowers/specs/2026-08-16-runtime-execution-contract-design.md`](docs/superpowers/specs/2026-08-16-runtime-execution-contract-design.md) — explicit executable / replay / runtime identity contract
- [`docs/superpowers/specs/2026-08-16-runtime-overlays-design.md`](docs/superpowers/specs/2026-08-16-runtime-overlays-design.md) — per-algorithm frozen ROS runtime overlay contract
- [`docs/superpowers/specs/2026-08-16-trajectory-from-run-design.md`](docs/superpowers/specs/2026-08-16-trajectory-from-run-design.md) — run-local ROS 2 trajectory bag standardization contract
- [`docs/verification/runtime_overlays_verification.md`](docs/verification/runtime_overlays_verification.md) — repository verification and fresh-shell target-machine overlay gate
- [`docs/verification/trajectory_from_run_verification.md`](docs/verification/trajectory_from_run_verification.md) — repository verification and target-machine acceptance gate

## License

Apache-2.0