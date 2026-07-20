# LIO Benchmark Tools

ROS 2 Humble 离线 LiDAR/LIO/SLAM 评测工具。当前分支已部署并登记 10 个独立实验配置：KISS-ICP、MOLA-LO、MOLA-LIO、FAST-LIVO2、Point-LIO、DLIO、GLIM odometry、GLIM full SLAM、LIO-SAM no-loop 和 LIO-SAM loop。

仓库只保存编排代码、manifest、参数、测试和必要 patch；外部算法源码、bag、构建目录和运行结果不进入 Git。外部工作区路径全部由 manifest 注入。

## 当前 MID360 检查点

```bash
source /opt/ros/humble/setup.bash

benchmark_base/bin/lio-benchmark validate \
  --config benchmark_base/config/navigation_20260719_164431.json

benchmark_base/bin/lio-benchmark doctor \
  --config benchmark_base/config/navigation_20260719_164431.json

benchmark_base/bin/lio-benchmark commands \
  --config benchmark_base/config/navigation_20260719_164431.json
```

当前状态是 `PRE_RUN_REVIEW_REQUIRED`：编译、配置、输入字段抽样和无 bag 节点启动已完成；尚未播放 bag。用户审阅后先执行 30–60 秒 smoke，再决定是否跑完整数据。

关键文档：

- [实现审计](benchmark_base/docs/IMPLEMENTATION_AUDIT.md)
- [算法部署与参数](benchmark_base/docs/ALGORITHM_INTEGRATION.md)
- [实验协议](benchmark_base/docs/EXPERIMENT_PROTOCOL.md)
- [MID360/LIO-SAM 限制](benchmark_base/docs/MID360_LIO_SAM_LIMITATIONS.md)
- [中文手册](benchmark_base/docs/USER_MANUAL_ZH.md)

## 公平性底线

- 所有 bag 播放固定 `--rate 1.0 --clock`。
- LiDAR-only、LiDAR–IMU odometry、full SLAM 分组，不做跨组总排名。
- 地图使用真实时间戳、SLERP 和完整 SE(3) 外参，不按轨迹百分比配扫描。
- 无独立真值时只输出 diagnostic，不生成 ATE/RPE 或“绝对精度”。
- 任何不兼容或失败配置输出明确失败状态，不生成伪结果。
