# KISS-ICP Adapter

## Purpose

`kiss_icp` is the LiDAR-only control baseline. It is deliberately excluded from the Common LiDAR+IMU scoreboard and does not require LiDAR-IMU calibration.

## Upstream

- Repository: `PRBonn/kiss-icp`
- Branch: `main`
- ROS2 package: `kiss_icp`
- Node: `kiss_icp_node`
- Input: `sensor_msgs/msg/PointCloud2`
- Odometry output: `/kiss/odometry`

## Livox CustomMsg adaptation

The green-house dataset uses `livox_ros_driver2/msg/CustomMsg`, while upstream KISS-ICP consumes PointCloud2.

`evaluators/livox_custom_to_pointcloud2.py` republishes:

```text
x float32
y float32
z float32
t uint32 = Livox offset_time
```

KISS-ICP upstream recognizes `t`, `time`, `times`, `timestamp`, or `timestamps` and normalizes integer timestamps for deskew. The converter therefore preserves the Livox per-point temporal ordering instead of dropping point time.

No IMU topic is passed to KISS-ICP.

## Native map semantics

Upstream `/kiss/local_map` is a local voxel-map debug output. It is retained as a diagnostic topic but is **not** labeled as a Native global map.

For the two-map benchmark contract:

```text
Native Map = NOT_PROVIDED
Unified Map = generated from KISS-ICP odometry + common frozen LiDAR scans
```

## Acceptance

`adapter_status` remains `NOT_TESTED` until a real-machine short smoke and full-bag run succeed.
