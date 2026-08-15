# FAST-LIO2 Adapter

## Algorithm identity

- Algorithm family: `hku-mars/FAST_LIO`
- Benchmark ID: `fast_lio2`
- Role: `ODOMETRY`
- Required sensors: LiDAR + IMU
- Canonical extrinsic convention: `LIDAR_TO_IMU`

The HKU-MARS official repository is the algorithm identity but remains a ROS1/catkin project. The Humble adapter therefore freezes a separate execution implementation instead of pretending an arbitrary ROS2 fork is the official repository.

## ROS2 execution implementation

- Repository: `Franklif1/Fast_LIO2_ROS2`
- Branch: `ros2`
- ROS package: `fast_lio`
- Executable: `fastlio_mapping`

Every real run must preserve the local implementation commit/dirty state in the benchmark environment/provenance snapshot.

## Generated configuration

The adapter does not edit the upstream `mid360.yaml`.

`preflight/prepare` writes the canonical benchmark calibration to:

```text
configs/generated/fast_lio2/calibration.json
```

`evaluators/prepare_fast_lio2_config.py` then generates:

```text
configs/generated/fast_lio2/benchmark.yaml
```

from the frozen dataset topics, message type, and calibration.

For the selected ROS2 implementation, source variables are named `Lidar_T_wrt_IMU` / `Lidar_R_wrt_IMU`, so the adapter uses the benchmark canonical `LIDAR_TO_IMU` transform.

## Outputs retained

The adapter records when available:

```text
/Odometry
/path
/cloud_registered
/cloud_registered_body
```

These raw ROS outputs remain in `raw/fast_lio2/fast_lio2_outputs`.

The common scientific trajectory and Unified Map are produced later by the benchmark standardizers.

## Native map mode

Native map collection is opt-in:

```bash
BENCHMARK_COLLECT_NATIVE_MAP=1 lio-benchmark run ...
```

The selected ROS2 port builds `/Laser_map` through an additional accumulated map publication path and the `map_save` service writes that accumulation. Enabling it can change runtime cost. Therefore the normal odometry benchmark does not silently enable native-map accumulation.

When native-map mode is enabled, the run must record that fact and the resulting `native_map.pcd` may be passed to the benchmark Native Map collector. It is never substituted for the Unified Map.

## Acceptance status

The adapter remains `NOT_TESTED` until a local Humble short smoke and full-bag run pass. Headless CI validates registry/schema/Python/shell syntax only.
