# Leg-KILO 2.0 fixed-baseline adapter

Leg-KILO 2.0 is a fixed V2 baseline, but the upstream project is currently documented and tested as a ROS1/catkin package. The benchmark repository therefore separates **algorithm identity** from **machine-specific execution adaptation**.

For ordinary MID360 + IMU greenhouse bags, the frozen benchmark label is:

```text
Leg-KILO 2.0
mode = lidar_imu
leg_kinematics = disabled
```

This is intentionally different from a future run that supplies valid leg encoder/contact observations.

## Local adapter contract

Set:

```bash
export LEG_KILO_ADAPTER_BIN=/absolute/path/to/your/validated/leg_kilo_mid360_adapter.sh
```

The executable receives:

```text
$1 = ROS 2 bag directory
$2 = benchmark raw output directory
```

It may use the ROS1/ROS2 bridge, an audited bag conversion step, or a local ROS2 port, but that choice must remain visible in the run provenance. The adapter should save its exact launch/config/trajectory/map outputs under `$2`.

The repository-provided `evaluators/run_leg_kilo_test.sh` is only a safe shim. It does not patch upstream Leg-KILO, convert bags silently, invent output topic names, or enable leg kinematics when the dataset does not contain them.

## Why this boundary exists

A benchmark result is useful only when another person can tell which implementation actually ran. Treating a local ROS2 port and the upstream ROS1 implementation as if they were identical would make the comparison difficult to audit. Keep the local adapter path, upstream commit, local patch/port commit, and effective topics in the run metadata.
