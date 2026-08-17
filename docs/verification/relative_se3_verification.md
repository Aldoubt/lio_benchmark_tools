# Relative SE(3) Motion Benchmark Verification

Date: 2026-08-17

## Repository implementation — PASS

Branch:

```text
feat/lio-baseline-suite
```

Relative SE(3) V1 keeps the original scientific definition:

```text
target physical frame = IMU_BODY
world gauge removal    = T(t0)^-1 * T(t)
sample period          = 0.1 s
rotation disagreement  = SO3_GEODESIC
translation thresholds = [0.05, 0.10, 0.20, 0.50] m
rotation thresholds    = [1, 2, 5, 10] deg
sustain samples        = 3
ground truth           = NONE
terminology            = PAIRWISE_DISAGREEMENT
```

LiDAR-tracked trajectories are normalized only through the frozen dataset canonical calibration:

```text
T_WI = T_WL * inverse(T_IL)
```

The implementation interpolates the source pose at each evaluation timestamp before applying the fixed physical-frame conversion.

## Mid-360 factory-extrinsic closure

The active `green_house_mid360` registry now freezes the internal Mid-360 geometry with explicit direction semantics:

```text
T_AB maps frame B coordinates into frame A
p_A = R_AB * p_B + t_AB

canonical transform:
T_IL
p_I = R_IL * p_L + t_IL
R_IL = I
t_IL = [-0.011, -0.02329, +0.04412] m

manufacturer point-location evidence:
^L p_I = [+0.011, +0.02329, -0.04412] m

T_LI = inverse(T_IL)
t_LI = [+0.011, +0.02329, -0.04412] m

calibration status = MANUFACTURER_SPEC
sensor model       = Livox Mid-360
IMU relation       = INTERNAL_IMU
```

Therefore a KISS-ICP LiDAR pose is converted to the Mid-360 internal IMU pose by right-multiplying the **positive inverse transform** `T_LI`.

Dedicated real-registry regression tests now prove:

```text
Unified Map IMU_BODY conversion uses negative canonical T_IL
Relative SE(3) LiDAR->IMU pose normalization uses positive inverse T_LI
FAST-LIO2 generated config uses negative T_IL and extrinsic_est_en=false
FAST-LIVO2 generated run-local config uses negative T_IL
```

`MANUFACTURER_SPEC` is a usable fixed-calibration status and no longer requires `--allow-diagnostic-calibration`.

## Historical run boundary

All Relative SE(3) artifacts generated before this factory-extrinsic closure remain immutable historical evidence.

The old green-house runs froze a sign-ambiguous positive vector while labeling it `LIDAR_TO_IMU`. Their KISS-to-IMU lever-arm normalization is therefore not promoted into the new baseline. The old files are retained; they are not rewritten in place.

A **fresh run** is required before numerical comparison resumes.

## Fixed outputs

A successful comparison creates exactly this run-local evidence directory:

```text
metrics/relative_se3/
├── metadata.json
├── normalized_motion.csv
├── pairwise_samples.csv
├── pairwise_summary.csv
└── onset_thresholds.csv
```

The diagnostic bundle includes these files when they exist. New bundles also include available run-local generated calibration/config evidence for FAST-LIO2 and FAST-LIVO2.

## Scientific interpretation after calibration closure

Calibration ambiguity is no longer the reason to mark the current Mid-360 comparison `DIAGNOSTIC_ONLY`.

However, ground truth is still `NONE`. Therefore Relative SE(3) remains a **descriptive pairwise-disagreement benchmark**, not an accuracy benchmark.

Allowed terminology:

```text
pairwise disagreement
descriptive relative motion comparison
divergence onset
runtime / temporal coverage comparison
```

Not allowed without independent ground truth:

```text
ATE/RPE truth error
accuracy ranking
"algorithm A is objectively more accurate"
```

## Fresh target-machine acceptance — PENDING

Repository CI cannot execute the target ROS 2 machine or greenhouse bag. The next acceptance must create a new persistent run and execute the three algorithms again from the corrected frozen registry.

Required chain:

```text
one bag
  -> validate / init / snapshot
  -> preflight WITHOUT diagnostic-calibration override
  -> FAST-LIVO2 / FAST-LIO2 / KISS-ICP
  -> verify effective generated T_IL for both LIO runtimes
  -> trajectory-from-run x3
  -> frame audit / runtime provenance / trajectory coverage
  -> selected scan manifest
  -> strict common-map manifest
  -> strict Unified Map x3
  -> Relative SE(3)
  -> diagnostic bundle with generated config evidence
```

Required Relative SE(3) evidence remains:

```text
metadata.json exists and records schema v1
eligible algorithms are the expected frozen set
common_start_s = global latest trajectory start
common_end_s   = global earliest trajectory end
sample_period_s = 0.1
sustain_samples = 3
ground_truth = NONE
terminology = PAIRWISE_DISAGREEMENT
normalized motion for every eligible algorithm is identity at common t0
pairwise_summary.csv has one row per eligible pair
onset_thresholds.csv records crossed=false/null onset when no sustained crossing exists
standardized trajectory SHA-256 values still match metadata fingerprints
```

Expected pair set:

```text
fast_lio2 <-> fast_livo2
fast_lio2 <-> kiss_icp
fast_livo2 <-> kiss_icp
```

## Acceptance record template

```text
Target run: PENDING
Repository HEAD: PENDING
Bag identity/hash: PENDING

Calibration status MANUFACTURER_SPEC: PENDING
Canonical T_IL negative vector: PENDING
FAST-LIVO2 effective T_IL: PENDING
FAST-LIO2 effective T_IL: PENDING
Runtime PASS: PENDING
Runtime identity FROZEN: PENDING
Runtime provenance MATCH: PENDING
Frame contract MATCH: PENDING
Trajectory coverage: PENDING
Strict common-map contract: PENDING
Relative SE(3) artifacts: PENDING
Normalized t0 identity check: PENDING
Pair count: PENDING
Diagnostic bundle config evidence: PENDING
Scientific label: DESCRIPTIVE_NO_GROUND_TRUTH

FRESH_FACTORY_EXTRINSIC_ACCEPTANCE = PENDING
```
