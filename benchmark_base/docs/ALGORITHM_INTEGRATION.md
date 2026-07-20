# 算法部署与接入记录

所有外部源码和构建产物位于 `/home/yangxuan/lio_benchmark_algorithms`，不进入本仓库。实际路径和版本固定在当前 manifest 中；以下是本次审阅摘要。

| 配置 | 上游版本 | 输入契约 | IMU / 外参 | 状态与限制 |
|---|---|---|---|---|
| KISS-ICP | PRBonn/kiss-icp v1.3.0 `b168352` | PointCloud2 `x y z intensity ring time` | 不使用 IMU | Release 构建及空载启动通过；LiDAR-only |
| MOLA-LO | Humble binary MOLA 2.9.0, LO 2.2.1 | 同上，GICP，Livox local-map nearby=2 | 不订阅 IMU，线性 deskew | 空载启动通过；关闭时有上游双 SIGINT 风险 |
| MOLA-LIO | 同上，state-estimation 2.4.2 | 同上 | SI IMU；IMU deskew=True；IMU→LiDAR 固定 pose | 空载启动通过；与 LO 分开报告 |
| FAST-LIVO2 | agt_navigation_v2 `1e96f08` | 原生 CustomMsg | 原始 g IMU；LiDAR→IMU `[.011,.02329,-.04412]` | 空载启动通过；图像关闭 |
| Point-LIO | dfloreaa/point_lio_ros2 `a8e2d0d` | PointCloud2；按 Velodyne 字段契约，4 line | 原始 g IMU，`acc_norm=1` | Release 构建及空载启动通过；其 CustomMsg 分支在该 fork 中不可用 |
| DLIO | vectr-ucla feature/ros2 `c8acc37` | PointCloud2，逐点相对秒 | SI IMU；使用逆外参 | Release 构建及空载启动通过；未修改上游源码 |
| GLIM odometry | GLIM v1.2.2 `faa264a` | PointCloud2，相对秒 | SI IMU；`T_lidar_imu` 按上游定义为 IMU→LiDAR | CPU Release 构建及空载启动通过 |
| GLIM full SLAM | 同上 | 同上 | 同上 | CPU odometry + sub-map + pose graph 均加载成功 |
| LIO-SAM no-loop | ros2 `08af3f3` | 独立 MID360 adapter 输出真实 line 和相对秒 | SI IMU；LiDAR→IMU | Release 构建、四节点空载启动及 50 帧字段验证通过；仍需短包验证非重复扫描模型 |
| LIO-SAM loop | 同上 | 同上 | 同上 | 与 no-loop 独立配置、独立结果；同样处于 pre-run validation 状态 |

## 构建与补丁

- KISS-ICP、Point-LIO、DLIO、LIO-SAM、GLIM 均以 `colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release` 构建。
- MOLA 使用官方 Humble `.deb` 解包到用户 overlay；精确版本见 manifest。
- GLIM 的 gtsam_points v1.2.2 在 Boost 1.74 上需要 `boost::none` constexpr 兼容补丁。补丁、目标、风险和回滚说明见 `patches/glim/README.md`。
- 其他算法未修改上游源码。FAST-LIVO2 的父工作区原本 dirty，本次未改其源码。
- 构建与 smoke 日志：`/home/yangxuan/lio_benchmark_algorithms/logs/`。

## 源码状态与安装路径

| 源码 | commit | dirty | install / 说明 |
|---|---|---:|---|
| kiss-icp | `b16835283aee` | no | `kiss_icp_ws/install` |
| point_lio_ros2 | `a8e2d0d5090a` | no | `point_lio_ws/install` |
| direct_lidar_inertial_odometry | `c8acc37100e3` | no | `dlio_ws/install` |
| GLIM | `faa264a1bce1` | no | `glim_ws/install` |
| glim_ros2 | `4a9e7a4cb084` | no | `glim_ws/install` |
| gtsam_points | `9d32e7dbecf6` | yes | 仅 Boost 兼容 patch；`glim_ws/deps_install` |
| LIO-SAM | `08af3f32f017` | no | `lio_sam_ws/install` |
| agt_navigation_v2 / FAST-LIVO2 | `1e96f08f992a` | yes | 用户原有 dirty 工作树；本任务未改上游源码 |

MOLA 不含源码工作树，来自官方 ROS 2 Humble 二进制：`mola=2.9.0`、`mola-lidar-odometry=2.2.1`、`mola-state-estimation=2.4.2`，安装在 `mola_ws/apt_root` 用户 overlay。完整构建输出保存在同名 `*_build.log`。

## 参数原则

- 播放倍率固定 1.0，使用 `/clock`，所有节点 `use_sim_time=true`。
- 统一转换字段：`x/y/z/intensity FLOAT32`、`ring UINT16`、`time FLOAT32 seconds relative to frame`。
- 转换时保留真实 `line`，按真实 `offset_time` 排序；不虚构 ring。
- 共同分析范围记为 0.5–70 m；算法原生过滤能力不同，报告中必须保存实际配置。
- 结果分三组：LiDAR-only odometry、LiDAR–IMU odometry、full SLAM；禁止跨组总排名。
