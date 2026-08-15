# Leg-KILO Current Master Adapter

## Identity

- Benchmark ID: `leg_kilo`
- Repository: `ouguangjun/Leg-KILO`
- Branch: `master`
- ROS2 package: `legkilo`
- Executable: `legkilo_node`
- Common benchmark mode: `LIO`
- Kinematics: disabled for ordinary handheld LiDAR+IMU datasets

This record is distinct from historical `leg_kilo2_lidar_imu`, which identifies the earlier `legkilo-v2` implementation.

## Extrinsic convention

Current-master source applies:

```text
point_body = extrinsic_R * point_lidar + extrinsic_T
```

and its official MID360 config documents this as `T_I_L`, LiDAR frame expressed in IMU frame. Therefore the benchmark convention is:

```text
LIDAR_TO_IMU
```

No inverse is applied when generating the current-master config from the benchmark canonical calibration.

## Run-local configuration

`evaluators/prepare_leg_kilo_config.py` reads the upstream official:

```text
legkilo/config/m3dgr_mid360.yaml
```

and changes only the dataset-dependent contract:

- lidar topic
- imu topic
- sensor mode = LIO
- canonical extrinsic T/R
- Livox nanosecond `time_scale`
- unique temporary result folder

The generated file lives under:

```text
configs/generated/leg_kilo/benchmark.yaml
```

The upstream repository config is never edited.

## Online outputs

Current ROS2 interface publishes:

```text
/Odometry
/path
/cloud_registered
/cloud_registered_body
```

These are retained in the raw algorithm output bag.

## Backend/runtime artifacts

The current backend automatically records its temporary result folder and flushes it when stopped. The adapter copies that folder into:

```text
raw/leg_kilo/leg_kilo_runtime/
```

Expected upstream evidence includes, when produced:

```text
frontend_frames.csv
submaps.csv
loop_edges.csv
submap point clouds and backend state
```

These artifacts are preserved even if a later official export step fails.

## Frontend/backend trajectories and Native Map

The live `/Odometry` topic represents frontend odometry. The official result saver can derive frontend and backend trajectories from the recorded runtime state and can export a global map. Those exports are separate derived upstream artifacts and must retain their roles:

```text
frontend -> ODOMETRY
backend  -> SYSTEM_MAPPING
```

Until the automatic/headless saver integration is verified, Native Map remains `NOT_PROVIDED`; the benchmark must not call `/cloud_registered` accumulation a Native global map.

## Viewer/headless execution

Current master creates its viewer at startup. If `DISPLAY` is unavailable, the runner uses `xvfb-run` when installed; otherwise the local run is blocked rather than modifying upstream viewer code.

## Acceptance

`adapter_status` remains `NOT_TESTED` until local Humble short-smoke and full-bag acceptance pass.
