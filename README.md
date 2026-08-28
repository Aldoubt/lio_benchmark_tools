# LIO Benchmark Tools

ROS 2 Humble 离线 LiDAR/LIO/SLAM 多算法评测框架。当前仓库已经接入并跑通 10 个独立实验配置：KISS-ICP、MOLA-LO、MOLA-LIO、FAST-LIVO2、Point-LIO、DLIO、GLIM odometry、GLIM full SLAM、LIO-SAM no-loop 和 LIO-SAM loop。

这里的“10 个算法”更准确地说是 7 个算法家族下的 10 个可复现实验配置：GLIM odometry/full SLAM、LIO-SAM no-loop/loop、MOLA-LO/MOLA-LIO 分别是同一算法家族下的不同使用策略。框架的目标不是给出没有真值支撑的绝对排名，而是把输入契约、版本、参数、资源消耗、轨迹健康和相对地图诊断固定下来，让不同策略能在同一 bag 上被审计、复现和继续调参。

Git 跟踪部分只保存编排代码、manifest、参数、测试和必要 patch；外部算法源码、bag 原始数据、构建目录和完整运行产物不进入 Git。当前工作区的 `artifacts/` 是用于查看本轮结果的本机归档，外部工作区路径全部由 manifest 注入。

> 顶层 README 已恢复为完整多算法说明版本。本轮 comparison/resource 可视化的新增说明集中维护在 `benchmark_base/docs/COMPARISON_VISUALIZATION.md`，避免用局部功能说明覆盖仓库总览。
