# LIO Benchmark Tools 原理与使用说明书

## 1. 工具能做什么

本工具用于对 ROS 2 LiDAR-IMU 数据和 LIO/SLAM 算法进行可复现的离线评测，重点包括：

- rosbag2 数据完整性、话题、消息数量和频率；
- 点云逐点时间字段及去畸变条件；
- IMU 单位、均值、模长、噪声和时间间隔；
- LiDAR 与 IMU 的时间同步统计；
- Odometry 轨迹的 X/Y/Z、roll/pitch/yaw；
- Z 极差、首尾 Z 差、路径长度和归一化 Z 漂移；
- 多算法轨迹、点云地图和三视图可视化；
- 纯 odometry 与带全局后端结果的分组比较；
- 实验配置、Git commit、环境、日志和报告归档。

当前已有适配：

- FAST-LIVO2
- Point-LIO
- GLIM odometry
- GLIM full SLAM
- DLIO

## 2. 不能自动保证什么

工具不能仅凭一个任意 bag 自动保证所有算法都能运行。开始实验前仍需满足：

1. 算法源码已 clone、依赖已安装并成功编译；
2. bag 中 LiDAR/IMU 消息类型与算法兼容；
3. 点云保留逐点时间；
4. IMU 单位已确认是 g 还是 m/s²；
5. LiDAR-IMU 外参方向和单位正确；
6. 算法输出 Odometry/Path 话题已写入实验清单；
7. 如果要计算绝对误差，需要真值轨迹；
8. 如果要把首尾 Z 差称为闭合误差，需要确认起终点是同一位置且真实等高。

因此它是“标准化、可复现的评测基座”，不是绕过传感器和算法适配的一键黑盒。

## 3. 总体原理

```text
rosbag2
   │
   ├── 点云字段/时间/频率检查
   ├── IMU 单位/模长/噪声检查
   └── LiDAR-IMU 同步检查
            │
            ▼
       运行 LIO 前端
            │
            ├── Odometry 原始 bag
            ├── 标准化轨迹 CSV
            └── 算法日志
            │
            ▼
      统一轨迹指标计算
            │
            ├── Z 极差
            ├── 首尾 Z 差
            ├── 路径长度
            ├── cm/100m
            └── roll/pitch 变化
            │
            ▼
 同一原始点云 + 各算法位姿重建地图
            │
            ├── PLY
            ├── XY/XZ/YZ 图
            └── 中文报告
```

## 4. 输入 bag 的规则

### 4.1 rosbag2 目录

命令输入应是包含 `metadata.yaml` 的目录，而不是单独 `.db3`：

```text
my_dataset/
├── metadata.yaml
└── my_dataset_0.db3
```

正确：

```bash
ros2 bag info /data/my_dataset
```

不推荐：

```bash
ros2 bag info /data/my_dataset/my_dataset_0.db3
```

### 4.2 支持的基础消息

- LiDAR：`sensor_msgs/msg/PointCloud2`
- IMU：`sensor_msgs/msg/Imu`
- 轨迹：`nav_msgs/msg/Odometry`

Point-LIO 的 MID360 模式通常要求 `livox_ros_driver2/msg/CustomMsg`。工具提供 `pointcloud2_to_livox_custom.py`，但只适用于当前已验证的字段布局。

### 4.3 MID360 PointCloud2 推荐字段

```text
x          FLOAT32
y          FLOAT32
z          FLOAT32
intensity  FLOAT32
tag        UINT8
line       UINT8
timestamp  FLOAT64（绝对纳秒）
```

如果缺少 `timestamp/time/t/offset_time`，高速运动时无法可靠去畸变，不能作为公平的 LIO 对比输入。

### 4.4 IMU 单位

- 静止模长约 1：单位通常是 g；算法需要乘 9.80665。
- 静止模长约 9.81：单位通常是 m/s²；不得再次缩放。

当前 MID360 bag 的模长约 0.99，属于 g：

- FAST-LIVO2：初始化后按均值自动缩放；
- Point-LIO：`acc_norm: 1.0`；
- GLIM：`acc_scale: 9.80665`；
- DLIO：通过 `scale_imu_acceleration.py` 显式转换。

## 5. 实验清单

复制模板：

```bash
cp benchmark_base/config/experiment.template.json \
   benchmark_base/config/my_dataset.json
```

必须填写的主要字段：

```json
{
  "workspace": "/absolute/path/to/ros2_ws",
  "output_root": "/absolute/path/to/ros2_ws/runs",
  "dataset": {
    "bag_dir": "/data/my_dataset",
    "db3": "/data/my_dataset/my_dataset_0.db3",
    "sha256": "...",
    "lidar_topic": "/livox/lidar",
    "imu_topic": "/livox/imu",
    "imu_acceleration_unit": "g",
    "point_time_field": "timestamp",
    "point_time_unit": "ns_absolute"
  },
  "calibration": {
    "rotation_lidar_to_imu_row_major": [1,0,0,0,1,0,0,0,1],
    "translation_lidar_to_imu_m": [0.011,0.02329,-0.04412],
    "source": "factory/project calibration"
  }
}
```

外参统一记录为 LiDAR→IMU：

```text
p_imu = R_lidar_to_imu × p_lidar + t_lidar_to_imu
```

如果某算法要求 IMU→LiDAR，必须先求逆，不能只复制相同数组。

## 6. 标准使用流程

以下假设：

```text
工具仓库：/home/yangxuan/ros2_ws/lio_benchmark_tools
算法工作区：/home/yangxuan/ros2_ws
```

### 6.1 加载 ROS 环境

```bash
cd /home/yangxuan/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
```

若 Point-LIO/DLIO/GLIM 使用隔离 install，还需加载对应环境。

### 6.2 验证清单

```bash
lio_benchmark_tools/benchmark_base/bin/lio-benchmark validate \
  --config lio_benchmark_tools/benchmark_base/config/current_mid360.json
```

同时校验 1.8 GiB bag 的 SHA-256：

```bash
lio_benchmark_tools/benchmark_base/bin/lio-benchmark validate \
  --config lio_benchmark_tools/benchmark_base/config/current_mid360.json \
  --verify-hash
```

### 6.3 创建不可覆盖的 run

```bash
lio_benchmark_tools/benchmark_base/bin/lio-benchmark init \
  --config lio_benchmark_tools/benchmark_base/config/current_mid360.json \
  --run-id greenhouse_20260712_001
```

工具拒绝覆盖同名 run。若要重测，应使用新的 run-id。

### 6.4 分析 bag

```bash
lio_benchmark_tools/benchmark_base/bin/lio-benchmark analyze-bag \
  --run runs/greenhouse_20260712_001
```

输出：

```text
runs/greenhouse_20260712_001/metrics/bag_analysis.json
runs/greenhouse_20260712_001/logs/analyze_bag.log
```

### 6.5 获取算法运行命令

```bash
lio_benchmark_tools/benchmark_base/bin/lio-benchmark commands \
  --run runs/greenhouse_20260712_001
```

该命令只打印可审计的运行命令，不自动连续启动所有耗时算法。建议逐个执行并检查日志，避免某算法失败后仍生成误导性报告。

### 6.6 保存环境快照

```bash
lio_benchmark_tools/benchmark_base/bin/lio-benchmark snapshot \
  --run runs/greenhouse_20260712_001
```

记录内容包括：

- 操作系统和 Python；
- ROS_DISTRO；
- Git branch、commit、dirty 状态；
- ros2、colcon、cmake、git 路径。

## 7. 单独运行算法

### 7.1 FAST-LIVO2

```bash
bash lio_benchmark_tools/evaluators/run_fast_livo_test.sh \
  /data/my_bag \
  runs/my_run/raw/fast_livo2
```

### 7.2 Point-LIO

```bash
bash lio_benchmark_tools/evaluators/run_point_lio_test.sh \
  /data/my_bag \
  runs/my_run/raw/point_lio
```

当前转换器要求 MID360 PointCloud2 字段布局与第 4.3 节一致。

### 7.3 GLIM odometry

```bash
bash lio_benchmark_tools/evaluators/run_glim_odometry_test.sh \
  /data/my_bag \
  runs/my_run/raw/glim_odometry \
  /path/to/glim_odometry_config
```

### 7.4 GLIM full SLAM

```bash
bash lio_benchmark_tools/evaluators/run_glim_full_slam_test.sh \
  /data/my_bag \
  runs/my_run/raw/glim_full_slam \
  /path/to/glim_full_slam_config
```

必须分别分析 `/glim_ros/odom` 和 `/glim_ros/odom_corrected`，不能只看后端结果。

### 7.5 DLIO

先确认目标 DLIO commit，再应用补丁：

```bash
git -C /path/to/dlio apply --check \
  lio_benchmark_tools/patches/dlio_ros2/mid360_time_handling.patch

git -C /path/to/dlio apply \
  lio_benchmark_tools/patches/dlio_ros2/mid360_time_handling.patch
```

然后运行：

```bash
bash lio_benchmark_tools/evaluators/run_dlio_test.sh \
  /data/my_bag \
  runs/my_run/raw/dlio
```

## 8. 轨迹分析原理

### 8.1 Z 极差

```text
E_z_range = max(z) - min(z)
```

表示整个轨迹经历的最大高度范围。它会包含真实坡度，因此不必然等于漂移。

### 8.2 首尾 Z 差

```text
Δz = z_end - z_start
```

只有确认起终点真实等高时，`abs(Δz)` 才能解释为高度闭合误差。

### 8.3 路径长度

```text
L = Σ ||p_i - p_(i-1)||
```

高频 Odometry 抖动会虚增路径。DLIO 约 200 Hz 输出，因此当前基线按 `min_dt=0.09 s` 抽样到约 10 Hz。

### 8.4 归一化 Z 指标

```text
D_z = abs(Δz) / L × 10000
```

输出单位为 `cm/100m`。没有等高条件时应称为“条件化指标”，不是绝对误差。

### 8.5 roll/pitch

工具输出姿态范围，用于判断 Z 变化是否和姿态变化同步。但范围包含真实转弯、坡度和安装倾角，不能直接称为姿态漂移。

## 9. 地图可视化原理

为了公平比较，统一地图使用：

```text
同一原始点云 + 各算法估计位姿 + 相同抽帧 + 相同点采样 + 相同体素
```

输出：

- 二进制 PLY；
- XY 俯视图；
- XZ、YZ 侧视图；
- 四算法轨迹对比图；
- 地图元数据 JSON。

统一重建图用于观察：

- 墙面或立柱重影；
- 行间结构弯曲；
- 地面/顶棚厚度；
- 转弯后地图错位；
- 高度颜色随路线系统变化。

体素后点数多不代表地图更好。重影和位姿误差也会占用更多体素。

## 10. 标准 run 输出说明

```text
runs/<run_id>/
├── manifest.json
├── RUN_STATUS.md
├── input/                 # bag 路径和校验值
├── configs/               # 实际参数副本
├── raw/                   # 算法原始输出
├── standardized/
│   ├── trajectories/      # CSV/TUM
│   └── maps/              # PLY/PCD
├── metrics/               # JSON/CSV
├── figures/               # PNG/SVG
├── reports/               # Markdown
├── logs/
└── metadata/
```

源码仓库不应提交 `runs/`。需要分享实验结果时，建议单独压缩指定 run 或使用数据制品存储。

## 11. 如何阅读结论

### 静止或短距离就漂移

优先检查：

- IMU 单位；
- 重力方向；
- 点云逐点时间；
- 时间同步；
- 外参方向；
- 初始化静止时间。

不要优先增加回环。

### 长直行中实时高度退化

优先考虑：

- 温室重复结构导致几何退化；
- 地面平面软约束；
- 轮速里程计；
- 非完整运动学约束；
- 垂向速度软约束。

单独增加回环不能修复实时定位。

### 返回旧区域后地图不闭合

适合测试：

- 地点描述子候选；
- 时间/拓扑过滤；
- GICP/VGICP 几何验证；
- 位姿图优化。

温室重复行有错误回环风险，不能只凭相似度加入回环边。

## 12. 常见故障

### `bag_dir 缺少 metadata.yaml`

传入了 `.db3` 文件或错误目录。把 `bag_dir` 改为 rosbag2 目录。

### IMU 模长约 1，但轨迹迅速飞走

算法可能按 m/s² 使用输入。确认是否需要乘 9.80665。

### 点云存在但算法不输出轨迹

检查：

- 消息类型是否匹配；
- QoS 是否兼容；
- `timestamp` 数据类型；
- IMU 是否覆盖扫描时间；
- 初始化是否完成；
- 输出话题是否写错。

### `Bad time sync between LiDAR and IMU`

先检查时间统计，不要直接调 offset。对大纪元绝对纳秒时间，还要检查算法是否错误使用 float。

### GLIM 全局优化没有改善

确认是否真的形成了经过几何验证的旧区域回环。连续子图保护边不等于回环。

### 地图看起来倾斜或 Z 达到数米

检查可视化是否用完整首帧 roll/pitch 旋转整条轨迹。重力对齐比较通常只消除起点平移和 yaw。

## 13. 新增算法

新增算法适配至少需要：

1. 一个运行脚本，参数为 `bag_dir output_dir [config_dir]`；
2. 明确输入 LiDAR、IMU 类型和逐点时间要求；
3. 明确 IMU 单位处理；
4. 明确外参定义；
5. 输出 `nav_msgs/msg/Odometry`；
6. 在 manifest 的 `algorithms` 中登记 mode、source、runner 和 trajectory topic；
7. 把源码 patch 单独放在 `patches/`，不得静默修改算法；
8. 补充 README 和一个最小 smoke test。

## 14. 推荐日常操作

每次新数据集遵循：

```text
复制 manifest
  → validate
  → init 新 run
  → analyze-bag
  → 人工确认单位/外参/时间
  → 逐个运行算法并检查日志
  → 标准化轨迹
  → 生成地图和报告
  → snapshot
  → 更新 RUN_STATUS.md
```

不要复用旧输出目录，不要覆盖算法日志，不要把测试 bag 提交到源码 Git 仓库。

