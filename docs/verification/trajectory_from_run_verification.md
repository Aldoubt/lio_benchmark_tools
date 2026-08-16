# Trajectory From Run Verification

Date: 2026-08-16

## Scope

This note verifies the repository-side contract for run-local ROS 2 trajectory standardization. It does **not** claim that the new path has already passed a fresh greenhouse target-machine replay.

## Repository contract status

Status: **VERIFIED IN CI**

The implementation provides:

- `benchmark_base/lib/trajectory_from_run.py` for ROS-independent pose-to-standard-trajectory conversion.
- `benchmark_base/lib/rosbag_trajectory.py` as the shared ROS 2 bag/topic/pose reader.
- `evaluators/audit_trajectory_frames.py` consuming the shared reader while remaining read-only.
- `evaluators/standardize_trajectory_from_run.py` for run-local raw trajectory bag conversion.
- `lio-benchmark standardize trajectory-from-run --run <run> --algorithm <id>`.
- fail-closed refusal to overwrite an existing standardized trajectory.
- `metadata/algorithms/<algorithm>/trajectory_standardization.json` as the standardization evidence artifact.
- inclusion of trajectory-standardization metadata in the minimal diagnostic bundle.

Scientific boundary:

```text
raw estimator pose values
        ↓
representation normalization only
        ↓
standardized trajectory CSV
```

The stage does not perform tracked-frame conversion, gravity/world-gauge normalization, display alignment, LiDAR-IMU extrinsic transformation, interpolation, resampling, warm-up trimming, or accuracy scoring.

## CI evidence

The implementation was developed with RED/GREEN contract tests covering:

- quaternion normalization and derived RPY;
- unchanged XYZ and timestamp values;
- source-topic preservation;
- strict-monotonic timestamp enforcement through the existing `Trajectory` contract;
- frozen trajectory-topic resolution;
- fixed output and metadata paths;
- refusal to overwrite an existing standardized trajectory;
- shared ROS bag reader use by both frame audit and run-local standardization;
- main CLI exposure without `--overwrite`;
- diagnostic bundle inclusion and missing-evidence recording.

The final code commit before this note passed the complete `Core Contracts` workflow, including:

```text
Baseline suite registry contract
Unit contracts
Compile Python sources
Shell adapter syntax
Registry smoke
```

## Target-machine integration status

Status: **PENDING**

A new run ID must be used. The historical `green_house_three_smoke_004` run must not be overwritten or reused as if it had frozen runtime identities from the new execution contract.

Target dataset:

```text
green_house_mid360
```

Target algorithms:

```text
fast_livo2
fast_lio2
kiss_icp
```

Target replay contract:

```text
rate = 1.0
start_offset_s = 0.0
duration_s = 15.0
```

FAST-LIO2 uses the explicit executable override frozen by `benchmark_base/config/green_house_three_runtime_smoke.json`.

## Required target-machine acceptance

For each of the three algorithms, the fresh run must prove:

1. estimator execution produces a raw ROS 2 trajectory bag;
2. `runtime_identity.json` is frozen before estimator execution;
3. `standardize trajectory-from-run` creates a non-empty standardized CSV;
4. timestamps are strictly increasing;
5. raw and standardized first poses match apart from quaternion normalization tolerance;
6. trajectory-frame audit can consume the same raw evidence through the shared reader;
7. Common Scan Manifest inherits the frozen 15 s replay window;
8. Unified Map consumes the generated standardized trajectory;
9. runtime provenance consumes frozen runtime identity first;
10. `lio-benchmark bundle --run <run>` contains all small evidence artifacts.

Only after these target-machine checks pass should this note be extended with a real run ID and measured counts.
