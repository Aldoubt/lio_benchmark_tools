# Trajectory From Run Standardization Design

## 1. Problem

The benchmark runners for FAST-LIVO2, FAST-LIO2, and KISS-ICP record trajectory outputs as run-local ROS 2 bags under:

```text
raw/<algorithm>/...
```

The current trajectory standardization entry point primarily accepts an external CSV and writes:

```text
standardized/trajectories/<algorithm>.csv
```

This leaves a gap in a freshly created benchmark run: the benchmark itself records the raw trajectory evidence, but a user still needs an external/manual conversion step before Unified Map reconstruction can consume a standardized trajectory.

The frame-audit path already contains source-backed ROS 2 bag discovery and pose-message reading logic, but that code is currently embedded in a read-only audit evaluator. Reusing that logic indirectly through the audit command would violate the audit boundary, while duplicating it in each algorithm runner would fragment the standardization contract.

## 2. Decision

Add a run-native trajectory standardization command:

```bash
lio-benchmark standardize trajectory-from-run \
  --run <run> \
  --algorithm <algorithm_id>
```

The command converts the selected algorithm's recorded raw ROS 2 trajectory bag into the existing standardized trajectory CSV contract.

This feature performs format normalization only. It MUST NOT transform the physical tracked frame, change world gauge, apply display alignment, apply calibration transforms, or otherwise modify estimator poses.

## 3. Scope

### 3.1. In scope

The new path will:

1. Resolve the selected algorithm from the frozen run manifest.
2. Resolve the trajectory output topic from the frozen algorithm contract.
3. Search only under `raw/<algorithm>/` for a ROS 2 bag containing that topic.
4. Fail if zero or multiple matching bags are found.
5. Support the pose message types already accepted by frame audit:
   - `nav_msgs/msg/Odometry`
   - `geometry_msgs/msg/PoseStamped`
   - `geometry_msgs/msg/PoseWithCovarianceStamped`
6. Use message header timestamps when non-zero, otherwise fall back to rosbag record time.
7. Preserve translation and quaternion values exactly apart from quaternion normalization required by the existing standardized trajectory contract.
8. Derive roll/pitch/yaw from the same normalized quaternion using the existing trajectory utilities.
9. Preserve the actual source topic in the standardized CSV.
10. Write:

```text
standardized/trajectories/<algorithm>.csv
```

11. Emit a small machine-readable metadata artifact describing source bag, source topic, source message type, timestamp policy, sample count, and output path.

### 3.2. Out of scope

The feature will not:

- transform IMU-body poses into LiDAR poses;
- transform LiDAR poses into base-link poses;
- align gravity or initial heading;
- apply `START_XY_YAW` or any display alignment;
- interpolate or resample estimator poses;
- trim warm-up periods;
- apply LiDAR-IMU extrinsics;
- alter raw ROS bags;
- modify algorithm source trees;
- perform trajectory accuracy scoring;
- infer missing frame semantics.

Those remain separate benchmark stages.

## 4. Architecture

### 4.1. Shared ROS bag pose reader

Extract the generic ROS 2 trajectory-bag discovery and pose-reading behavior currently embedded in `evaluators/audit_trajectory_frames.py` into a focused shared module, for example:

```text
benchmark_base/lib/rosbag_trajectory.py
```

Responsibilities:

```text
normalize_topic
storage_identifier
open_reader
topic_map
find_bag_for_topic
stamp_seconds
pose_fields
read_pose_observations
```

The module is ROS-dependent and therefore remains outside the pure-Python core tests that run without ROS. Pure pose-to-standardized-sample conversion logic should remain testable independently where possible.

`audit_trajectory_frames.py` becomes a consumer of this shared reader rather than the owner of duplicate bag parsing logic.

### 4.2. New evaluator

Add a dedicated evaluator, for example:

```text
evaluators/standardize_trajectory_from_run.py
```

Inputs:

```text
--run <run>
--algorithm <algorithm_id>
```

Processing:

```text
frozen run manifest
      ↓
selected algorithm contract
      ↓
trajectory output topic
      ↓
raw/<algorithm>/ ROS 2 bag discovery
      ↓
pose-message extraction
      ↓
existing PoseSample / Trajectory contract
      ↓
standardized/trajectories/<algorithm>.csv
```

### 4.3. CLI integration

Extend:

```text
lio-benchmark standardize
```

with:

```text
trajectory-from-run
```

The existing CSV-based command remains unchanged:

```text
trajectory
```

The two paths deliberately coexist:

```text
trajectory          = external/upstream CSV → standard contract
trajectory-from-run = run-local raw ROS 2 bag → standard contract
```

## 5. Data Contract

The generated CSV uses the existing standardized trajectory columns:

```text
timestamp_s
x_m
y_m
z_m
qx
qy
qz
qw
roll_rad
pitch_rad
yaw_rad
source_topic
```

No new scientific trajectory representation is introduced.

Recommended metadata path:

```text
metadata/algorithms/<algorithm>/trajectory_standardization.json
```

Minimum metadata:

```json
{
  "schema_version": 1,
  "algorithm_id": "fast_lio2",
  "source_kind": "RUN_LOCAL_ROS2_BAG",
  "source_bag": "...",
  "source_topic": "/Odometry",
  "source_message_type": "nav_msgs/msg/Odometry",
  "timestamp_policy": "HEADER_STAMP_ELSE_BAG_RECORD_TIME",
  "sample_count": 0,
  "start_timestamp_s": 0.0,
  "end_timestamp_s": 0.0,
  "output": "standardized/trajectories/fast_lio2.csv"
}
```

## 6. Failure Semantics

The command fails closed when:

- the algorithm is not selected in the frozen run;
- the trajectory output topic is missing from the frozen algorithm contract;
- `raw/<algorithm>/` contains no bag with that topic;
- more than one raw bag contains that topic;
- the trajectory message type is unsupported;
- no readable pose messages exist;
- pose values are non-finite or the quaternion is invalid;
- timestamps violate the existing `Trajectory` monotonicity contract;
- the output already exists unless an explicit overwrite policy is later designed.

For this phase, the command should refuse to silently overwrite an existing standardized trajectory. A rerun that needs different source evidence should use a new benchmark run ID or remove the derived artifact deliberately outside the benchmark command.

No failure is converted into a synthetic empty trajectory or PASS state.

## 7. Scientific Boundary

The output is a representation change, not a coordinate-system correction.

For an estimator pose:

```text
T_parent_tracked(t)
```

the new standardization path preserves that same transform numerically and records its source topic. Frame meaning remains governed by the frozen `trajectory_contract` and is checked independently by:

```bash
lio-benchmark audit trajectory-frames
```

Therefore:

```text
trajectory-from-run != frame normalization
trajectory-from-run != gauge normalization
trajectory-from-run != display alignment
trajectory-from-run != common tracked-frame conversion
```

This separation is required so later Relative SE(3) or common-frame diagnostics cannot accidentally rewrite primary estimator evidence.

## 8. Testing Strategy

### 8.1. Pure contract tests

Add tests for reusable conversion behavior using synthetic pose observations:

- odometry-style pose becomes the expected standardized sample;
- quaternion normalization and derived RPY match existing trajectory utilities;
- header timestamp policy is explicit;
- non-monotonic timestamps fail through the existing `Trajectory` contract;
- no frame/gauge transform is applied.

### 8.2. CLI contract tests

Verify:

```bash
lio-benchmark standardize trajectory-from-run --help
```

exposes:

```text
--run
--algorithm
```

and keeps the existing `standardize trajectory` command intact.

### 8.3. ROS integration verification

On the target ROS 2 Humble machine, use a new run ID and verify all three smoke algorithms:

```text
fast_livo2
fast_lio2
kiss_icp
```

For each algorithm:

1. the runner records a raw trajectory bag;
2. `trajectory-from-run` writes the standardized CSV;
3. sample count is non-zero;
4. timestamps are monotonic;
5. first standardized pose matches the raw first pose within serialization/normalization tolerance;
6. `audit trajectory-frames` can compare raw and standardized first poses;
7. Unified Map can consume the generated standardized trajectory without manual CSV conversion.

## 9. Target Smoke Flow After This Patch

The intended fresh-run sequence becomes:

```text
validate / init / snapshot
        ↓
preflight
        ↓
run FAST-LIVO2 / FAST-LIO2 / KISS-ICP
        ↓
runtime_identity.json for each estimator
        ↓
standardize trajectory-from-run for each estimator
        ↓
audit trajectory-frames
        ↓
standardize scan-manifest
        ↓
standardize map
        ↓
audit runtime-provenance
        ↓
report / bundle
```

The three-algorithm target smoke remains diagnostic because the greenhouse LiDAR-IMU calibration is not yet formally confirmed. This feature does not change calibration status or upgrade diagnostic results into formal ranking evidence.

## 10. Acceptance Criteria

Repository-side acceptance requires:

1. shared trajectory-bag reading logic is no longer duplicated inside frame audit;
2. the new `trajectory-from-run` CLI exists;
3. the output uses the existing standardized trajectory schema;
4. raw pose values are not coordinate-transformed;
5. zero/multiple bag matches and unsupported messages fail closed;
6. existing CSV trajectory standardization remains compatible;
7. existing frame audit remains read-only;
8. unit/contract tests, Python compilation, shell syntax checks, and registry smoke remain green.

Target-machine acceptance requires a new three-algorithm greenhouse smoke proving raw run-local trajectory bags can reach Unified Map reconstruction without any manual trajectory CSV conversion.
