# SLICT Research Adapter

## 1. Benchmark role

`slict` is a `RESEARCH` baseline representing continuous-time LiDAR-inertial optimization with surfel mapping.

It is intentionally not required for every machine. Unsupported environments remain explicit blockers and do not invalidate the Core benchmark suite.

## 2. Selected upstream implementation

Repository:

```text
brytsknguyen/slict
branch: master
```

The selected current master is a ROS 2 implementation that explicitly targets:

```text
Ubuntu 24.04
ROS 2 Jazzy
```

Its build configuration directly references the Jazzy include tree and installs the main executables:

```text
slict_estimator
slict_sensorsync
slict_imu_odom
slict_livox_to_ouster
```

The benchmark does not claim that this current master is supported on the primary ROS 2 Humble machine.

## 3. Dataset configuration boundary

SLICT has substantial dataset-specific configuration, including:

```text
LiDAR topic(s)
IMU topic
LiDAR-to-body extrinsic
timestamp/scan convention
IMU noise values
spline/window parameters
map settings
loop settings
```

Therefore the formal adapter requires an explicitly reviewed config:

```bash
export BENCHMARK_SLICT_CONFIG=/path/to/reviewed_dataset_config.yaml
```

The adapter copies that file into the frozen run config directory. It does not silently reuse an unrelated public-dataset config.

For Livox data, current master provides `slict_livox_to_ouster`. It is enabled only when explicitly requested:

```bash
export BENCHMARK_SLICT_USE_LIVOX_CONVERTER=1
```

This switch must only be used when the selected dataset message format is known to match the upstream converter contract.

## 4. Calibration convention

Current upstream YAML describes `lidar_extr` as:

```text
transform of coordinates in LiDAR frame to body
```

For the common LiDAR/IMU benchmark, the body state is treated as the IMU/body frame, therefore the registry records:

```text
extrinsic_convention = LIDAR_TO_IMU
```

A dataset-specific SLICT config must be generated/reviewed from the canonical Dataset Registry calibration before a formal comparison. Copying another dataset's 4x4 transform is not acceptable.

## 5. Formal adapter

Entry point:

```bash
evaluators/run_slict_test.sh <rosbag2_dir> <output_dir>
```

Required environment:

```text
ROS_DISTRO=jazzy
WORKSPACE with a built slict package
BENCHMARK_SLICT_CONFIG
```

Optional:

```text
BENCHMARK_SLICT_SOURCE
BENCHMARK_SLICT_USE_LIVOX_CONVERTER=1
```

The adapter launches the upstream components directly:

```text
slict_sensorsync
slict_estimator
slict_imu_odom
optional slict_livox_to_ouster
```

and replays the frozen rosbag2 at `BAG_PLAY_RATE`.

## 6. Retained outputs

Until a specific SLICT output-role mapping is validated on a real benchmark dataset, the adapter does not invent canonical trajectory topic names.

It retains:

```text
slict_outputs rosbag
slict_log directory
sensor-sync log
estimator log
IMU-odometry log
optional Livox-converter log
bag replay log
```

After real-machine validation, declared ODOMETRY/native-map topics or log files can be added to the registry and standardized without changing the adapter's environment semantics.

## 7. Current verification status

```text
Contract/registry adapter: implemented
Shell syntax / CI: required
Real-machine SLICT run: NOT_TESTED on this branch
Primary Ubuntu 22.04 / ROS2 Humble machine: BLOCKED_ENVIRONMENT by design
```

SLICT only becomes a successful benchmark result when it is run in the registered supported environment with a reviewed dataset-specific config and its trajectory/map output roles are validated.
