# FAST-LIVO2 基准地图对比

当前默认使用 FAST-LIVO2 的 LIO 模式作为相对基准。该模式在 `configs/algorithms/fast_livo2/mid360.yaml` 中关闭图像输入，保留 LiDAR 和 IMU。

生成当前 run 的地图和轨迹对比：

```bash
source /opt/ros/humble/setup.bash
source /home/yangxuan/agt_navigation_v2/install/setup.bash
source /home/yangxuan/lio_benchmark_algorithms/adapter_ws/install/setup.bash
python3 evaluators/visualize_baseline_maps.py \
  --run /home/yangxuan/lio_benchmark_runs/navigation_20260719_round1_smoke60_20260721_001 \
  --baseline fast_livo2 \
  --scan-step 1 --point-step 20 --voxel 0.12
```

输出目录为 run 下的 `figures/fast_livo2_baseline_maps/`，包括每个算法的 PLY 地图、三视图 PNG、10 算法 XY 总览、基准对齐轨迹图和 `visualization_metadata.json`。

地图使用原始 CustomMsg 的真实点时间、manifest 中的 LiDAR-to-IMU 外参和姿态 SLERP；其他算法只做共同起点的初始 yaw+平移对齐。没有独立真值时，输出指标属于 relative-to-baseline diagnostic，不代表绝对精度，也不生成 ATE/RPE。
