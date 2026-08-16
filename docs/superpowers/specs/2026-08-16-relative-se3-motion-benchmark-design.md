# Relative SE(3) Motion Benchmark V1 Design

Date: 2026-08-16

## Goal

Add a scientifically conservative pairwise motion-disagreement benchmark for standardized odometry trajectories when no ground-truth trajectory is available. The benchmark must compare relative SE(3) motion, not fitted world trajectories, and must preserve runtime provenance, frame-contract, and calibration limitations in every result.

## Scope

V1 compares selected algorithms from one frozen run. The intended first target is `fast_livo2`, `fast_lio2`, and `kiss_icp` on the same greenhouse bag.

V1 does not compute or claim ATE, RPE, accuracy, estimator ranking, SE(3) best-fit alignment, Umeyama alignment, ICP alignment, warmup trimming, START_XY_YAW display alignment, automatic calibration refinement, or ground-truth error.

## Input gates

An algorithm is eligible only when all of the following run-local evidence exists and is consistent:

- standardized trajectory is available and valid;
- runtime identity is `FROZEN`;
- runtime provenance is `MATCH`;
- trajectory frame audit is `MATCH`;
- `trajectory_contract.tracked_frame_physical` is supported.

Unsupported or missing evidence must fail closed for that algorithm. A blocked algorithm must not erase valid pairwise evidence between remaining eligible algorithms.

## Target physical frame

The benchmark target frame is `IMU_BODY`.

- `IMU_BODY` trajectories need no additional physical-frame conversion.
- `LIDAR` trajectories are converted using the frozen dataset canonical LiDAR-to-IMU calibration.
- other tracked physical frames are unsupported in V1.

The dataset canonical transform is `T_IL`, defined by `p_I = R_IL p_L + t_IL`. Therefore a LiDAR-tracked world pose is normalized using:

```text
T_WI = T_WL * inverse(T_IL)
```

The transform direction must be unit-tested with a non-zero lever arm and non-identity rotation.

## Interpolation order

Physical-frame conversion is applied after pose interpolation at each evaluation timestamp:

```text
standardized trajectory
  -> interpolate T_WL(t)
  -> convert T_WI(t) = T_WL(t) * inverse(T_IL)
```

V1 must not pre-transform samples and then linearly interpolate transformed translations because the lever-arm translation depends on orientation.

## Common evaluation interval

For the set of eligible algorithms used in one comparison pass:

```text
t0 = max(first timestamp of each eligible trajectory)
t1 = min(last timestamp of each eligible trajectory)
```

All algorithms interpolate their start pose at the same global `t0`.

The evaluation grid is frozen to:

```text
sample_period_s = 0.1
```

`t1` is explicitly included when it is not exactly on the 0.1 s grid.

## World-gauge normalization

For each algorithm after physical-frame normalization:

```text
DeltaT_i(t) = T_i(t0)^-1 * T_i(t)
```

This removes each estimator's arbitrary world origin and orientation gauge without fitting one estimator to another. Every normalized motion trajectory must evaluate to identity at `t0` within floating-point tolerance.

## Pairwise disagreement

For algorithms A and B:

```text
DeltaT_A = [R_A, p_A]
DeltaT_B = [R_B, p_B]
```

Translation disagreement:

```text
d = p_A - p_B
xy = hypot(dx, dy)
z_abs = abs(dz)
xyz = sqrt(dx^2 + dy^2 + dz^2)
```

Signed `dx`, `dy`, and `dz` are preserved in the sample output.

Rotation disagreement uses SO(3) geodesic distance:

```text
R_err = R_A^T * R_B
theta = acos(clamp((trace(R_err) - 1) / 2, -1, 1))
```

Quaternion sign must not affect the result.

## Summary statistics

For `xy`, `z_abs`, `xyz`, and SO(3) rotation disagreement, each pair records:

- RMSE;
- median;
- P95;
- maximum;
- peak absolute timestamp;
- peak relative time.

The terminology is always `disagreement`, never `error`, `accuracy`, `ATE`, or `RPE`.

## Sustained onset thresholds

Translation thresholds, in meters:

```text
[0.05, 0.10, 0.20, 0.50]
```

Rotation thresholds, in degrees:

```text
[1, 2, 5, 10]
```

Translation thresholds are evaluated independently for `xy`, `z_abs`, and `xyz`. Rotation thresholds apply to SO(3) geodesic angle.

The frozen sustained-crossing definition is:

```text
sustain_samples = 3
```

An onset exists only when the metric is greater than or equal to the threshold for three consecutive evaluation samples. The onset timestamp is the first sample of that sustained run. A transient single-sample spike must not trigger onset. If no sustained crossing exists, `crossed=false` and onset timestamps are null.

## Calibration and scientific status

The current greenhouse LiDAR-to-IMU calibration is unconfirmed.

`fast_livo2 <-> fast_lio2` does not require an additional trajectory-frame extrinsic conversion because both track `IMU_BODY`, but their estimator runs still depend on the unconfirmed LiDAR-IMU calibration. Their scientific status therefore remains `DIAGNOSTIC_ONLY`.

Pairs involving KISS-ICP additionally depend on the canonical LiDAR-to-IMU transform to convert `LIDAR` tracking to `IMU_BODY`. These pair records must explicitly state that physical-frame normalization used calibration and that the calibration status is `UNCONFIRMED`.

If the calibration object exists and is structurally valid but unconfirmed, numerical KISS results are allowed and marked `DIAGNOSTIC_ONLY`. If required calibration is missing or malformed, KISS-related pairs are blocked while valid IMU_BODY-only pairs remain available.

## Output contract

Fixed output directory:

```text
metrics/relative_se3/
```

Artifacts:

```text
metadata.json
normalized_motion.csv
pairwise_samples.csv
pairwise_summary.csv
onset_thresholds.csv
```

`normalized_motion.csv` is a long table with algorithm id, timestamps, relative motion pose, source tracked frame, and target tracked frame.

`pairwise_samples.csv` contains signed translation components, XY/Z/XYZ disagreement, and SO(3) disagreement for every pair and evaluation timestamp.

`pairwise_summary.csv` contains the fixed summary metrics and scientific status per pair.

`onset_thresholds.csv` is long-form and contains pair, metric, threshold, unit, sustain sample count, crossing status, onset absolute/relative time, and onset value.

## Metadata contract

`metadata.json` freezes at least:

- schema version;
- selected/eligible/blocked algorithms and reasons;
- `target_physical_frame = IMU_BODY`;
- global `common_start_s` and `common_end_s`;
- `sample_period_s = 0.1`;
- `sustain_samples = 3`;
- fixed translation and rotation thresholds;
- world-gauge normalization formula `T(t0)^-1 * T(t)`;
- rotation metric `SO3_GEODESIC`;
- `ground_truth = NONE`;
- terminology `PAIRWISE_DISAGREEMENT`;
- input standardized trajectory path, SHA-256, and size;
- runtime identity status;
- runtime provenance status;
- frame audit status;
- source tracked physical frame;
- whether physical-frame calibration conversion was used;
- calibration status;
- scientific status and diagnostic reasons.

The analysis must never mutate standardized trajectory files.

## CLI

Add:

```bash
lio-benchmark compare relative-se3 --run <run>
```

Optional:

```bash
--algorithms fast_livo2 fast_lio2 kiss_icp
```

If omitted, the command uses algorithms selected in the frozen manifest.

V1 intentionally exposes no CLI options for alignment mode, sample period, thresholds, sustained-sample count, extrinsic override, reference algorithm, or warmup.

## Code boundary

Create a new ROS-independent core module `benchmark_base/lib/relative_se3.py` and a small evaluator/CLI adapter. Reuse the existing `Trajectory.interpolate_pose`, quaternion SLERP, calibration transform helpers, and trajectory semantics. Do not change the existing display-oriented `reporting.diagnostics.pairwise_disagreement` scientific meaning.

## Acceptance

Repository acceptance requires unit tests for rigid transform direction, shared `t0`, SO(3) sign/wrap behavior, sustained onset, calibration fail-closed behavior, provenance/frame gating, deterministic output files, and standardized trajectory immutability.

Target-machine acceptance is performed on one new run generated from one bag. The final run must produce the five Relative SE(3) artifacts and preserve `DIAGNOSTIC_ONLY` scientific labels while calibration remains unconfirmed.
