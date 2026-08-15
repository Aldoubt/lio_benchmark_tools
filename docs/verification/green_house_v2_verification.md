# LIO Benchmark Tools V2 Green-House Verification

验收日期：2026-08-15  
分支：`feat/lio-benchmark-v2`  
修复 commit：`3807a03` (`fix: support green-house custom rosbag contract`)  
Frozen run：`/home/yangxuan/lio_benchmark_runs/green_house_v2_smoke_003`

## 1. Environment

| Item | Result |
|---|---|
| OS | Linux 6.8 x86_64 |
| ROS | ROS 2 Humble |
| Python | 3.10.12 |
| Open3D | 0.19.0 |
| ffmpeg | 未安装 |
| GPU | NVIDIA driver unavailable；FAST-LIVO2 使用当前 CPU/ROS 环境运行 |
| workspace | `/home/yangxuan/agt_navigation_v2` |
| bag | `/home/yangxuan/agt_navigation_v2/runtime/rosbag/green-house` |
| run output | 仓库外 `/home/yangxuan/lio_benchmark_runs/green_house_v2_smoke_003` |

仓库自身测试：32 tests passed；`compileall` passed；`bash -n evaluators/*.sh` passed；固定 baseline registry 六项均可解析。

## 2. Bag Contract

这是 rosbag2，storage backend 为 `sqlite3`，文件为 `green-house_0.db3`，大小约 2.4 GiB，duration `622.994416876 s`，总消息数 `130830`。

| Topic | Type | Count | Frame |
|---|---|---:|---|
| `/agt/sensors/lidar/custom` | `livox_ros_driver2/msg/CustomMsg` | 6230 | `livox_frame` |
| `/agt/sensors/imu/data` | `sensor_msgs/msg/Imu` | 124600 | `livox_frame` |

没有 camera。LiDAR 不是 `PointCloud2`，而是 `CustomMsg`：`timebase:uint64`（absolute ns）、`offset_time:uint32`（relative ns）、`x/y/z:float32`（m）、`reflectivity/tag/line:uint8`。抽样帧点数约 19968–20064，`offset_time` 最大约 100 ms，点时间单位确认是 ns。

IMU 的 angular velocity 按 `rad/s` 使用；linear acceleration 抽样范数约 1.0，表现为 g-like 原始单位，DLIO adapter 的 `9.80665` 缩放仍是显式 provenance。bag 未提供 camera、TF 或 ground truth。

标定来源 `/home/yangxuan/agt_navigation_v2/runtime/calibrations/handheld_mid360_sensor_v01.yaml` 明确为 `PENDING_NUMERIC_VERIFICATION`，LiDAR-IMU 数值为空。实验暂记录 legacy config 中的 `[0.011, 0.02329, -0.04412]` 和单位旋转矩阵，但标记为 `BLOCKED_CALIBRATION`，不得视为已确认标定。

## 3. Core Tests

- `python3 -m unittest discover -s benchmark_base/tests -v`: PASS, 32/32。
- `python3 -m compileall -q benchmark_base evaluators visualization reporting`: PASS。
- `bash -n evaluators/*.sh`: PASS。
- `lio-benchmark validate ...`: PASS。
- `lio-benchmark validate ... --verify-hash`: PASS（数据集未提供 hash，因此没有伪造 hash 验证）。
- `init`, `snapshot`, `analyze-bag`, `commands`: PASS；manifest 冻结 dataset 与 algorithm registry snapshot。

## 4. Algorithms

| Algorithm | Environment | Launch | Full Bag | Trajectory | Map | Status |
|---|---|---|---|---|---|---|
| FAST-LIVO2 | installed and runnable | PASS | PASS, 6230 LiDAR frames | PASS, 6227 odometry samples | diagnostic artifact available; calibration acceptance blocked | PASS |
| Point-LIO | ROS package not installed | NOT TESTED | NOT TESTED | MISSING | MISSING | BLOCKED_ENVIRONMENT |
| DLIO | ROS package not installed | NOT TESTED | NOT TESTED | MISSING | MISSING | BLOCKED_ENVIRONMENT |
| GLIM Odometry | ROS package not installed | NOT TESTED | NOT TESTED | MISSING | MISSING | BLOCKED_ENVIRONMENT |
| GLIM Full SLAM | ROS package not installed | NOT TESTED | NOT TESTED | MISSING | MISSING | BLOCKED_ENVIRONMENT |
| Leg-KILO 2.0 LiDAR-IMU | no executable local adapter; upstream/local bridge not validated | NOT TESTED | NOT TESTED | MISSING | MISSING | BLOCKED_ENVIRONMENT |

FAST-LIVO2 used one isolated ROS domain and ran alone. The corrected runner launches `agt_mapping/fast_livo2_mapping.launch.py`, replays the original CustomMsg/IMU topics, enables simulated time, and plays `/clock`. The final run returned code 0. Its recorded trajectory bag duration was `622.606663464 s`, with 6227 `/aft_mapped_to_init` and 6227 `/path` messages.

The earlier failed attempts are retained in `green_house_v2_smoke_001` and `green_house_v2_smoke_002`; they exposed launch-name, stale recorder-directory, and wall-clock issues. No failure log was deleted.

## 5. Timestamp Standardization

Final FAST-LIVO2 standardized trajectory:

- samples: 6227
- time: `1767659506.7347057` to `1767660129.3403108`
- duration: `622.605605 s`
- timestamps strictly increasing: PASS
- quaternion maximum norm error: `2.22e-16`
- NaN: none
- source topic: `/aft_mapped_to_init`

The existing `Trajectory.interpolate_pose()` tests passed, including linear position interpolation, shortest-arc quaternion SLERP, tolerance enforcement, and out-of-range rejection. The real map run used this interpolation path; it did not use normalized index matching.

## 6. Map Standardization

FAST-LIVO2 output: `standardized/maps/fast_livo2/unified_map.ply`

- `map_source`: `UNIFIED_RECONSTRUCTION`
- voxel: `0.12 m`
- point count: `772631`
- selected scans: `1246`
- matched scans: `1238`
- unmatched scans: `8`
- timestamp source: `HEADER_STAMP`
- trajectory source: standardized FAST-LIVO2 trajectory
- map bounds: X `[-9.7305, 58.6977]`, Y `[-73.0085, 38.8630]`, Z `[-3.3465, 63.2495]` m
- finite XYZ: PASS
- duplicate XYZ ratio: no duplicate rows detected in loaded PLY

The 8 unmatched scans are retained in metadata rather than silently included. Matching used the configured 0.05 s tolerance; the maximum nearest-sample gap was 0.04993 s. Map acceptance remains calibration-blocked because the numeric extrinsic is not verified for this bag.

## 7. Inspector

- Open3D import: PASS。
- Inspector process launched and remained alive for the 15 s GUI probe: PASS for launch smoke.
- Standardized artifact immutability during display: PASS by command path review; display alignment is not written back.
- Manual visual checklist (multi-algorithm toggle, shared camera, ROI, XY/XZ/YZ, screenshot): `BLOCKED_ENVIRONMENT`，当前仅有 FAST-LIVO2 地图，且本次 API 环境无法人工确认 GUI 画面。

## 8. Report

`lio-benchmark report`：PASS。

生成了 `summary.csv`、Markdown/HTML 报告及 trajectory/map/runtime figures。报告将 Point-LIO、DLIO、GLIM 明确显示为 `MISSING`，没有转换为 0；FAST-LIVO2 地图标注为 `UNIFIED_RECONSTRUCTION`。

## 9. Demo GIF

- 同一 frozen run 生成 demo frames：PASS。
- 缺失 Point-LIO 被明确跳过：PASS。
- 统一 bounds/camera/display alignment 规则：PASS（由生成器执行）。
- GIF 合成：`BLOCKED_DEPENDENCY`，机器没有 `ffmpeg`。生成器已输出完整帧和可复制的 ffmpeg 命令，未将 GIF 写入仓库。

## 10. Live Debug

- `live prepare`：PASS，session 为 `/tmp/lio_live_sessions/green_house_verify_001`。
- 生成 `session.json`、`env.sh`、bag play、FAST-LIVO2、Point-LIO command files：PASS。
- shell syntax check：PASS。
- marker append：PASS；两个 marker 均保存在 `markers/events.jsonl`，旧 marker 未被覆盖。
- 实际 Point-LIO 手动 smoke：`BLOCKED_ENVIRONMENT`，因为本机没有 Point-LIO ROS package。
- 实际 FAST-LIVO2 已通过正式 frozen run 的真实 bag replay；未在 live session 中重复启动第二个 estimator。

## 11. Bugs Found and Fixed

1. Problem: `analyze_bag.py` 与真实 bag topic 写死为旧 `/livox/...`，并对 CustomMsg 全量反序列化导致不必要的长时间/内存开销。  
   Root cause: 只覆盖历史 PointCloud2/旧 topic contract。  
   Fix: 按 bag 类型识别 IMU/LiDAR，CustomMsg 只抽样解析，完整记录计数仍保留。  
   Regression test: core tests 32/32；真实 bag analysis PASS。

2. Problem: `standardize_map.py` 只支持 PointCloud2。  
   Root cause: V2 standardizer 未覆盖实际 Livox CustomMsg。  
   Fix: 增加 CustomMsg 点提取、时间基准/offset 解析和统一地图重建。  
   Regression test: `test_custom_msg_contract.py`；真实地图 PASS。

3. Problem: FAST-LIVO2 runner 使用不存在的 launch 文件、未检查 estimator/recorder 启动、使用 wall time。  
   Root cause: runner 沿用旧独立 workspace contract。  
   Fix: 使用实际 `agt_mapping` launch，增加启动门禁，使用 `use_sim_time` 与 `--clock`，保留 recorder 失败。  
   Regression test: 最终真实 623 s bag replay PASS，轨迹时间域与输入一致。

## 12. Remaining Blockers

- benchmark implementation: Point-LIO/DLIO 的真实 CustomMsg topic adapter 尚未完成；当前 PointCloud2-only converter 不能直接消费本 bag。它们因此未被伪记为 PASS。
- algorithm upstream/environment: Point-LIO、DLIO、GLIM ROS packages 未安装；Leg-KILO 没有已验证 adapter/ROS1↔ROS2 bridge。
- machine/dependency: ffmpeg 未安装；GUI checklist 无法在本 API 环境中人工确认。
- data/calibration: `handheld_mid360_sensor_v01.yaml` 没有数值 LiDAR-IMU 外参，只有 pending calibration boundary。当前 unified map 仅为诊断产物，不是正式可比较结果。

## 13. Final Verdict

## V2 CORE COMPLETE, INTEGRATION INCOMPLETE

核心 registry、frozen run、真实 ROS 2 bag 分析、FAST-LIVO2 独立完整回放、simulated-time 轨迹标准化、CustomMsg 统一地图、报告和 Live Debug marker 已形成可审计闭环；但固定基线中只有 FAST-LIVO2 可运行，标定未确认，Point-LIO/DLIO/GLIM/Leg-KILO 仍有明确外部环境或 adapter blocker，Inspector 人工 GUI 和 GIF 合成也未全部完成，因此不能判定 `V2 COMPLETE`。
