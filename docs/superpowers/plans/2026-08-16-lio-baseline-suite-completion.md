# LIO Baseline Suite Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the already-started baseline-suite implementation on `feat/lio-baseline-suite`, restore green CI, complete the remaining portability/research-adapter gaps, and leave the branch ready for real-machine multi-algorithm integration smoke tests.

**Architecture:** Preserve the current V2-compatible Registry → Adapter → Raw Output → Standardization → Native/Unified Map → Inspector/Report pipeline. Treat the existing modules (`calibration.py`, `map_sampling.py`, `display_alignment.py`, `scoreboards.py`, existing Core adapters) as the implementation baseline and change them only where a failing contract or frozen spec requires it.

**Tech Stack:** Python 3.10 standard library + NumPy for core contracts, ROS 2 Humble shell adapters for supported algorithms, Open3D optional visualization, GitHub Actions contract CI.

## Global Constraints

- Do not break existing V2 paths: `standardized/trajectories/<algorithm>.csv`, `standardized/maps/<algorithm>/unified_map.ply`, `map_metadata.json`.
- Native Map and Unified Map remain distinct artifacts; benchmark reconstruction must never be labeled Native.
- Display Alignment supports only `NONE` and `START_XY_YAW` and never mutates scientific artifacts.
- Dataset Registry owns canonical `LIDAR_TO_IMU`; adapters generate any required inverse convention run-locally.
- Formal benchmark default is `BAG_PLAY_RATE=1.0` and algorithms run independently.
- `leg_kilo` means current `ouguangjun/Leg-KILO` master; `leg_kilo2_lidar_imu` remains historical.
- Missing environments/dependencies are explicit blocker statuses, never PASS.
- Large bags, maps, and upstream repositories are not committed.

---

### Task 1: Restore adapter preflight CI and make runtime environment explicit

**Files:**
- Modify: `benchmark_base/lib/adapters.py`
- Test: `benchmark_base/tests/test_adapters.py`

**Interfaces:**
- Consumes: `algorithm["environment_requirements"]["ros_distros"]`, optional `runtime_env: Mapping[str, str]`.
- Produces: `preflight_algorithm(..., runtime_env=None) -> AdapterStatus` with unsupported ROS distributions classified as `BLOCKED_ENVIRONMENT`.

- [ ] **Step 1: Keep the existing failing regression test**

The branch already contains:

```python
def test_unsupported_ros_distro_is_blocked_environment(self):
    manifest["algorithms"]["lio"]["environment_requirements"] = {"ros_distros": ["noetic"]}
    result = preflight_algorithm(..., runtime_env={"ROS_DISTRO": "humble"})
    self.assertEqual("BLOCKED_ENVIRONMENT", result.status)
```

- [ ] **Step 2: Confirm the regression currently fails**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_adapters.AdapterLifecycleTest.test_unsupported_ros_distro_is_blocked_environment -v
```

Expected before fix: `TypeError: preflight_algorithm() got an unexpected keyword argument 'runtime_env'`.

- [ ] **Step 3: Implement minimal runtime environment checking**

Add an optional runtime environment parameter using `os.environ` by default and fail closed only when an algorithm explicitly declares accepted ROS distributions:

```python
from collections.abc import Mapping
import os


def preflight_algorithm(..., runtime_env: Mapping[str, str] | None = None) -> AdapterStatus:
    env = os.environ if runtime_env is None else runtime_env
    requirements = algorithm.get("environment_requirements", {})
    ros_distros = requirements.get("ros_distros", []) if isinstance(requirements, dict) else []
    active_ros = str(env.get("ROS_DISTRO", ""))
    checks["ros_distro"] = active_ros or None
    checks["supported_ros_distros"] = ros_distros
    if ros_distros and active_ros not in ros_distros:
        reasons.append(
            f"ROS_DISTRO {active_ros or '<unset>'} is unsupported; expected one of: {', '.join(ros_distros)}"
        )
        return AdapterStatus(algorithm_id, "BLOCKED_ENVIRONMENT", False, False, tuple(reasons), checks)
```

- [ ] **Step 4: Run adapter tests**

```bash
python3 -m unittest benchmark_base.tests.test_adapters -v
```

Expected: all adapter lifecycle tests PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/adapters.py benchmark_base/tests/test_adapters.py
git commit -m "fix: enforce adapter ROS environment requirements"
```

### Task 2: Complete preflight portability metadata for Research baselines

**Files:**
- Modify: `benchmark_base/registry/algorithms/faster_lio.json`
- Modify: `benchmark_base/registry/algorithms/slict.json`
- Modify: `benchmark_base/lib/registry.py` only if schema validation does not preserve `environment_requirements`
- Test: `benchmark_base/tests/test_registry.py`
- Test: `benchmark_base/tests/test_adapters.py`

**Interfaces:**
- Consumes: explicit `environment_requirements` and `input_requirements` in registry records.
- Produces: registry records that explain why unsupported research baselines are blocked instead of relying on adapter comments.

- [ ] **Step 1: Add failing registry assertions**

```python
slict = self.registry.load_algorithm("slict")
self.assertIn("environment_requirements", slict)
self.assertTrue(slict["environment_requirements"]["ros_distros"])
```

Add equivalent assertions for Faster-LIO when its supported execution environment is intentionally constrained.

- [ ] **Step 2: Verify the new assertions fail before metadata is added**

```bash
python3 -m unittest benchmark_base.tests.test_registry.RegistryTest -v
```

- [ ] **Step 3: Add exact environment metadata verified from upstream documentation**

Registry form:

```json
"environment_requirements": {
  "ros_distros": ["..."],
  "notes": "Exact supported/selected upstream execution environment"
}
```

Do not invent a Humble-compatible claim if the selected upstream implementation is not documented/tested for Humble.

- [ ] **Step 4: Re-run registry and adapter tests**

```bash
python3 -m unittest benchmark_base.tests.test_registry benchmark_base.tests.test_adapters -v
```

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/registry/algorithms benchmark_base/tests
git commit -m "feat: declare research baseline environment contracts"
```

### Task 3: Implement the Faster-LIO research adapter

**Files:**
- Create: `evaluators/run_faster_lio_test.sh`
- Create: `benchmark_base/docs/adapters/FASTER_LIO.md`
- Modify: `benchmark_base/registry/algorithms/faster_lio.json`
- Test: `benchmark_base/tests/test_registry.py`
- Test: `.github/workflows/core-python.yml` only if the shell glob does not already cover the new script.

**Interfaces:**
- Consumes: `<BAG_DIR> <OUTPUT_DIR>`, `WORKSPACE`, `BAG_PLAY_RATE`, run-local config/environment variables.
- Produces: raw algorithm logs/trajectory/map outputs plus explicit blocker exits when package/source is unavailable.

- [ ] **Step 1: Add a registry contract test requiring an existing adapter path**

```python
record = self.registry.load_algorithm("faster_lio")
runner = self.root / record["runner"]["adapter"]
self.assertTrue(runner.is_file())
```

- [ ] **Step 2: Verify the test fails because `run_faster_lio_test.sh` does not exist**

```bash
python3 -m unittest benchmark_base.tests.test_registry -v
```

- [ ] **Step 3: Add a fail-closed shell adapter**

The script must:

```text
source the selected ROS environment
verify the upstream package/executable exists
reject unsupported dataset message types explicitly
record odometry/native outputs when upstream exposes them
run rosbag at BAG_PLAY_RATE
leave logs under OUTPUT_DIR
return nonzero on startup/recording failure
```

The script must not patch upstream source or silently rewrite calibration/IMU units.

- [ ] **Step 4: Document upstream repository, selected branch/commit policy, topics, outputs, and known platform limitations**

`FASTER_LIO.md` must state whether the adapter is verified or `NOT_TESTED` on ROS 2 Humble.

- [ ] **Step 5: Run contract checks**

```bash
bash -n evaluators/run_faster_lio_test.sh
python3 -m unittest benchmark_base.tests.test_registry -v
```

- [ ] **Step 6: Commit**

```bash
git add evaluators/run_faster_lio_test.sh benchmark_base/docs/adapters/FASTER_LIO.md benchmark_base/registry/algorithms/faster_lio.json benchmark_base/tests/test_registry.py
git commit -m "feat: add Faster-LIO research adapter contract"
```

### Task 4: Implement the SLICT research adapter as an explicit platform-gated baseline

**Files:**
- Create: `evaluators/run_slict_test.sh`
- Create: `benchmark_base/docs/adapters/SLICT.md`
- Modify: `benchmark_base/registry/algorithms/slict.json`
- Test: `benchmark_base/tests/test_registry.py`
- Test: `benchmark_base/tests/test_adapters.py`

**Interfaces:**
- Consumes: the same adapter lifecycle contract as Core baselines.
- Produces: either a runnable SLICT execution command on a supported environment or deterministic `BLOCKED_ENVIRONMENT/BLOCKED_DEPENDENCY` status on unsupported machines.

- [ ] **Step 1: Add a test that the SLICT runner exists and that unsupported `ROS_DISTRO` is blocked before execution**

```python
record = self.registry.load_algorithm("slict")
self.assertTrue((self.root / record["runner"]["adapter"]).is_file())
```

Use `preflight_algorithm(..., runtime_env={"ROS_DISTRO": "humble"})` with the exact supported distro list from the selected upstream implementation.

- [ ] **Step 2: Confirm tests fail before the adapter/metadata is complete**

```bash
python3 -m unittest benchmark_base.tests.test_registry benchmark_base.tests.test_adapters -v
```

- [ ] **Step 3: Add the shell adapter without hidden porting**

The adapter must verify supported environment/package first. If unsupported, it exits before bag replay with a clear message rather than pretending a source port exists.

- [ ] **Step 4: Document the selected upstream implementation and why it is Research Tier**

The documentation must include the exact installation/runtime boundary and state that missing support on the primary Humble machine is an expected environment blocker.

- [ ] **Step 5: Verify**

```bash
bash -n evaluators/run_slict_test.sh
python3 -m unittest benchmark_base.tests.test_registry benchmark_base.tests.test_adapters -v
```

- [ ] **Step 6: Commit**

```bash
git add evaluators/run_slict_test.sh benchmark_base/docs/adapters/SLICT.md benchmark_base/registry/algorithms/slict.json benchmark_base/tests
git commit -m "feat: add SLICT research adapter contract"
```

### Task 5: Audit Inspector/Report/Demo against the frozen Display Alignment contract

**Files:**
- Review/modify only if required: `visualization/map_inspector.py`
- Review/modify only if required: `reporting/generate_report.py`
- Review/modify only if required: `reporting/generate_demo.py`
- Test: `benchmark_base/tests/test_display_alignment.py`
- Test: `benchmark_base/tests/test_reporting_contract.py`

**Interfaces:**
- Consumes: `NONE | START_XY_YAW`, common ROI/camera/map kind/trajectory role.
- Produces: display-derived geometry/metadata without modifying standardized trajectories/maps.

- [ ] **Step 1: Verify all three consumers expose the canonical alignment names**

Search locally:

```bash
grep -R "START_XY_YAW\|display-alignment" visualization reporting benchmark_base/bin/lio-benchmark
```

- [ ] **Step 2: Add/retain tests proving alignment is display-only and missing artifacts remain missing**

```bash
python3 -m unittest benchmark_base.tests.test_display_alignment benchmark_base.tests.test_reporting_contract -v
```

- [ ] **Step 3: Remove any remaining independent per-algorithm viewport/color fitting if found**

Shared comparison bounds and shared scalar ranges must be computed across the compared algorithms after the selected display transform/ROI, not separately per algorithm.

- [ ] **Step 4: Commit only if code changes are needed**

```bash
git add visualization reporting benchmark_base/tests
git commit -m "fix: keep comparison rendering on shared display contracts"
```

### Task 6: Full contract verification and integration handoff

**Files:**
- Modify: `docs/verification/baseline_suite_contract_verification.md`
- Modify: `README.md` / `benchmark_base/docs/V2_WORKFLOW.md` only where the public workflow is stale.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a reproducible verification record and exact next commands for real-machine smoke tests.

- [ ] **Step 1: Run the full core CI commands**

```bash
python3 -m unittest benchmark_base.tests.test_registry -v
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
for f in evaluators/*.sh; do bash -n "$f"; done
benchmark_base/bin/lio-benchmark list algorithms
```

Expected: zero failures.

- [ ] **Step 2: Verify all baseline IDs remain discoverable**

Expected runnable/registry identities include:

```text
fast_livo2
fast_lio2
point_lio
dlio
lio_sam
glim_odometry
glim_full_slam
leg_kilo
kiss_icp
faster_lio
slict
leg_kilo2_lidar_imu
```

- [ ] **Step 3: Record what CI proves vs what still requires the real machine**

The verification doc must separate:

```text
CONTRACT_VERIFIED
REAL_MACHINE_NOT_TESTED
BLOCKED_ENVIRONMENT
BLOCKED_CALIBRATION
```

- [ ] **Step 4: Write the real-machine smoke sequence**

The first integration order remains:

```text
FAST-LIVO2 reference
FAST-LIO2
KISS-ICP
Leg-KILO master
LIO-SAM
GLIM modes
then optional Faster-LIO / SLICT where environment permits
```

Each algorithm first runs a short representative bag segment before the full frozen bag.

- [ ] **Step 5: Commit**

```bash
git add docs README.md benchmark_base/docs
 git commit -m "docs: record baseline suite contract verification"
```
