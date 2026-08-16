# Relative SE(3) Motion Benchmark Verification

Date: 2026-08-16

## Repository implementation — PASS

Branch:

```text
feat/lio-baseline-suite
```

The first complete implementation/CLI HEAD before this verification document was:

```text
44da59239ccf407491b542475e75995933ea84ee
```

Exact-head GitHub Actions `Core Contracts` run `31945078865` completed successfully. The repository contract includes unit tests for:

```text
world-gauge invariance
shared global t0/t1
endpoint-inclusive fixed 0.1 s grid
T_WL * inverse(T_IL) physical-frame conversion
non-zero lever arm and non-identity extrinsic direction
SO(3) geodesic wrap/sign behavior
three-sample sustained onset
runtime identity / provenance / frame fail-closed gates
malformed LiDAR calibration isolation
DIAGNOSTIC_ONLY unconfirmed-calibration behavior
five deterministic output artifacts
standardized trajectory immutability
compare CLI surface
optional diagnostic-bundle inclusion
legacy importable CLI contracts
```

## Frozen V1 scientific contract

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

The diagnostic bundle includes these files when they exist. Their absence is not reported as missing evidence for historical runs created before Relative SE(3) V1.

## Target-machine one-bag acceptance — PENDING

Repository CI has no ROS 2 target-machine runtime or greenhouse bag, so the final end-to-end acceptance must be executed on one fresh run generated from one bag.

The intended acceptance chain is:

```text
one bag
  -> validate / init / snapshot
  -> preflight
  -> three estimator runs
  -> trajectory-from-run x3
  -> trajectory frame audit
  -> Common Scan Manifest
  -> Unified Map x3
  -> runtime provenance
  -> Relative SE(3)
  -> diagnostic bundle
```

After all runtime/provenance/frame gates pass, run:

```bash
benchmark_base/bin/lio-benchmark compare relative-se3 --run "$RUN"
```

Required Relative SE(3) evidence:

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

For the current greenhouse three-algorithm smoke, if FAST-LIVO2, FAST-LIO2, and KISS-ICP are all eligible, the expected pair set is:

```text
fast_lio2 <-> fast_livo2
fast_lio2 <-> kiss_icp
fast_livo2 <-> kiss_icp
```

Current greenhouse LiDAR-IMU calibration remains unconfirmed. Therefore numerical Relative SE(3) evidence is diagnostic only. Pairs involving KISS must additionally record that physical-frame normalization used calibration. No Relative SE(3) output from this state may be described as ground-truth error, ATE, RPE, or estimator accuracy.

## Acceptance record template

Update this section only after the actual target run succeeds:

```text
Target run: PENDING
Repository HEAD: PENDING
Bag identity/hash: PENDING

Runtime PASS: PENDING
Runtime identity FROZEN: PENDING
Runtime provenance MATCH: PENDING
Frame contract MATCH: PENDING
Relative SE(3) artifacts: PENDING
Normalized t0 identity check: PENDING
Pair count: PENDING
Calibration status: PENDING
Scientific status: PENDING
Diagnostic bundle: PENDING

TARGET_ONE_BAG_ACCEPTANCE = PENDING
```
