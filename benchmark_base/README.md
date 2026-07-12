# LIO Benchmark Base

面向 ROS 2 LiDAR-IMU 前端的独立测试基座。它位于 `tools/`，不属于导航、底盘控制或在线定位功能包，也不会被正常 `colcon build` 自动编入机器人运行系统。

## 目标

- 用一份实验清单固定 bag、话题、单位、外参、算法版本和评测口径。
- 每次实验使用独立 run 目录，禁止覆盖历史结果。
- 原始输出、标准化轨迹、地图、日志、指标和报告分目录保存。
- 纯 odometry 与 full SLAM 分组比较。
- 所有自动报告保留数据限制，不能把首尾高度差自动称为真值误差。

## 快速开始

```bash
cd /home/yangxuan/ros2_ws

# 1. 检查实验清单、bag、话题和依赖脚本
lio_benchmark_tools/benchmark_base/bin/lio-benchmark validate \
  --config lio_benchmark_tools/benchmark_base/config/current_mid360.json

# 2. 创建一个不可覆盖的标准实验目录
lio_benchmark_tools/benchmark_base/bin/lio-benchmark init \
  --config lio_benchmark_tools/benchmark_base/config/current_mid360.json \
  --run-id greenhouse_mid360_001

# 3. 对新 run 执行 bag 数据质量分析
lio_benchmark_tools/benchmark_base/bin/lio-benchmark analyze-bag \
  --run runs/greenhouse_mid360_001

# 4. 算法运行仍使用 adapters/ 中明确可审计的适配命令
lio_benchmark_tools/benchmark_base/bin/lio-benchmark commands \
  --run runs/greenhouse_mid360_001

# 5. 收集环境、Git commit 和文件校验值
lio_benchmark_tools/benchmark_base/bin/lio-benchmark snapshot \
  --run runs/greenhouse_mid360_001
```

默认 run 根目录是工作区的 `runs/`，可以在实验清单的 `output_root` 中修改。

## 标准 run 目录

```text
runs/<run_id>/
├── manifest.json              # 已冻结的实验清单副本
├── RUN_STATUS.md              # 人工/自动状态记录
├── input/                     # 输入说明与校验值，不复制大 bag
├── configs/                   # 本次实际使用的参数副本
├── raw/
│   ├── fast_livo2/
│   ├── point_lio/
│   ├── glim_odometry/
│   ├── glim_full_slam/
│   └── dlio/
├── standardized/
│   ├── trajectories/          # 统一 CSV/TUM
│   └── maps/                  # 统一 PLY/PCD
├── metrics/                   # JSON/CSV 指标
├── figures/                   # PNG/SVG
├── reports/                   # 中文 Markdown 报告
├── logs/                      # ROS/算法/录包日志
└── metadata/                  # 环境、Git、校验值、命令记录
```

## 实验阶段

1. `validate`：检查 bag 目录、metadata、话题和工具。
2. `init`：冻结 manifest，建立 run 目录。
3. `analyze-bag`：数据、IMU、时间戳和逐点字段检查。
4. `run frontend`：分别运行 FAST-LIVO2、Point-LIO、GLIM odometry、DLIO。
5. `run backend`：只对支持后端的配置单独运行，例如 GLIM full SLAM。
6. `standardize`：导出统一坐标含义和采样口径的轨迹与地图。
7. `evaluate`：Z 极差、首尾差、路径归一化漂移、姿态范围和分段指标。
8. `visualize/report`：生成统一地图、轨迹图和报告。
9. `snapshot`：保存 Git commit、系统环境、命令和校验值。

## 公平比较规则

- 纯前端组：FAST-LIVO2、Point-LIO、GLIM odometry、DLIO。
- 后端组：GLIM full SLAM 或“前端 + 独立回环后端”。
- 不把 full SLAM 与纯 odometry 直接排名。
- 所有算法使用相同 bag、起止区间、LiDAR/IMU 外参和 IMU 单位。
- PointCloud2 必须保留逐点时间；格式转换必须记录字段映射。
- 地图比较使用相同扫描、点采样和体素分辨率。
- 没有真值和等高测量时，`z_end - z_start` 只能称为首尾 Z 差。
- 不允许通过锁死 Z/roll/pitch 或降低回环阈值美化结果。

## 与现有工具的关系

- `benchmark_base`：实验编排、目录契约、配置冻结、环境快照。
- `evaluators`：bag/轨迹分析、算法运行适配、地图可视化。
- `src/mid360_nav_demo`、导航与控制包：不被本基座修改或依赖。

当前完整实验可作为基准样例，见 `config/current_mid360.json` 和 `docs/CURRENT_BASELINE.md`。

完整原理、输入规则、指标解释、四算法命令和故障排查见 [docs/USER_MANUAL_ZH.md](docs/USER_MANUAL_ZH.md)。
