# 数据集要求

输入必须是带 `metadata.yaml` 的 rosbag2 目录。manifest 必须明确 storage、LiDAR/IMU 话题和类型、时间字段、单位、外参方向、起止区间以及真值状态；不能确认的字段使用 `UNRESOLVED`。

本次 MID360 原始输入为 CustomMsg：`offset_time` 是相对帧头的 uint32 纳秒，`line` 是 0–3 的真实线号，IMU 加速度单位为 g。统一 PointCloud2 adapter 输出相对秒并按时间排序。需要 SI 的算法使用统一 IMU scaler。

若缺少可靠 LiDAR–IMU 外参，只能运行 KISS-ICP 和 MOLA-LO。若没有独立真值，可以运行算法，但只能生成 diagnostic 指标。
