# 实验协议

1. `validate` 与 `doctor` 必须全通过。
2. 创建全新不可覆盖 run，冻结 manifest、配置、commit 和命令。
3. 先以 `lio-benchmark run --run <run> --duration 60` 执行 smoke；任何算法没有有效轨迹、崩溃或输入不兼容时停止该配置并分类失败。
4. 用户审阅 smoke 后才执行完整 bag；所有算法固定 `--rate 1.0 --clock`。
5. 每个算法独立 ROS domain、输出目录和记录 bag；不得混入当前机器人系统的话题。
6. 标准化真实传感器时间，求共同有效时间区间，地图使用 SE(3) 插值和完整外参。
7. LiDAR-only、LiDAR–IMU odometry、full SLAM 分组报告。无真值时只给 diagnostic。
8. 默认完整实验重复三次，保存资源、健康、退出码和失败分类。

当前检查点为 `PRE_RUN_REVIEW_REQUIRED`。尚未执行任何 bag playback。
