# 十算法 ROS 2 版本锁定

本清单对应完整实验 `mapping_20260719_172810_full807_round1_001`，记录时间为 2026-07-22。实验运行环境为 Ubuntu 22.04、ROS 2 Humble（`ROS_VERSION=2`）。机器可读版本锁定文件是：

[`benchmark_base/config/mapping_20260719_172810_versions.lock.json`](../config/mapping_20260719_172810_versions.lock.json)

## 版本表

| 算法 | ROS 2 发行版 | 实现版本/引用 | 固定 commit | 额外 patch |
|---|---|---|---|---|
| KISS-ICP | Humble | v1.3.0 | `b1683528` | 无 |
| MOLA-LO | Humble | `mola_launcher 2.9.0`、`mola_lidar_odometry 2.2.1` | Humble 二进制包 | 无 |
| MOLA-LIO | Humble | `mola_launcher 2.9.0`、`mola_state_estimation 2.4.2`、`mola_lidar_odometry 2.2.1` | Humble 二进制包 | 无 |
| FAST-LIVO2 | Humble | `fast_livo` package 0.0.0，来源于 `agt_navigation_v2` | `1e96f08f` | 无 |
| Point-LIO | Humble | `point_lio` package 0.0.0 | `a8e2d0d5` | 无 |
| DLIO | Humble | `direct_lidar_inertial_odometry` 1.1.1 | `c8acc371` | `patches/dlio/spaciousness_bounds.patch` |
| GLIM odometry | Humble | v1.2.2 | `faa264a1` | `patches/glim/gtsam_points_v1.2.2_boost_none.patch` |
| GLIM full SLAM | Humble | v1.2.2 | `faa264a1` | `patches/glim/gtsam_points_v1.2.2_boost_none.patch` |
| LIO-SAM no-loop | Humble | `lio_sam` package 1.0.0 | `08af3f32` | 无 |
| LIO-SAM loop | Humble | `lio_sam` package 1.0.0 | `08af3f32` | 无 |

完整仓库地址、分支和 40 位 commit 在 JSON 锁定文件及本次 run 的 `manifest.json` 中保留。DLIO/GLIM 的 patch 必须在构建对应工作区时重新应用；不能只 checkout 上游 commit 而跳过 patch。

## 迁移到另一台电脑

1. 安装 Ubuntu 22.04 和 ROS 2 Humble，确认 `source /opt/ros/humble/setup.bash` 后 `echo "$ROS_DISTRO"` 输出 `humble`。
2. 按锁定文件 checkout 各算法源码的 commit；MOLA 使用对应版本的 Humble 二进制包。
3. 重新构建各算法工作区及 `lio_benchmark_adapters`，然后修改实验 manifest 中的 `workspace`、`source`、`setup_scripts`、`required_executables`、`dataset.bag_dir` 和 `output_root` 绝对路径。
4. 先执行 `validate`、`doctor` 和 `commands`，确认路径和可执行文件全部存在，再创建新的 run。不要直接复用旧 run 目录。

仓库不会提交外部算法源码、ROS `install/`、构建产物或 bag。这样可以避免把特定电脑的二进制路径误当成可迁移依赖，同时用 commit、patch 和配置文件保留实验的可复现边界。
