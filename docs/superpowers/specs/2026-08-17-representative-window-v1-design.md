# Representative Window V1 Design

## Goal

Create a deterministic, estimator-independent selector for representative windows from one long ROS 2 bag, then emit four fresh experiment configs for FAST-LIVO2, FAST-LIO2, and KISS-ICP.

The selector exists to answer *when the algorithms diverge*, not to rank ground-truth accuracy.

## Scientific boundary

Window selection MUST use only raw sensor evidence from the frozen dataset bag:

- Mid-360 LiDAR messages
- Mid-360 internal IMU messages
- ROS bag record timestamps

It MUST NOT use:

- FAST-LIVO2 trajectory or map
- FAST-LIO2 trajectory or map
- KISS-ICP trajectory or map
- Relative SE(3) results
- map quality results
- ground truth

This prevents estimator-dependent cherry-picking.

The selected windows are descriptive candidates. In particular `geometric_degeneracy_candidate` is a raw-geometry proxy, not proof that any estimator is mathematically degenerate.

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

V1 exposes no CLI tuning flags for these constants. A future change requires a schema/version change rather than silently changing an existing experiment.

## Time domain

All selected `start_offset_s` values are expressed in ROS bag record-time offset from the first bag record. This is the same domain consumed by `ros2 bag play --start-offset`.

Header timestamps and point timestamps may still be audited elsewhere, but they are not used to define representative replay boundaries.

## Raw LiDAR features

For each usable LiDAR scan:

1. extract finite XYZ points with the shared cloud contract
2. downsample with `lidar_point_step = 20`
3. discard points nearer than 0.5 m
4. build a 32-bin radial range histogram over `[0.5, 30.0]` m and normalize it
5. compute the centered XYZ covariance eigenvalues `lambda1 >= lambda2 >= lambda3 >= 0`
6. normalize eigenvalues into `p_i = lambda_i / sum(lambda)`
7. compute normalized structural entropy

```text
H = -sum(p_i log p_i) / log(3)
geometric_degeneracy_score = 1 - H
```

The score approaches zero for isotropic 3-D structure and increases for strongly anisotropic structure. It is used only to nominate a candidate window.

Adjacent normalized radial histograms produce a raw scene-change proxy:

```text
scene_change = 0.5 * L1(hist_t - hist_t-1)
```

## Raw IMU features

For each IMU message use the vector norms:

```text
angular_speed_rad_s = ||omega||
acceleration_norm_native = ||a||
```

`acceleration_norm_native` intentionally preserves the frozen dataset's declared acceleration unit rather than assuming SI. The current greenhouse registry describes the stream as `g_like_raw; existing DLIO adapter scales by 9.80665`. Representative Window V1 only uses rank/order information from acceleration dynamics, so a constant unit scale does not alter the selector ordering.

Each 45 s candidate window records:

```text
gyro_rms_rad_s
gyro_p95_rad_s
accel_dynamic_rms_native
scene_change_mean
geometric_degeneracy_median
geometric_degeneracy_p90
lidar_scan_count
imu_sample_count
```

`accel_dynamic_rms_native` is the RMS deviation of acceleration magnitude from the window median in the dataset-native unit, so gravity magnitude itself does not dominate the score. The actual declared unit string is frozen in `selection_metadata.json`.

## Candidate grid and validity

Candidate windows start on a deterministic 5 s grid and must fit fully inside the common raw LiDAR/IMU record-time interval.

A candidate is valid only when it contains at least 100 usable LiDAR scans and 500 IMU samples.

The fixed initialization window is:

```text
label = initialization
start_offset_s = 0.0
duration_s = 45.0
```

Other candidates may start only after:

```text
45.0 + 15.0 = 60.0 s
```

## Selection policy

All selected windows must be pairwise non-overlapping.

Selection order is fixed:

1. `initialization`
2. `high_angular_motion`
3. `geometric_degeneracy_candidate`
4. `steady_translation_candidate`

### High angular motion

Choose the remaining valid window with maximum `gyro_p95_rad_s`. Tie-break by earlier start time.

### Geometric degeneracy candidate

Among remaining non-overlapping windows, prefer windows whose `scene_change_mean` is at or above the lower quartile of the remaining valid candidate population, then choose maximum `geometric_degeneracy_median`. Tie-break by higher `scene_change_mean`, then earlier start time.

This avoids preferentially selecting a completely static but anisotropic scene when moving alternatives exist.

### Steady translation candidate

Among remaining non-overlapping windows, compute deterministic percentile ranks over the remaining candidate population:

```text
steady_score =
    0.60 * rank(scene_change_mean, high_is_good)
  + 0.30 * rank(gyro_rms_rad_s, low_is_good)
  + 0.10 * rank(accel_dynamic_rms_native, low_is_good)
```

Choose maximum score, tie-break by earlier start time.

This is intentionally named a *candidate*: raw sensors can support a low-angular, scene-changing segment without claiming externally verified straight-line motion.

## Outputs

A successful selector writes only small run-local evidence:

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

`selection_metadata.json` freezes:

- schema version
- all V1 constants
- bag/dataset identity
- algorithm IDs preserved for child experiments
- selection inputs = raw LiDAR + raw IMU
- `estimator_outputs_used = false`
- `ground_truth_used = false`
- selected window labels and offsets
- fingerprints of generated child configs

## Child experiment configs

The selector run must originate from schema-v2 and preserve:

- workspace
- output root
- dataset registry ID
- algorithm registry IDs
- execution overrides
- runtime overlays
- standardization rules

Each generated child config differs only in:

- experiment name
- `replay.start_offset_s`
- `replay.duration_s = 45.0`

The generated configs are normal V2 configs and must pass the existing `validate -> init -> snapshot -> preflight -> run` chain.

## Selector run contract

Representative Window V1 requires a dedicated selector run whose frozen replay is:

```text
rate = 1.0
start_offset_s = 0.0
duration_s = null
```

The selector refuses a truncated replay run. This prevents accidentally selecting four windows from a previous 15 s smoke run.

## CLI

Add one additive command:

```bash
lio-benchmark plan representative-windows --run <selector-run>
```

It has no scientific tuning flags in V1.

Because reading Livox CustomMsg requires ROS/workspace message packages, the command must execute through the shared formal ROS workspace runner, not an ambient Python subprocess.

## Immutability and fail-closed behavior

The output directory is immutable.

- if no output exists: generate atomically
- if all outputs exist and fingerprints match current inputs: return existing artifacts without rewrite
- if outputs are partial: fail
- if the selector manifest/bag identity changes: fail
- if fewer than four valid pairwise non-overlapping windows can be selected: fail
- never overwrite a prior selection with a different result

## Diagnostic bundle

Representative-window JSON/CSV/config/Markdown evidence is optional additive bundle content for new selector runs and is not required for historical runs.

Raw bags, DB3/MCAP, PLY/PCD remain excluded.

## Acceptance boundary

Repository CI can validate pure scoring, config generation, CLI wiring, immutability, and bundle behavior.

Target-machine acceptance is still required to prove that the full greenhouse bag can be deserialized and produces four valid windows. The implementation phase stops at that first real-bag acceptance point.
