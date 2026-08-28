# LIO-SAM 6-axis IMU compatibility for the greenhouse benchmark

This benchmark dataset provides valid accelerometer and gyroscope samples but an invalid zero IMU orientation quaternion. The locked ROS 2 LIO-SAM source (`08af3f32f01725372d4269838dc44c19c6d9e76b`) unconditionally rejects that quaternion in `ParamServer::imuConverter()` and shuts down before publishing odometry.

The benchmark therefore tracks an explicit compatibility patch:

```text
patches/lio_sam/allow_6axis_imu.patch
```

The patch adds `allow6AxisImu` with default `false`. The benchmark no-loop and loop parameter files set it to `true`. When orientation is invalid and the flag is enabled, the patch estimates roll/pitch from the rotated acceleration vector, initializes yaw to zero, and logs the fallback. It does not create or claim a 9-axis heading estimate.

## Apply to the locked external workspace

The external LIO-SAM checkout is expected at:

```text
/home/yangxuan/lio_benchmark_algorithms/lio_sam_ws/src/LIO-SAM
```

Before modifying it:

```bash
cd /home/yangxuan/lio_benchmark_algorithms/lio_sam_ws/src/LIO-SAM
git status --short
git rev-parse HEAD
```

The commit must be the locked source commit. If `include/lio_sam/utility.hpp` is already modified, do not reset it automatically. First inspect whether the compatibility change is already present:

```bash
grep -n "allow6AxisImu\|6-axis IMU fallback" include/lio_sam/utility.hpp || true
git diff -- include/lio_sam/utility.hpp
```

For a clean locked checkout, check and apply the tracked patch:

```bash
git apply --check /home/yangxuan/lio_benchmark_tools/patches/lio_sam/allow_6axis_imu.patch
git apply /home/yangxuan/lio_benchmark_tools/patches/lio_sam/allow_6axis_imu.patch
```

If `git apply --check` reports that the patch does not apply, do not force it. First check whether it is already applied with:

```bash
git apply --reverse --check /home/yangxuan/lio_benchmark_tools/patches/lio_sam/allow_6axis_imu.patch
```

If the reverse check succeeds, the patch is already applied. If both forward and reverse checks fail, preserve the local diff and reconcile it explicitly rather than using `git reset --hard` or `git checkout --`.

## Rebuild only LIO-SAM

The dependency setup helper is normally invoked by the benchmark runner and requires the algorithm workspace environment variable. Set it explicitly for a manual build:

```bash
cd /home/yangxuan/lio_benchmark_algorithms/lio_sam_ws
source /opt/ros/humble/setup.bash
export LIO_BENCHMARK_ALGORITHM_WORKSPACE=/home/yangxuan/lio_benchmark_algorithms/lio_sam_ws
source /home/yangxuan/lio_benchmark_tools/configs/algorithms/lio_sam/setup_dependencies.bash
colcon build --packages-select lio_sam --cmake-args -DCMAKE_BUILD_TYPE=Release
source install/setup.bash
```

Do not rebuild or retune unrelated algorithms for this compatibility test.

## Acceptance smoke

Use a new run/output so the failed `NO_ODOMETRY` attempt remains auditable. Run only `lio_sam_no_loop` for 60 s on the greenhouse schema v2 configuration. Acceptance requires:

- process/run status `SUCCESS`;
- trajectory message count > 0;
- standardized trajectory has finite values and monotonic timestamps;
- no `path_divergence`;
- `clock_anchors.json` status `finished`, no wall/ROS time backtracks;
- phase resource alignment `strict/clock-anchored`;
- log contains the one-time `6-axis IMU fallback active` warning and no `Invalid quaternion, please use a 9-axis IMU!` shutdown.

All trajectory comparisons remain diagnostic/non-ground-truth.
