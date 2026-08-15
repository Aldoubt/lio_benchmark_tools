# Faster-LIO Research Adapter

## 1. Benchmark role

`faster_lio` is a `RESEARCH` baseline used to study the FAST-LIO2-family efficiency/map-structure direction, especially sparse incremental voxel mapping.

It is not a mandatory Core baseline. A missing or unsupported Faster-LIO environment must appear as `BLOCKED_ENVIRONMENT` / `BLOCKED_DEPENDENCY`, not as a benchmark failure of the dataset.

## 2. Selected upstream implementation

Repository:

```text
gaoxiang12/faster-lio
branch: main
```

The selected upstream implementation is ROS 1 and documents Ubuntu 18.04/20.04 with ROS Melodic/Noetic. The benchmark does not claim an upstream ROS 2 Humble implementation.

Registry environment contract:

```text
ROS_DISTRO = melodic | noetic
runtime = ROS1/catkin
```

A Humble/Jazzy machine is expected to be blocked unless another separately validated implementation is registered under a distinct identity.

## 3. Dataset transport boundary

Official Faster-LIO consumes ROS 1 messages/bags. The formal adapter accepts either:

```text
<BAG_INPUT> = an explicit ROS1 .bag file
```

or, when the frozen benchmark dataset is rosbag2:

```bash
export BENCHMARK_ROS1_BAG_FILE=/path/to/explicitly/converted.bag
```

The benchmark never silently converts rosbag2 to ROS1 because conversion is part of dataset provenance.

The converted artifact must be traceable to the frozen dataset and should record its conversion command/hash in experiment metadata before publication use.

## 4. Calibration convention

Upstream source names the configured extrinsics:

```text
Lidar_T_wrt_IMU
Lidar_R_wrt_IMU
offset_T_L_I
offset_R_L_I
```

The benchmark therefore declares:

```text
extrinsic_convention = LIDAR_TO_IMU
```

The adapter consumes the run-local `calibration.json` generated from the Dataset Registry canonical calibration and writes a run-local `benchmark.yaml`.

It does not edit `gaoxiang12/faster-lio` configuration files in place.

## 5. Formal adapter

Entry point:

```bash
evaluators/run_faster_lio_test.sh <ros1_bag_or_dataset_input> <output_dir>
```

Important environment variables:

```text
WORKSPACE
BAG_PLAY_RATE=1.0
BENCHMARK_RUN_DIR
BENCHMARK_GENERATED_CONFIG_DIR
BENCHMARK_ROS1_BAG_FILE          optional explicit conversion artifact
BENCHMARK_FASTER_LIO_SOURCE      optional source override
BENCHMARK_FASTER_LIO_BASE_CONFIG optional base YAML override
```

The generated config preserves the upstream tuning baseline while explicitly setting:

```text
LiDAR topic
IMU topic
LiDAR input type
LiDAR-to-IMU extrinsic
PCD save enable
```

## 6. Retained outputs

When available, retain:

```text
/Odometry
/path
/cloud_registered
/cloud_registered_body
raw ROS1 output bag
odometry_raw.csv
native PCD output
algorithm logs
rosbag replay log
```

Native PCD is `NATIVE` only when it is emitted by Faster-LIO itself. A benchmark accumulated Unified Map remains `UNIFIED_RECONSTRUCTION`.

## 7. Current verification status

```text
Contract/registry adapter: implemented
Shell syntax / CI: required
Real-machine Faster-LIO run: NOT_TESTED on this branch
Primary Ubuntu 22.04 / ROS2 Humble machine: BLOCKED_ENVIRONMENT by design
```

Do not change this status to PASS until an actual supported ROS1 environment consumes a frozen dataset and produces a validated trajectory/output set.
