# MID360 温室 Z 轴漂移评测区

标准化实验编排、run 目录契约和新数据集模板已经独立到 `tools/lio_benchmark_base/`。本目录继续作为底层算法适配与分析脚本库。

本目录用于隔离后续 Livox MID360 数据完整性、IMU、时间同步和 LIO 轨迹 Z 轴漂移测试，不修改任何算法核心源码。

完整十算法 run 的综合报告使用：

```bash
python3 evaluators/generate_comprehensive_report.py \
  --run /home/yangxuan/lio_benchmark_runs/<run_id>
```

输出 `reports/comprehensive_comparison.{md,json,csv}` 和 `figures/comprehensive_comparison/comprehensive_summary.png`。其中 TOPS 是根据进程树 CPU 百分比和当前 CPU 的 AVX2/FMA FP32 峰值假设换算的同机代理值；没有 perf/GPU 计数时，不把它当作真实算法 TOPS。

单算法补跑后，使用 `benchmark_base/bin/lio-benchmark combine-run` 创建新组合归档，再执行标准化、`visualize_baseline_maps.py`、`resource-plot` 和 `comprehensive-report`。不要直接替换旧 run 的 `raw/mola_lio`，否则地图和报告来源会失去可审计性。

## 指定数据集

- rosbag2 目录：`/media/yangxuan/67AE0BEFE2F5AC661/6.7白云基地导航数据集/第一次录制整体框架/mid360_init_state2`
- sqlite3 文件：`/media/yangxuan/67AE0BEFE2F5AC661/6.7白云基地导航数据集/第一次录制整体框架/mid360_init_state2/mid360_init_state2_0.db3`

运行 `ros2 bag info` 和 `ros2 bag play` 时应传入 rosbag2 **目录**，而不是单独的 `.db3` 文件。

## 已确认的 bag 摘要

- 存储格式：sqlite3
- 时长：249.548663623 s
- 消息总数：54849
- `/livox/lidar`：`sensor_msgs/msg/PointCloud2`，2495 帧
- `/livox/imu`：`sensor_msgs/msg/Imu`，49868 帧
- `/cloud_registered`：`sensor_msgs/msg/PointCloud2`，2486 帧

后续生成的统计表、图片和报告统一写入 `output/`；该目录内的 `.gitkeep` 仅用于保留目录结构。

## 执行

```bash
source /opt/ros/humble/setup.bash
source /home/yangxuan/ros2_ws/install/setup.bash
python3 tools/lio_z_drift_evaluator/analyze_bag.py date/mid360_init_state2 --output date/output/bag_analysis.json
bash tools/lio_z_drift_evaluator/run_fast_livo_test.sh
python3 tools/lio_z_drift_evaluator/analyze_trajectory.py date/output/fast_livo_trajectory --output-dir date/output
```

本次完整结论见 `date/output/final_report.md`。

后续 Point-LIO、GLIM 和 DLIO 的源码版本、构建状态、输入兼容性与公平测试矩阵记录在 `date/ALGORITHM_SOURCES.md`。

GLIM 回环与全局优化结果见 `date/output/glim_full_slam/REPORT.md`。

DLIO MID360 适配、源码修复和 Z 轴结果见 `date/output/dlio_final/REPORT.md`。

四种前端的统一轨迹、点云地图可视化和中文报告见 `date/output/frontend_visual_comparison/REPORT.md`。重新生成命令：

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
MPLCONFIGDIR=/tmp/matplotlib-lio-compare \
  python3 tools/lio_z_drift_evaluator/visualize_frontend_comparison.py
```
