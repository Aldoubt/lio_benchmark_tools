# LIO Benchmark Tools V2 Workflow

## 1. Register a dataset

从模板复制：

```bash
cp benchmark_base/registry/datasets/example_mid360.json \
   benchmark_base/registry/datasets/gaas_handheld_a.json
```

至少确认：

```text
dataset_id
bag_dir
sha256 when frozen
environment / acquisition
topics and message types
point-time field / unit
LiDAR→IMU calibration and source
```

不要修改原始 bag 来适配某一个算法。算法特有 topic / unit / format 适配属于 adapter。

## 2. Select algorithms

固定基线 registry：

```bash
lio-benchmark list algorithms
lio-benchmark show algorithm fast_livo2
```

V2 固定基线为 FAST-LIVO2、Point-LIO、Leg-KILO 2.0 LiDAR-IMU、GLIM Odometry、GLIM Full SLAM、DLIO。

## 3. Create a frozen run

复制 `benchmark_base/config/experiment.template.json`，填入 workspace、output_root、dataset ID 和算法列表：

```bash
lio-benchmark validate --config experiment.json
lio-benchmark init --config experiment.json --run-id gaas_a_001
lio-benchmark snapshot --run /path/to/runs/gaas_a_001
```

`manifest.json` 是该 run 的冻结契约；后续 registry 修改不会回写历史 run。

## 4. Offline benchmark

```bash
lio-benchmark run --run <run> --algorithm fast_livo2
lio-benchmark run-all --run <run>
```

每个算法输出独立日志和 run status。失败 run 保留，不自动删除。

Leg-KILO 见 `LEG_KILO_ADAPTER.md`：公共 registry 固定算法身份，本机 adapter 显式记录具体 ROS1/ROS2 bridge、bag conversion 或 local port。

## 5. Standardize trajectories

当前 V2 不猜每个第三方算法的原始输出文件位置。先由各 adapter/现有分析器导出 CSV，再显式执行：

```bash
lio-benchmark standardize trajectory \
  --run <run> \
  --algorithm point_lio \
  --input /path/to/raw_or_legacy_trajectory.csv \
  --source-topic /aft_mapped_to_init
```

如果列名不是标准别名，使用 `--column-map` 传 JSON 字符串或 JSON 文件。

## 6. Standardize maps

```bash
lio-benchmark standardize map --run <run> --algorithm point_lio
```

统一重建规则：

```text
bag LiDAR scan timestamp
        ↓
standard trajectory time range
        ↓
linear position interpolation
quaternion shortest-arc SLERP
        ↓
LiDAR→IMU calibration
        ↓
world points
        ↓
common voxel rule
```

无法在容差内匹配的 scan 会被拒绝并计数，绝不退回 normalized-index matching。

## 7. Inspect maps interactively

```bash
lio-benchmark inspect --run <run> \
  --algorithms fast_livo2 point_lio leg_kilo2_lidar_imu \
  --color-mode height
```

Open3D settings panel 可开关每个 map / trajectory。Actions 中提供 XY、XZ、YZ、Perspective、Save Camera Preset 和 Export Screenshot。

可以加载：

```bash
--roi /path/to/roi.json
--camera /path/to/camera.json
```

ROI/camera JSON 是小型可版本管理的研究资产，可复用于论文图和 demo。

## 8. Generate paper artifacts

```bash
lio-benchmark report --run <run>
```

主要输出：

```text
metrics/summary.csv
figures/trajectory_xy.png
figures/map_xy_comparison.png
figures/map_xz_comparison.png
figures/map_yz_comparison.png
figures/runtime_comparison.png
reports/report.md
reports/report.html
```

这不是 ATE/真值评估器。没有 Ground Truth 时，报告不会把 start/end displacement 或 Z 差冒充定位真值误差。

## 9. Generate README GIF

```bash
lio-benchmark demo \
  --run <run> \
  --algorithms fast_livo2 point_lio leg_kilo2_lidar_imu \
  --output assets/demo/same_bag_map_comparison.gif
```

每个算法使用同一：

```text
run / bag
ROI
map reconstruction contract
plot bounds
camera motion
viewport
```

中间帧留在 run 下；只在人工确认 GIF 没有误导性后提交最终小体积 GIF。

README 引用：

```markdown
![Same-bag LIO map comparison](assets/demo/same_bag_map_comparison.gif)
```

## 10. Live Debug a failure

```bash
lio-benchmark live prepare \
  --dataset gaas_handheld_a \
  --algorithms fast_livo2 point_lio \
  --workspace ~/ros2_ws \
  --rate 0.5
```

打开生成的 `commands.md`，按顺序启动 bag 和一个 estimator。需要时：

```bash
ros2 topic hz <topic>
ros2 topic delay <topic>
ros2 run tf2_ros tf2_echo <a> <b>
```

发现异常：

```bash
lio-benchmark mark --session <session> \
  --algorithm point_lio \
  --event repetitive_row_misregistration \
  --bag-time 84.32 \
  --note "row alias begins after headland turn"
```

以后可以围绕 marker 时间截取前后局部 bag/trajectory/log 做失效分析。

## 11. Recommended P1 experiment use

把十算法/多算法探索和 P1 正文分开：

```text
Engineering benchmark
  = 所有可运行算法

P1 main comparison
  = 代表性固定基线 + frozen bags
```

建议固定同一温室不同采集轨迹 + 跨环境 bag，并始终保存失败案例。Benchmark 的目标不是证明某个算法“最好”，而是形成可审计证据说明为什么某个 mapping front end 被选入后续 Navigation Map derivation 实验。
