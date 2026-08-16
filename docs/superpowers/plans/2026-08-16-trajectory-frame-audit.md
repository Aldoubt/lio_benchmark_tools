# Trajectory Frame Audit Implementation Plan

## Goal

Add a read-only trajectory-frame audit that determines whether estimator divergence is already present in raw ROS odometry semantics or is introduced by trajectory standardization.

This task must not modify standardized trajectories, maps, alignment modes, algorithm parameters, or upstream source trees.

## Artifacts

Per algorithm:

```text
metadata/frame_audit/<algorithm>.json
```

Combined:

```text
metrics/trajectory_frame_audit.csv
```

## Audit contract

For each selected algorithm record:

- declared trajectory topic
- raw output rosbag directory actually containing that topic
- ROS message type
- message count
- unique `header.frame_id`
- unique `child_frame_id` when available
- frame-id change counts
- first/last raw timestamps
- first raw position / quaternion / roll-pitch-yaw
- standardized first position / quaternion / roll-pitch-yaw when available
- raw-to-standardized first timestamp delta
- raw-to-standardized first position delta
- raw-to-standardized first orientation delta
- pose semantics basis (`nav_msgs/msg/Odometry` means pose is parent-to-child)
- declared `pose_represents` and `world_frame_semantics` when the registry provides them; otherwise `UNKNOWN`

No heuristic is allowed to silently relabel a frame as LiDAR/IMU/base from its name.

## Implementation order

1. Add pure-Python frame-audit data model and comparison math with tests
2. Verify RED in CI
3. Implement the pure core until tests are GREEN
4. Add ROS2 bag reader/evaluator that discovers the raw output bag containing the declared trajectory topic
5. Add `lio-benchmark audit trajectory-frames --run ... [--algorithms ...]`
6. Add CLI contract tests
7. Document the three-algorithm rerun procedure
8. Run full CI and report only what CI proves; real rosbag audit remains a machine-side smoke

## Scientific boundary

This audit diagnoses coordinate-frame semantics. It does not add `START_SE3`, does not transform scientific artifacts, and does not claim which estimator is correct.
