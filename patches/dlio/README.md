# DLIO ROS 2 spaciousness bounds patch

- Upstream: `vectr-ucla/direct_lidar_inertial_odometry`, `feature/ros2`
- Target commit: `c8acc37100e349d70a9d8432d656cbce7e5072cd`
- File: `src/dlio/odom.cc`
- Reason: `computeSpaciousness()` iterates through `i <= points.size()` and dereferences one element past the end. The first MID360 scan reproducibly segfaults after IMU calibration.
- Change: use `size_t` and strict `< points.size()` bound.
- Behavior: metric calculation reads exactly the valid cloud; odometry mathematics are otherwise unchanged.
- Risk: minimal; this removes undefined behavior only.
- Validation: rebuild Release, run the 60-second DLIO smoke, require non-empty odometry and no segfault.
- Rollback: `git apply -R patches/dlio/spaciousness_bounds.patch` in the target worktree.

The benchmark config keeps `odom/preprocessing/cropBoxFilter/size=1.0`. DLIO applies this filter as a negative crop box around the robot; setting it to the desired 70 m maximum range removes the entire useful cloud and leaves deskew with an empty input.
