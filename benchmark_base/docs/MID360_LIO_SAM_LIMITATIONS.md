# MID360 与 LIO-SAM 限制

LIO-SAM 的特征组织假设源于规则多线扫描。MID360 是非重复扫描模式；CustomMsg 的 `line=0..3` 虽是真实字段，但不能证明它具有机械式 LiDAR 的规则方位组织。

当前 adapter 不合成 ring：它把真实 line 扩宽为 UINT16，把 `offset_time` 从 uint32 ns 转成相对帧头的 FLOAT32 秒，并按时间排序。50 帧、1,000,608 点的只读验证中，66 个 tag 非法点被丢弃，输出无时间倒退，范围 0–0.102348637 秒。

因此当前状态是 `PRE_RUN_VALIDATION`，不是算法效果通过。审阅后必须先跑 30–60 秒，检查接收计数、deskew、NaN、轨迹连续性和四节点健康；若失败，标记 `BLOCKED_INPUT_MODEL`，不得加入排行榜。
