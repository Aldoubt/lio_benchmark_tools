# Representative Window V1 Verification

Date: 2026-08-17

Branch:

```text
feat/lio-baseline-suite
```

## Scope

Representative Window V1 creates four deterministic, pairwise non-overlapping 45 s replay windows from one long ROS 2 bag before estimator comparison:

```text
initialization
high_angular_motion
geometric_degeneracy_candidate
steady_translation_candidate
```

Selection is estimator-independent. The only allowed evidence is:

```text
raw Mid-360 LiDAR
raw Mid-360 internal IMU
ROS bag record timestamps
```

Forbidden selection inputs include FAST-LIVO2 / FAST-LIO2 / KISS trajectories, maps, disagreement outputs, and ground truth.

The candidate labels are descriptive raw-sensor proxies. They do not establish ground-truth straight-line motion or mathematical estimator degeneracy.

## Frozen V1 constants

```text
window_duration_s = 45.0
window_stride_s = 5.0
post_initialization_guard_s = 15.0
lidar_point_step = 20
lidar_near_range_m = 0.5
range_histogram_max_m = 30.0
range_histogram_bins = 32
minimum_lidar_scans_per_window = 100
minimum_imu_samples_per_window = 500
```

V1 exposes no CLI tuning flags for these values.

Window replay boundaries use bag-record time offset from the first bag record, matching the `ros2 bag play --start-offset` domain.

The greenhouse dataset declares its raw acceleration stream as `g_like_raw; existing DLIO adapter scales by 9.80665`. Therefore the selector preserves acceleration dynamics in dataset-native units as:

```text
accel_dynamic_rms_native
```

It does not label raw acceleration as SI. Only deterministic rank/order information is used in the steady-motion candidate score.

## Factory extrinsic boundary

Representative-window selection does not use the LiDAR-IMU extrinsic. The already-frozen unified baseline remains unchanged:

```text
calibration_status = MANUFACTURER_SPEC
T_IL translation = [-0.011, -0.02329, +0.04412] m
T_LI translation = [+0.011, +0.02329, -0.04412] m
```

Every generated child experiment preserves the same dataset/algorithm/runtime/standardization contracts; only the experiment name and replay start/duration change.

## Task 1 — pure scoring core

Initial RED commit:

```text
0ca69ba83fd2b221fb95e96636fe6b6f4898212d
```

The new contract failed because `benchmark_base.lib.representative_windows` did not exist.

The pure module now implements:

```text
raw LiDAR radial histogram
raw LiDAR covariance entropy / anisotropy proxy
raw histogram scene-change proxy
raw IMU angular-speed norm
raw IMU acceleration-magnitude dynamics in dataset-native units
45 s / 5 s candidate aggregation
deterministic four-class non-overlap selection
earlier-start tie breaking
fail-closed insufficient candidate handling
```

Task 1 GREEN implementation HEAD:

```text
84dab127180ad85ede07e44133f09cf60fa454c6
```

Exact-head Core Contracts completed successfully.

## Task 2 — full-bag planner and child configs

Planner RED commit:

```text
c57716c0613d3b084c5a2b0380730457aa524825
```

The run/config planner interfaces and raw bag evaluator did not yet exist.

Implementation added:

```text
benchmark_base/config/green_house_representative_window_selector.json
evaluators/plan_representative_windows.py
```

The selector config is a normal schema-v2 config with:

```text
dataset = green_house_mid360
algorithms = fast_livo2, fast_lio2, kiss_icp
replay.rate = 1.0
replay.start_offset_s = 0.0
replay.duration_s = null
```

The selector run refuses a truncated replay manifest.

The evaluator uses the shared ROS bag / cloud contracts and writes immutable evidence:

```text
metadata/representative_windows/window_features.csv
metadata/representative_windows/selected_windows.json
metadata/representative_windows/selection_metadata.json
configs/representative_windows/initialization.json
configs/representative_windows/high_angular_motion.json
configs/representative_windows/geometric_degeneracy_candidate.json
configs/representative_windows/steady_translation_candidate.json
reports/REPRESENTATIVE_WINDOW_PLAN.md
```

Child configs preserve:

```text
workspace
output_root
dataset registry ID
algorithm registry IDs
execution overrides
runtime overlays
standardization rules
```

and freeze `duration_s=45.0` with the selected bag-record start offset.

Task 2 implementation HEAD:

```text
5827c93f56ea0ce76492c5564c395a7a7bf000ab
```

Exact-head Core Contracts run:

```text
31988630162 = completed / success
```

The selector config is additionally contract-tested through the existing V2 registry resolver/validator, not merely checked as JSON shape.

## Task 3 — public CLI and portable evidence

Task 3 RED HEAD:

```text
d81e0243d9481329f207fa240fe0719df971e607
```

Exact-head run `31988680838` failed only because:

```text
plan representative-windows CLI did not exist
selector artifacts were not yet collected by the diagnostic bundle
```

Production wiring added:

```bash
lio-benchmark plan representative-windows --run <selector-run>
```

The command exposes only `--run` in V1 and delegates through the shared formal ROS workspace runner so Livox CustomMsg resolution does not depend on the caller's ambient shell.

Diagnostic bundles now optionally include selector CSV/JSON/child-config/plan evidence. Historical runs do not report it as missing, and raw/DB3/MCAP/PLY/PCD exclusions remain unchanged.

Task 3 implementation HEAD:

```text
87d82e513f8f7c6873a3168dc22053efecf5f9bc
```

Exact-head Core Contracts run:

```text
31988749867 = completed / success
```

## Repository verification before target acceptance

Final implementation/documentation HEAD before this verification record:

```text
051df670cf818054f456c3ee6ffa02e6a6d895f6
```

Exact-head Core Contracts run:

```text
31988821837 = completed / success
```

That run includes successful:

```text
Baseline suite registry contract
Unit Contracts
Compile Python sources
Shell adapter syntax
Registry smoke
```

## Scientific interpretation

Representative Window V1 is a test-selection mechanism, not a metric and not a ground-truth annotator.

All downstream fresh window comparisons retain:

```text
SCIENTIFIC_STATUS = DESCRIPTIVE_NO_GROUND_TRUTH
Relative SE(3) terminology = PAIRWISE_DISAGREEMENT
```

Do not describe selected-window results as ATE/RPE truth, objective accuracy ranking, or verified failure-mode labels.

## Target-machine acceptance — PENDING

Repository CI does not contain the 623 s greenhouse bag or target ROS workspace. The following remain deliberately unclaimed until a fresh target-machine run:

```text
full bag raw sensor deserialization = PENDING
four representative windows selected = PENDING
four windows pairwise non-overlapping = PENDING
selector immutability rerun = PENDING
all four generated child configs validate on target = PENDING
12 fresh estimator runs (4 windows x 3 algorithms) = PENDING
coverage / provenance / frame gates per window = PENDING
strict common-map population per window = PENDING
fresh Relative SE(3) artifacts per window = PENDING
multi-window diagnostic bundles = PENDING
```

No full 623 s estimator benchmark is started automatically by this phase.

Acceptance state:

```text
REPRESENTATIVE_WINDOW_SELECTOR_ACCEPTANCE = PENDING
REPRESENTATIVE_WINDOW_FOUR_RUN_ACCEPTANCE = PENDING
```
