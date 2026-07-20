# 当前 MID360 基线

数据集：`navigation_20260719_164431`；SQLite3；2604.252 秒；LiDAR 26,043 帧；IMU 514,000 条。

当前只完成部署与运行前验证，不包含算法效果结论：

- 10 个算法配置已登记，playback rate 全部固定 1.0。
- 5 个源码工作区完成 Release 构建，MOLA 官方二进制 user overlay 可用，FAST-LIVO2 使用现有已构建工作区。
- 10 个配置对应的节点/模块完成无 bag 启动验证。
- 50 帧 MID360 只读字段抽样通过；真实 line 为 0–3，逐点时间转换后单调。
- manifest validate 和 doctor 全绿；单元测试 16/16。
- 当前 bag 无独立真值，禁止生成绝对精度指标。

待审阅风险：base 外参仍是 provisional；LIO-SAM 对 MID360 非重复扫描的运行可靠性必须通过短包验证；MOLA 外部重复 SIGINT 的退出缺陷需在 runner 中避免。

下一阶段入口：用户批准后，仅运行 30–60 秒 smoke，并再次停下审阅，不直接跑完整 43 分钟 bag。
