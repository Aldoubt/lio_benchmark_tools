# 飞行 bag 软件审计与合成回归

本轮审计日期：2026-10-30。原始代码基线：`bdbe60622a6370b20db0940a599f170571ce0414`。
用户确认尚未开始收集飞行 bag，因此本次证据仅来自源代码、单元测试、合成消息序列。
没有运行算法回放、ROS 节点、机器人驱动或硬件命令。首次本地验证后，按用户后续要求整理为独立云端分支 `feat/offline-flight-bag-audit`，等待真实数据集验证。

## 先核实的已有能力

| 项目 | 原有实现 / 测试 | 已确认的范围 |
|---|---|---|
| bag 时间统计 | `evaluators/analyze_bag.py` | 录制/消息时间间隔、非递增计数、record-header 时差、IMU/点时间统计；原先导入即依赖 ROS |
| 轨迹标准化 | `normalize_samples` / `test_trajectory_standardization.py` | 排序、去零戳/重复戳，保留输入回退计数；标准化后的轨迹不能还原所有原始时序证据 |
| 位置与 yaw 跳变 | `trajectory_discontinuity.py` / 同名测试 | MAD 自适应阈值 + 固定下限，时间戳事件，yaw 跨 ±π 不误报；不是精度评估 |
| 固定频率诊断 | `diagnostic_timeline.py` / 同名测试 | 轨迹重采样、事件聚类、资源关联；原先在长断流内仍然插值 |
| 无真值边界 | `evaluation.py` / `test_metric_naming.py` | 无独立真值禁止 ATE/RPE 类命名 |
| README 的十配置结果 | 历史描述与 manifest | 本次未重跑，也没有把历史描述计作当前机器的集成测试通过 |

最小修改路线：提取共享时间审计逻辑 → 修复原始顺序与缺失头配对 → 复用位姿检测并补三维旋转 → 合成回归与证据输出。
没有新增 requirements 或安装包。时间审计只用标准库，位姿和回归使用仓库已有 NumPy。

## 本轮改动

- `timing_audit.py`：保留 reader 顺序，区分严格回退、重复、长间隔、缺失和非有限时间；记录样本索引。零戳单独计数，允许模拟时钟从 0 开始。
- `analyze_bag.py`：共享上述逻辑；旧 `*_time_reversals` 保留非递增含义，新 `timing_audit` 提供准确分类。未知消息类型仍统计录制消息数量，缺失 header 使用占位保持配对。最近 IMU 时间改用排序副本和二分查找，原始异常不被排序删除。
- `flight_bag_audit.py`：JSON/rosbag2 sqlite3 离线入口。真实 bag 必须明确选话题；支持 header、Odometry、PoseStamped、PoseWithCovarianceStamped 的常规 pose 结构。姿态使用 XYZW 四元数最短旋转角，覆盖 roll/pitch；q 与 -q 不算跳变。未知类型保留记录时钟，并说明缺少解码。
- 位姿差分跳过非正时间差、长间隔、非法位姿和坐标系切换。yaw 差分使用逐对角度包络，单个 NaN 不再污染整段后续数据。
- `diagnostic_timeline.py`：新增 `--max-gap-s`，默认 0.5 s；不在长间隔内插值，跨间隔的运动量以 `motion_valid=false` 标记。无效运动行的数值 0 仅为占位，不能解释为静止；下游应检查该字段。
- 新增 15 场景回归与 6 个可选真实 CDR/sqlite3 往返测试。合成命令拒绝复用输出目录，防止覆盖证据。

## 复现：Windows，无需 ROS/WSL

在仓库根目录执行，当前机器 Python 3.12.0、NumPy 2.2.6、pytest 9.1.1：

```powershell
$env:PYTHONNOUSERSITE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONUTF8='1'
python -X utf8 -m pytest -q tests/test_timing_audit.py tests/test_flight_bag_audit.py tests/test_analyze_bag_timing.py tests/test_flight_bag_ros2.py tests/test_trajectory_discontinuity.py tests/test_trajectory_standardization.py tests/test_diagnostic_timeline.py tests/test_metric_naming.py
python -X utf8 evaluators/synthetic_bag_regression.py --output-dir output/flight_audit_reproduction_001
python -X utf8 evaluators/flight_bag_audit.py --input-json output/flight_audit_reproduction_001/combined/input.json --output-dir output/flight_audit_single_001
```

每次重跑换新的输出目录。Linux 的纯软件命令相同，Python 可写为 `python3`。

每个合成场景产生 `input.json`、`injection.json`（输入 SHA-256、明确的已知修改、独立预期）、`audit.json`、`audit.md`。
汇总见 `regression.json` / `regression.md`。检测器只接收 records，不读取 injection manifest 或 expected 字段。

默认审计阈值：时间间隔严格大于 0.5 s，正 record-header 时差严格大于 0.2 s；所有负时差单列。
位姿采用 `max(floor, median + 10 × 1.4826 × MAD)`；位置下限 0.5 m，yaw/完整旋转下限 10°。
这些只是复核触发阈值，不是飞行合格标准。不同频率的话题应分开调用并设定 `--gap-threshold-s`，不能直接沿用统一阈值判断丢帧。

## 合成结果：注入事实与观测严格分开

| 场景 | 生成器已知操作 | 检测器观测 | 不能据此认定 |
|---|---|---|---|
| 正常对照 | 80 条，10 Hz，record-header=0.02 s | 无阈值事件 | 实际飞行通过 |
| header 回退 | 第 20 条及后续 header 减 0.4 s | 1 次严格回退，60 条大时差 | 时钟硬件故障已定位 |
| 录制时间回退 | 第 20 条 record 减 0.3 s | 1 次 reader 顺序回退、1 次负时差 | sqlite3 时间排序后仍能恢复原始写入顺序 |
| 重复戳 | header[20]=header[19] | 1 次重复，0 次严格回退 | 丢包 |
| 断流 | 删除原始 20..29 共 10 条 | 两类时钟各 1 个 1.1 s 间隔；不跨缺口计算位置跳变 | 真实数据一定丢了 10 包或由网络导致 |
| 延迟阶跃 | 后 60 条 record 增加 0.35 s | 后 60 条时差约 0.37 s | 真实传输延迟已测得 |
| 恒定延迟 / 时钟偏移 | 两种生成器解释、相同 record 数值变化 | 两份观测完全相同 | 能凭这组数据区分两种原因 |
| 负时差 | 所有 header 增加 10 s | 80 个负时差 | 物理负延迟 |
| 平移跳变 | 后半段 x 增加 2 m | 1 次位置步长异常（步长 2.1 m） | 漂移精度为 2.1 m |
| yaw / roll / pitch | 后半段分别加 90° / 60° / 60° | yaw 用例 1 个 yaw 和旋转事件；roll/pitch 各 1 个旋转事件 | 所有跳变都是估计器失败 |
| 四元数符号 | 后半段 q 改成 -q | 无姿态跳变 | 符号变化是姿态变化 |
| 混合 | 断流、header 回退、位置步阶叠加 | 各异常仍被保留 | 能自动定位实际飞行根因 |

候选解释仅列为 `UNCONFIRMED`：时钟重置、记录调度/缓冲、源停顿、传输中断、重定位、回环校正、真实快速运动等。没有独立证据时不做因果排序。

## 实测验证记录

使用同一 Windows/Python/UTF-8 环境，对 Git HEAD 的独立解包副本与修改后代码分别运行 `pytest -q tests --continue-on-collection-errors --disable-warnings --tb=line`：

| 检查 | 结果 |
|---|---|
| 原始 HEAD 全量基线 | 183 passed、11 failed、1 skipped、8 collection errors |
| 修改后全量 | 219 passed、11 failed、7 skipped、8 collection errors |
| 本轮聚焦测试 | 47 passed、6 skipped |
| 确定性合成回归 | 15/15 PASS |
| `git diff --check` | PASS |
| 真实 CDR/sqlite3 往返 | NOT_RUN：6 项因缺 ROS 2 跳过 |
| 真实飞行 bag / DDS QoS / 算法运行 / 硬件 | NOT_RUN |

两次全量检查的 11 个失败项与 8 个收集错误项一致；没有新增失败项，但绝不能表述为全量通过。
其中：SciPy 缺失导致 8 个收集错误及 1 个 viewer 测试失败；Jinja2/ReportLab 缺失导致 7 个报告测试失败；psutil 缺失导致 1 个测试失败；另有 POSIX 路径断言和开发机绝对路径 manifest 各 1 项失败。
原有 manual controller 的退出清理还触发 Windows 无 `os.killpg` 警告。它不在此次离线审计执行链内，没有改写 Linux 进程控制逻辑。
初次未开启 UTF-8 时还出现 3 个 GBK 解码失败；上表已统一 `-X utf8`，这不是本轮算法修复。

本机产物：`output/flight_audit_20261030_001/`；完整日志：`output/baseline-utf8-tests.txt`、`output/post-utf8-tests.txt`。
测试替身覆盖 bag reader 接口、未知类型计数和缺失 header 配对；它们不替代真实 ROS CDR 集成测试。

## 云端交接：等待真实数据

2026-10-30 推送前检查了全部远端分支和开放 PR（当时无开放 PR）：

| 分支 | 检查时的 HEAD | 处理 |
|---|---|---|
| `main` | `bdbe60622a6370b20db0940a599f170571ce0414` | 作为本轮基线 |
| `feat/phase-aware-benchmark` | 同 `main` | 保持原状 |
| `feat/paper1-map-source-benchmark-freeze` | `3747464ea472df3d0c06f820a2fc8d5403bc5e7c` | 与 main 历史分叉；其两份新增文档与 main 内容一致，保持原状 |
| `feat/offline-flight-bag-audit` | 本轮新分支 | 保存审计代码、测试、报告；未合并到 main |

推送复核修正了 Windows 文本换行可能导致输入文件字节与清单 SHA-256 不一致的问题：输入改用固定 UTF-8 字节写入，并逐场景验证实际文件哈希。修复后重新运行聚焦测试（47 passed、6 skipped）、15 场景回归（全部通过）和全量测试（219 passed、11 failed、7 skipped、8 collection errors）；失败项仍与原始基线一致。云端验证记录中的源码 SHA-256 按 Git blob 字节计算，不受工作区换行转换影响。
可在 GitHub 直接查看的小型证据：[合成报告](evidence/flight_bag_audit_20261030/regression.md)、[机器可读场景结果](evidence/flight_bag_audit_20261030/regression.json)、[验证状态与源码哈希](evidence/flight_bag_audit_20261030/verification.json)。原始 bag、生成的输入序列、完整本机日志均不纳入 Git。

下一阶段状态为 `WAITING_FOR_REAL_DATA`，不是完整验收通过。数据回来后需同时提供实际话题及消息类型、录制窗口、header/record 时钟约定、外参版本，以及独立真值是否存在。
先执行 6 项真实 CDR/sqlite3 往返测试，再对真实 bag 只读审计；缺少真值时继续只报告健康诊断。尚未验证的 ROS 2/DDS、真实飞行与精度项目保持 `NOT_RUN`。

## WSL 判断与下一层验证

当前 `wsl --list --verbose` 显示没有安装 Linux 发行版。本轮没有安装 WSL、ROS、Docker 或 Gazebo。
纯 Python 软件回归已能运行，暂不需要 WSL。下一阶段要验证真实 rosbag2/CDR/custom msg 和 Linux 集成时，建议 WSL 2 + Ubuntu 22.04 + ROS 2 Humble，保持仓库版本基线；WSL 提供 Linux 环境，本身不模拟飞行器或验证实时性。

[Microsoft 的 WSL 安装说明](https://learn.microsoft.com/en-us/windows/wsl/install)支持指定发行版，新安装默认使用 WSL 2。
[ROS 2 Humble 官方安装文档源码](https://github.com/ros2/ros2_documentation/blob/humble/source/Installation/Ubuntu-Install-Debs.rst)指定 Ubuntu Jammy 22.04，并提供无 GUI 的 ros-base。

以下是后续环境准备命令，**本轮未执行**：

```powershell
wsl --list --online
wsl --install -d Ubuntu-22.04
```

Ubuntu 内先按官方文档完成 locale、ROS apt 源和系统更新，再安装最小测试依赖（不是整个算法栈）：

```bash
sudo apt install ros-humble-ros-base ros-humble-rosbag2-py ros-humble-rosbag2-storage-default-plugins ros-humble-nav-msgs python3-numpy python3-pytest
source /opt/ros/humble/setup.bash
export PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python3 -m pytest -q tests/test_flight_bag_ros2.py
```

这 6 项测试只创建、序列化、读取临时 sqlite3 bag，不启动节点、不连接机器人。
若要复现已有全量报告/可视化测试，再按仓库原有 dev/freeze 环境说明补既有依赖；不需要为此次审计安装所有 LIO 算法或仿真器。

收集到实际 bag 后，执行只读审计（话题名替换为实际值）：

```bash
python3 evaluators/flight_bag_audit.py --bag /path/to/flight_bag --topic /imu --topic /odom --output-dir output/flight_real_001 --gap-threshold-s 0.5 --offset-threshold-s 0.2
python3 evaluators/analyze_bag.py /path/to/flight_bag --manifest /path/to/manifest.json --output output/bag_analysis_001.json --gap-threshold-s 0.5
```

现阶段 bag reader 仅声明支持 sqlite3。自定义消息需安装对应消息定义；未知类型、选中但零消息话题会被明确记录。开头/末尾断流需预期录制窗口，完全未出现的话题需预期话题清单；这两类不能从中间相邻记录直接推断。
header 与 record 用浮点秒计算，不保证 epoch 时间下亚微秒差分精度；真实 bag reader 的排序可能隐藏录制写入顺序回退；最近时间匹配遇到时钟重置可能跨时段关联。
大 bag 当前仍将选中记录保存在内存中；未进行大规模内存性能验证。真实飞行的时钟同步、动态合理性、外参、QoS 与漂移精度均需后续独立证据。
