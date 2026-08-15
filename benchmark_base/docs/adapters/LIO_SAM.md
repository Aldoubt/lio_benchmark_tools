# LIO-SAM Adapter

## Identity and execution implementation

- Algorithm identity: `TixiaoShan/LIO-SAM`
- Benchmark ID: `lio_sam`
- Roles: `ODOMETRY`, `SYSTEM_MAPPING`
- Humble/MID360 execution integration: `UV-Lab/LIO-SAM_MID360_ROS2_PKG`
- ROS2 implementation submodule: `UV-Lab/LIO-SAM_MID360_ROS2`
- Package: `lio_sam`

The algorithm identity and the ROS2 execution implementation are recorded separately because the original repository is ROS1-oriented while the benchmark runtime is ROS2 Humble.

## Input gate: valid IMU orientation is mandatory

Official LIO-SAM rejects an invalid orientation quaternion and explicitly requires a 9-axis/orientation-capable IMU path for its initialization logic.

Therefore the adapter declares:

```text
dataset.capabilities.imu_orientation_valid = true
```

as a preflight requirement. Datasets that only provide reliable angular velocity and linear acceleration remain `BLOCKED_INPUT`; the benchmark does not fabricate orientation to make LIO-SAM run.

## Extrinsic semantics

LIO-SAM uses three calibration parameters with different semantics:

```text
extrinsicTrans = canonical LiDAR -> IMU translation
extrinsicRot   = IMU -> LiDAR rotation for acceleration/gyro
extrinsicRPY   = LiDAR -> IMU rotation; source internally inverts it for attitude conversion
```

`prepare_lio_sam_config.py` derives all three from the benchmark canonical `LIDAR_TO_IMU` rigid transform and does not edit the upstream params file.

## Run-local configuration

The adapter starts from the ROS2 integration's `config/params.yaml` and replaces only dataset-dependent values:

- point-cloud topic
- IMU topic
- disabled GPS topic
- Livox sensor profile / 4 scan lines
- the three extrinsic fields above
- heading initialization flag

Generated config:

```text
configs/generated/lio_sam/benchmark.yaml
```

## Retained outputs

The runner keeps when available:

```text
/lio_sam/mapping/odometry
/lio_sam/mapping/odometry_incremental
/lio_sam/mapping/path
/lio_sam/mapping/trajectory
/lio_sam/mapping/cloud_registered
/lio_sam/mapping/cloud_registered_raw
/odometry/imu
/odometry/imu_incremental
```

The map-optimization service `lio_sam/save_map` is called after replay. When successful, the upstream `GlobalMap.pcd`, key-pose trajectory, and transformations are copied into the raw run directory and may be collected as Native Map/system-mapping artifacts.

## GNSS

GNSS remains disabled for the common LiDAR+IMU baseline. A GNSS-enabled LIO-SAM experiment is a different sensor profile and belongs outside the Common LIO scoreboard.

## Acceptance

`adapter_status` remains `NOT_TESTED` until the selected integration has passed local short-smoke and full-bag validation on a dataset that satisfies the orientation requirement.
