# Mid-360 Factory Extrinsic Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the Livox Mid-360 internal LiDAR→IMU transform with explicit manufacturer provenance, force FAST-LIVO2/FAST-LIO2/map/Relative-SE3 consumers to use the same canonical direction, and prepare a fresh three-algorithm comparison.

**Architecture:** Keep `benchmark_base/lib/calibration.py` as the sole transform resolver and correct the green-house dataset registry to canonical `T_IL`. FAST-LIO2 continues consuming generated calibration directly; FAST-LIVO2 gains a benchmark-owned run-local params generator so it no longer inherits the sign-ambiguous external YAML. KISS remains LiDAR-only and is normalized only in downstream physical-frame comparisons.

**Tech Stack:** Python 3.10, JSON registry, ROS 2 Humble launch/YAML parameter files, Bash runners, unittest, GitHub Actions Core Contracts.

## Global Constraints

- Canonical notation: `T_AB` maps frame B coordinates into frame A coordinates.
- Canonical transform: `T_IL`, `p_I = R_IL * p_L + t_IL`.
- `R_IL = I`.
- `t_IL = [-0.011, -0.02329, +0.04412] m`.
- Manufacturer point-location evidence: `^L p_I = [+0.011, +0.02329, -0.04412] m`.
- Calibration status: `MANUFACTURER_SPEC`.
- FAST-LIVO2 and FAST-LIO2 use fixed extrinsics; no online re-estimation.
- KISS-ICP estimator remains `extrinsic_convention = NONE`.
- Existing frozen runs and bundles are immutable historical evidence.
- Relative SE(3) remains no-GT `PAIRWISE_DISAGREEMENT`; no accuracy/ATE claims.
- Do not modify `main`.
- Do not modify the external `agt_navigation_v2` runtime repository merely to satisfy benchmark semantics.

---

### Task 1: Freeze canonical manufacturer-spec calibration

**Files:**
- Modify: `benchmark_base/lib/calibration.py`
- Modify: `benchmark_base/lib/adapters.py`
- Modify: `benchmark_base/registry/datasets/green_house_mid360.json`
- Test: `benchmark_base/tests/test_calibration.py`
- Test: `benchmark_base/tests/test_registry.py`
- Create: `benchmark_base/tests/test_mid360_factory_extrinsic.py`

**Interfaces:**
- Consumes: existing `RigidTransform`, `invert_transform()`, `canonical_lidar_to_imu()`, `resolve_algorithm_extrinsic()`.
- Produces: `USABLE_CALIBRATION_STATUSES = {"CONFIRMED", "VERIFIED", "MANUFACTURER_SPEC"}` (retain `CONFIRMED_CALIBRATION_STATUSES` as a backward-compatible alias if needed), manufacturer metadata propagated into generated calibration JSON, and preflight acceptance of `MANUFACTURER_SPEC`.

- [ ] **Step 1: Write failing calibration/registry tests**

Add tests that load the real `green_house_mid360` registry and assert:

```python
canonical = canonical_lidar_to_imu(dataset)
self.assertEqual((-0.011, -0.02329, 0.04412), canonical.translation)
self.assertEqual(
    [0.011, 0.02329, -0.04412],
    dataset["calibration"]["manufacturer_imu_origin_in_lidar_m"],
)
self.assertEqual("MANUFACTURER_SPEC", calibration_status(dataset))
self.assertEqual((0.011, 0.02329, -0.04412), invert_transform(canonical).translation)
```

Also assert `resolve_algorithm_extrinsic(... LIDAR_TO_IMU ...)` reports `diagnostic_only == False` and preserves provenance fields such as `source_type`, `sensor_model`, `imu_relation`, and `canonical_equation`.

Add a preflight unit contract proving a LIO algorithm with `MANUFACTURER_SPEC` is not returned as `BLOCKED_CALIBRATION`.

- [ ] **Step 2: Run exact-head CI and verify RED**

Push only tests and expect Core Contracts Unit Contracts to fail because the registry still has the old positive canonical vector/status and the code does not recognize `MANUFACTURER_SPEC`.

- [ ] **Step 3: Implement the minimal canonical status/provenance changes**

Update calibration helper status handling and return metadata. Replace adapter hard-coded `{CONFIRMED, VERIFIED}` with the shared usable-status constant.

Update `green_house_mid360.json` calibration to:

```json
{
  "canonical_convention": "LIDAR_TO_IMU",
  "canonical_equation": "p_I = R_IL * p_L + t_IL",
  "rotation_lidar_to_imu_row_major": [1,0,0,0,1,0,0,0,1],
  "translation_lidar_to_imu_m": [-0.011, -0.02329, 0.04412],
  "manufacturer_imu_origin_in_lidar_m": [0.011, 0.02329, -0.04412],
  "status": "MANUFACTURER_SPEC",
  "source_type": "MANUFACTURER_SPEC",
  "sensor_model": "Livox Mid-360",
  "imu_relation": "INTERNAL_IMU",
  "online_extrinsic_estimation": false
}
```

Retain explicit references to Livox Mid-360 manufacturer documentation and hku-mars FAST-LIO `config/mid360.yaml`/README convention in source/reference fields.

- [ ] **Step 4: Run exact-head CI and verify GREEN**

Expected: all calibration, registry, adapter and existing contracts pass.

- [ ] **Step 5: Commit**

Commit message: `fix: freeze Mid360 factory extrinsic semantics`.

---

### Task 2: Make FAST-LIVO2 consume benchmark-owned canonical extrinsic

**Files:**
- Create: `benchmark_base/config/templates/fast_livo2_mid360.yaml.in`
- Create: `evaluators/prepare_fast_livo2_config.py`
- Modify: `evaluators/run_fast_livo_test.sh`
- Create: `benchmark_base/tests/test_fast_livo2_factory_config.py`

**Interfaces:**
- Consumes: run-local `configs/generated/fast_livo2/calibration.json` produced by `prepare_algorithm()` and frozen run manifest.
- Produces: run-local `configs/generated/fast_livo2/runtime_params.yaml` and `adapter_config_metadata.json`; runner passes `params_file:=<absolute run-local runtime_params.yaml>` to `agt_mapping fast_livo2_mapping.launch.py`.

- [ ] **Step 1: Write failing generator/runner tests**

Tests must verify:

```python
self.assertIn("extrinsic_T: [-0.011, -0.02329, 0.04412]", generated_text)
self.assertIn("extrinsic_R: [1.0, 0.0, 0.0", generated_text)
```

and source-contract checks must verify the runner:

- invokes `prepare_fast_livo2_config.py` before the estimator;
- passes `params_file:=...runtime_params.yaml` in `estimator_cmd`;
- never relies solely on the external launch default params file.

- [ ] **Step 2: Run exact-head CI and verify RED**

Expected failure: generator/template do not exist and runner does not pass explicit params file.

- [ ] **Step 3: Add benchmark-owned FAST-LIVO2 template**

Track a full known-good Mid-360 LiDAR-IMU-only parameter template matching the current runtime configuration, but use explicit replacement tokens for LiDAR topic, IMU topic, `extrinsic_T`, and `extrinsic_R`.

Do not change unrelated estimator tuning values as part of this task.

- [ ] **Step 4: Implement generator**

`prepare_fast_livo2_config.py` shall:

1. load `manifest.json`;
2. load run-local `configs/generated/fast_livo2/calibration.json`;
3. require `convention == "LIDAR_TO_IMU"`;
4. require usable calibration status;
5. substitute frozen dataset topics and canonical extrinsic values into the benchmark-owned template;
6. write atomically/refuse unsafe malformed template substitution;
7. write metadata containing calibration source/status/convention/equation and final parameter file path.

- [ ] **Step 5: Wire runner**

Before `estimator_cmd`, run:

```bash
python3 "$BENCHMARK_ROOT/evaluators/prepare_fast_livo2_config.py" \
  --run "$BENCHMARK_RUN_DIR" \
  --output "$BENCHMARK_RUN_DIR/configs/generated/fast_livo2/runtime_params.yaml"
```

and launch with:

```bash
params_file:="$BENCHMARK_RUN_DIR/configs/generated/fast_livo2/runtime_params.yaml"
```

Keep all existing replay/runtime-identity/provenance behavior unchanged.

- [ ] **Step 6: Run exact-head CI and verify GREEN**

Expected: generator contracts, shell syntax and all prior contracts pass.

- [ ] **Step 7: Commit**

Commit message: `fix: inject canonical Mid360 extrinsic into FAST-LIVO2`.

---

### Task 3: Lock all consumer directions with regression tests

**Files:**
- Modify/Test: `benchmark_base/tests/test_calibration.py`
- Modify/Test: `benchmark_base/tests/test_map_frame_contract.py`
- Modify/Test: `benchmark_base/tests/test_relative_se3.py`
- Create: `benchmark_base/tests/test_fast_lio2_factory_config.py`
- Modify if necessary: `evaluators/prepare_fast_lio2_config.py`
- Modify if necessary: `benchmark_base/lib/relative_se3.py`
- Modify if necessary: `benchmark_base/lib/map_frame_contract.py`

**Interfaces:**
- FAST-LIO2 consumes `T_IL` directly.
- Unified Map IMU-body conversion consumes `T_IL` directly.
- Relative SE(3) LiDAR→IMU pose normalization uses `T_LI = inverse(T_IL)`.

- [ ] **Step 1: Add directional regression tests**

Test exact numeric behavior:

```python
# canonical T_IL
p_I = lidar_points_in_tracked_frame(
    np.array([[0.0, 0.0, 0.0]]),
    tracked_frame_physical="IMU_BODY",
    calibration=dataset["calibration"],
)
np.testing.assert_allclose(p_I[0], [-0.011, -0.02329, 0.04412])
```

For Relative SE(3), a world LiDAR identity pose normalized to IMU must translate by `T_LI = [+0.011,+0.02329,-0.04412]` before gauge cancellation.

For FAST-LIO2 generator, assert its YAML receives negative `T_IL` and `extrinsic_est_en: false`.

- [ ] **Step 2: Run exact-head CI and verify RED only if an existing consumer is directionally wrong**

If tests are already GREEN for `map_frame_contract` and Relative SE(3), record that as a confirmed existing implementation contract; do not introduce artificial code changes. The FAST-LIO2 generated-config test must still prove the corrected registry reaches its runtime config.

- [ ] **Step 3: Make only required consumer fixes**

Do not change correct pose composition. Only fix consumers that fail the explicit transform-direction test.

- [ ] **Step 4: Run full exact-head CI**

Expected: all unit contracts, compile checks, shell syntax and registry smoke pass.

- [ ] **Step 5: Commit**

Commit message if production code changed: `fix: enforce Mid360 extrinsic direction across consumers`.

If no production code change is needed: `test: lock Mid360 extrinsic consumer directions`.

---

### Task 4: Close documentation/provenance and prepare fresh unified rerun

**Files:**
- Modify: `benchmark_base/docs/CURRENT_BASELINE.md`
- Modify: `benchmark_base/docs/V2_WORKFLOW.md`
- Modify: `docs/verification/relative_se3_verification.md`
- Create: `docs/verification/mid360_factory_extrinsic_verification.md`
- Modify if needed: diagnostic/reporting contracts that still describe `BLOCKED_CALIBRATION` as current green-house state.

**Interfaces:**
- Produces a documented target-machine acceptance contract for a fresh three-algorithm run.

- [ ] **Step 1: Update active documentation**

Document:

- manufacturer positive point-location vector vs canonical negative `T_IL`;
- exact equation `p_I = R_IL p_L + t_IL`;
- `MANUFACTURER_SPEC` provenance status;
- FAST-LIVO2/FAST-LIO2 fixed extrinsics;
- KISS downstream physical-frame normalization;
- old runs remain historical sign-ambiguous evidence;
- no ground-truth accuracy claims.

- [ ] **Step 2: Add verification record**

Record exact-head unit/compile/shell/registry CI status and mark target-machine fresh three-algorithm acceptance `PENDING`.

- [ ] **Step 3: Run final exact-head CI**

Expected: `Core Contracts` completed/success at the final documentation HEAD.

- [ ] **Step 4: Stop for real-bag acceptance**

Do not reuse old run artifacts. Hand off a Codex workflow that creates a fresh persistent run, requires preflight without `--allow-diagnostic-calibration`, executes FAST-LIVO2/FAST-LIO2/KISS sequentially, checks effective generated extrinsics, standardizes trajectories, runs frame/provenance/coverage, builds strict common maps, runs Relative SE(3), bundles evidence, and reports the new descriptive comparison.

The target acceptance is successful only if the frozen run proves both LIO configs use the negative canonical `T_IL` and downstream map/Relative-SE3 metadata use `MANUFACTURER_SPEC` without calibration-blocked diagnostic reasons.

- [ ] **Step 5: Commit**

Commit message: `docs: record Mid360 factory extrinsic closure`.
