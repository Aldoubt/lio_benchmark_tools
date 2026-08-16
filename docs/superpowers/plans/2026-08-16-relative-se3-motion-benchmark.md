# Relative SE(3) Motion Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a run-local, provenance-gated Relative SE(3) pairwise disagreement benchmark that normalizes trajectories to `IMU_BODY`, removes only each estimator's world gauge, and writes deterministic diagnostic artifacts without ground-truth claims.

**Architecture:** Add one ROS-independent mathematical/run-contract module, one thin evaluator entry point, and one CLI subcommand. Existing standardized trajectories remain immutable; the new module reuses `Trajectory.interpolate_pose`, canonical calibration helpers, and run-local provenance/frame-audit evidence. Existing display-aligned diagnostics remain unchanged.

**Tech Stack:** Python 3.10, stdlib (`csv`, `json`, `hashlib`, `math`, `statistics`, `pathlib`), NumPy, existing benchmark trajectory/calibration/runtime contracts, `unittest`.

## Global Constraints

- Target physical frame: `IMU_BODY`.
- World-gauge normalization: `DeltaT(t) = T(t0)^-1 * T(t)`.
- Global common start: maximum first timestamp across eligible algorithms.
- Global common end: minimum last timestamp across eligible algorithms.
- Fixed `sample_period_s = 0.1`.
- Fixed `sustain_samples = 3`.
- Translation onset thresholds: `[0.05, 0.10, 0.20, 0.50]` m.
- Rotation onset thresholds: `[1, 2, 5, 10]` deg.
- Rotation disagreement: SO(3) geodesic angle.
- No SE(3)/Umeyama/ICP fitting, no START_XY_YAW, no warmup trimming, no ATE/RPE/accuracy claims.
- Structurally valid but unconfirmed calibration permits diagnostic KISS output; malformed/missing calibration blocks only pairs that need it.
- Existing standardized trajectories must not be modified.

---

### Task 1: Core Relative SE(3) mathematics

**Files:**
- Create: `benchmark_base/lib/relative_se3.py`
- Create: `benchmark_base/tests/test_relative_se3.py`

**Interfaces:**
- Consumes: `PoseSample`, `Trajectory.interpolate_pose`, `RigidTransform`, `invert_transform`.
- Produces: immutable pose/relative-motion dataclasses and pure functions for pose composition/inversion, interpolation-to-target-frame, common evaluation times, gauge normalization, pairwise disagreement, statistics, and sustained onset.

- [ ] **Step 1: Write failing math tests** covering identical motion under different world gauges, common `t0`, non-zero LiDAR lever arm transform direction, quaternion sign invariance, ±pi-safe SO(3) geodesic angle, and endpoint-inclusive fixed time grid.

- [ ] **Step 2: Run `python3 -m unittest benchmark_base.tests.test_relative_se3 -v` and confirm RED** because `benchmark_base.lib.relative_se3` does not yet exist.

- [ ] **Step 3: Implement minimal pure math** using 3x3 NumPy rotations and 3-vectors. Build pose rotation from normalized quaternion, compose/invert rigid poses, convert `LIDAR` poses via `T_WI = T_WL * inverse(T_IL)`, then compute `DeltaT = T0^-1 * T`.

- [ ] **Step 4: Implement pairwise sample statistics** for signed `dx/dy/dz`, XY, Z absolute, XYZ, and SO(3) geodesic disagreement with RMSE/median/P95/max/peak time.

- [ ] **Step 5: Implement sustained onset** requiring three consecutive samples above each fixed threshold, returning null onset when never crossed.

- [ ] **Step 6: Re-run the Task 1 tests and confirm GREEN.**

- [ ] **Step 7: Commit** `feat: add relative se3 motion core`.

### Task 2: Run evidence gating and deterministic artifacts

**Files:**
- Modify: `benchmark_base/lib/relative_se3.py`
- Modify: `benchmark_base/tests/test_relative_se3.py`
- Create: `evaluators/compare_relative_se3.py`

**Interfaces:**
- Consumes: frozen `manifest.json`, `metadata/algorithms/<id>/runtime_identity.json`, `metrics/runtime_provenance.csv`, `metrics/trajectory_frame_audit.csv`, and `standardized/trajectories/<id>.csv`.
- Produces: `metrics/relative_se3/{metadata.json,normalized_motion.csv,pairwise_samples.csv,pairwise_summary.csv,onset_thresholds.csv}`.

- [ ] **Step 1: Add RED gating tests** proving runtime identity must be `FROZEN`, provenance must be `MATCH`, frame audit must be `MATCH`, unsupported tracked frame blocks one algorithm, malformed calibration blocks only LIDAR-dependent pairs, and unconfirmed calibration still writes diagnostic results.

- [ ] **Step 2: Add RED artifact tests** proving all five files have deterministic headers/content ordering, input trajectories are fingerprinted, existing output directory is refused rather than overwritten, and source trajectory bytes are unchanged.

- [ ] **Step 3: Implement run-evidence loading** with fail-closed parsing and explicit blocked-reason records. Never infer runtime/frame state from filenames or current shell state.

- [ ] **Step 4: Implement eligibility and pair status** so valid IMU_BODY pairs survive KISS calibration failure, while all current greenhouse pairs remain `DIAGNOSTIC_ONLY` when calibration status is unconfirmed.

- [ ] **Step 5: Implement output writers** with sorted deterministic algorithm/pair ordering and fixed schema metadata.

- [ ] **Step 6: Implement `evaluators/compare_relative_se3.py`** as a thin argument parser calling the run-level core; no ROS imports.

- [ ] **Step 7: Run Task 2 tests and full `test_relative_se3` suite; confirm GREEN.**

- [ ] **Step 8: Commit** `feat: add run-level relative se3 comparison`.

### Task 3: CLI contract and bundle visibility

**Files:**
- Modify: `benchmark_base/bin/lio-benchmark`
- Modify: `benchmark_base/tests/test_cli_manifest.py`
- Modify: `benchmark_base/lib/diagnostic_bundle.py` only if current recursive metrics collection does not already include `metrics/relative_se3`.
- Modify: `benchmark_base/tests/test_diagnostic_bundle.py` only if bundle behavior needs an explicit regression.

**Interfaces:**
- Produces CLI: `lio-benchmark compare relative-se3 --run <run> [--algorithms ...]`.

- [ ] **Step 1: Add a failing CLI parser test** asserting the `compare relative-se3` command exists, requires `--run`, permits only optional `--algorithms`, and exposes no alignment/threshold/sample-period/sustain/extrinsic/reference/warmup options.

- [ ] **Step 2: Wire `cmd_compare_relative_se3`** to invoke `evaluators/compare_relative_se3.py` with the frozen run and optional algorithm list.

- [ ] **Step 3: Verify diagnostic bundle behavior.** If `metrics/relative_se3` is already recursively included, add no production bundle change. Otherwise add the smallest change plus a regression test.

- [ ] **Step 4: Run CLI/bundle tests and confirm GREEN.**

- [ ] **Step 5: Commit** `feat: expose relative se3 comparison cli`.

### Task 4: Documentation and repository verification

**Files:**
- Modify: `benchmark_base/README.md`
- Create: `docs/verification/relative_se3_verification.md`
- Modify: `docs/verification/runtime_overlays_verification.md` to remove the obsolete statement that the final HEAD still awaits CI.

**Interfaces:**
- Documents the exact one-bag acceptance chain and scientific limitations.

- [ ] **Step 1: Document the command** `lio-benchmark compare relative-se3 --run "$RUN"` after trajectory/frame/provenance gates.

- [ ] **Step 2: Document five fixed artifacts** and explain `DIAGNOSTIC_ONLY`, `PAIRWISE_DISAGREEMENT`, and absence of GT/ATE/RPE claims.

- [ ] **Step 3: Add target-machine verification template** with run path, repository HEAD, pairwise summary, onset rows, calibration status, and final gates marked `PENDING` until the one-bag target run is executed.

- [ ] **Step 4: Run repository verification**:

```bash
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 benchmark_base/bin/lio-benchmark list algorithms
```

- [ ] **Step 5: Commit** `docs: document relative se3 benchmark acceptance`.

- [ ] **Step 6: Require exact-head GitHub Actions `Core Contracts` success** before claiming repository-side completion.

### Task 5: One-bag target acceptance

**Files:**
- Target run only; no source file is modified unless the target run reveals a genuine bug.

**Interfaces:**
- Input: one rosbag through the existing frozen-run pipeline.
- Output: complete run plus Relative SE(3) artifacts and diagnostic bundle.

- [ ] **Step 1: Create a fresh run from the bag** and execute validate/init/snapshot/preflight plus all selected algorithm runners.

- [ ] **Step 2: Run `trajectory-from-run`, trajectory frame audit, common scan manifest, unified maps, and runtime provenance.** Require runtime/provenance/frame gates to pass before Relative SE(3).

- [ ] **Step 3: Run**:

```bash
benchmark_base/bin/lio-benchmark compare relative-se3 --run "$RUN"
```

- [ ] **Step 4: Verify** all five Relative SE(3) artifacts, common `t0`, identity first normalized motions, three pair summaries when all algorithms are eligible, sustained onset rows, and diagnostic calibration labels.

- [ ] **Step 5: Bundle the run** and verify the small Relative SE(3) evidence is present while raw bags/maps/binaries remain excluded.

- [ ] **Step 6: Update `docs/verification/relative_se3_verification.md` only after the actual one-bag target run passes.**
