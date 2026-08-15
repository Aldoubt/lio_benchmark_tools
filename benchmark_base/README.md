# LIO Benchmark Base V2

`benchmark_base` 是 `lio_benchmark_tools` 的实验编排核心。V2 将 Dataset、Algorithm、Run、Standardized Artifact 四个对象显式分开，避免一个脚本同时拥有数据、算法配置、地图和报告真值。

## 核心对象

```text
benchmark_base/
├─ bin/lio-benchmark
├─ config/
├─ registry/
│  ├─ datasets/
│  └─ algorithms/
├─ lib/
└─ tests/
```

### Dataset Registry

记录 bag 身份、话题、消息类型、逐点时间字段、外参来源和采集方式。bag 本体始终留在外部存储。

### Algorithm Registry

固定算法身份、模式、输入/输出 topic contract、runner、已知预处理要求和 Live Debug 启动信息。

### Run

`init` 把当时解析后的 Dataset / Algorithm registry 记录冻结到 `manifest.json`，避免后续 registry 更新改变历史实验语义。

## V2 quick start

```bash
# 查看固定基线
benchmark_base/bin/lio-benchmark list algorithms

# 创建你自己的 dataset JSON 后验证实验
benchmark_base/bin/lio-benchmark validate --config experiment.json
benchmark_base/bin/lio-benchmark init --config experiment.json --run-id greenhouse_001

# 冻结环境并运行
benchmark_base/bin/lio-benchmark snapshot --run /path/to/runs/greenhouse_001
benchmark_base/bin/lio-benchmark run-all --run /path/to/runs/greenhouse_001
```

## Standardization

轨迹标准格式：

```text
timestamp_s,x_m,y_m,z_m,qx,qy,qz,qw,roll_rad,pitch_rad,yaw_rad,source_topic
```

先将算法轨迹转换：

```bash
lio-benchmark standardize trajectory \
  --run <run> --algorithm fast_livo2 \
  --input <trajectory.csv> --source-topic /aft_mapped_to_init
```

再统一重建地图：

```bash
lio-benchmark standardize map --run <run> --algorithm fast_livo2
```

统一地图只接受时间戳匹配成功的扫描，并在 `map_metadata.json` 保存 selected/matched/unmatched scan 数、插值 gap、timestamp source 和生成命令。

## Inspector / Report / Demo

```bash
lio-benchmark inspect --run <run>
lio-benchmark report --run <run>
lio-benchmark demo --run <run>
```

Open3D 只属于 Inspector 可选依赖；headless benchmark 不依赖 Open3D。`ffmpeg` 只用于最后的 GIF 合成，没有 ffmpeg 时仍保留已经生成的 PNG frame 和合成命令。

## Live Debug

Live Debug 不是正式 benchmark timing 模式。它的用途是让人观察算法什么时候开始异常：

```bash
lio-benchmark live prepare \
  --dataset <dataset_id> \
  --algorithms fast_livo2 point_lio \
  --workspace ~/ros2_ws --rate 0.5
```

当前 adapter 只有在明确验证了 namespace/topic 隔离后才允许 session 标成 `simultaneous_safe=true`。否则 `commands.md` 会要求逐个运行 estimator，防止 `/aft_mapped_to_init` 等共享输出互相污染。

## 公平比较规则

- 同一个正式 run 固定 dataset identity、bag hash、外参、代码版本、参数和标准化口径
- 正式性能 benchmark 默认算法逐个运行
- native map 与 unified reconstruction 分开标记
- GLIM Full SLAM 不伪装成 pure odometry 排名
- Leg-KILO `lidar_imu` 与未来 kinematics-enabled 结果分开命名
- 不把首尾 Z 差自动称为真值误差
- 不通过删掉失败区域、手工换视角或只保留成功 run 美化展示
- missing / invalid / failure 都保留为实验状态

完整工作流见 [`docs/V2_WORKFLOW.md`](docs/V2_WORKFLOW.md)。
