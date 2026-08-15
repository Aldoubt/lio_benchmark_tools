# LIO Benchmark Baseline Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend LIO Benchmark Tools V2 into a reusable cross-scene baseline suite with Core/Research algorithm families, canonical calibration conversion, common scan sampling, Native/Unified map artifacts, display-only alignment, role-aware reporting, and representative algorithm adapters.

**Architecture:** Keep the existing V2 Dataset Registry, Algorithm Registry, frozen run directory, timestamp-based trajectory standardization, Inspector, Report/Demo, and Live Debug boundaries. Add small focused libraries for calibration, sampling, artifact roles, display transforms, and adapter preflight, then migrate current algorithms without breaking historical IDs before adding FAST-LIO2, KISS-ICP, current Leg-KILO master, LIO-SAM, Faster-LIO, and SLICT.

**Tech Stack:** Python 3.10 standard library + NumPy for core math, ROS 2 Humble runtime adapters, Open3D optional Inspector dependency, matplotlib/reporting dependencies already used by V2, shell adapters for upstream launch integration, GitHub Actions for headless contract verification.

## Global Constraints

- Implementation base MUST include the real green-house verification fixes `3807a03` and `33e32b3` or their pushed descendants before code migration starts.
- Preserve historical registry IDs: `fast_livo2`, `point_lio`, `dlio`, `glim_odometry`, `glim_full_slam`, `leg_kilo2_lidar_imu`.
- Current `ouguangjun/Leg-KILO` `master` is canonical ID `leg_kilo`; historical `leg_kilo2_lidar_imu` is never silently reinterpreted.
- Formal benchmark replay defaults to `BAG_PLAY_RATE=1.0` and algorithms execute one at a time.
- Dataset Registry owns canonical `LIDAR_TO_IMU` calibration; adapters convert conventions mathematically and never mutate upstream source.
- `UNCONFIRMED` LiDAR/IMU calibration forces LiDAR+IMU comparison results to `DIAGNOSTIC_ONLY` / `BLOCKED_CALIBRATION` for formal ranking.
- Unified Maps consume one frozen `selected_scans.csv` for the run.
- Native Map and Unified Map are distinct artifacts; benchmark-generated accumulation is never labeled Native Map.
- Display Alignment is visualization-only. Initial modes are exactly `NONE` and `START_XY_YAW`; no ICP/Umeyama/best-fit alignment in the default path.
- Display Alignment must not modify raw outputs, standardized trajectories, maps, map metadata, or scientific metrics.
- Missing upstream outputs are represented explicitly (`NOT_PROVIDED`, `MISSING`, `BLOCKED_*`) and never converted to zeros.
- Large rosbag/PCD/PLY/run outputs remain outside Git.

---

### Task 1: Extend Registry Schema for Baseline Families and Roles

**Files:**
- Modify: `benchmark_base/lib/registry.py`
- Modify: `benchmark_base/lib/manifest.py`
- Create: `benchmark_base/lib/algorithm_roles.py`
- Modify/Create: `benchmark_base/tests/test_registry.py`
- Modify: existing files under `benchmark_base/registry/algorithms/`
- Create registry records for `fast_lio2`, `lio_sam`, `leg_kilo`, `kiss_icp`, `faster_lio`, `slict`

**Interfaces:**
- Consumes: existing `Registry.load_algorithm()` / V2 manifest resolution.
- Produces: `AlgorithmTier`, `EvaluationRole`, `normalize_algorithm_record(record)`, canonical family metadata, output-role declarations, historical alias compatibility.

- [ ] **Step 1: Write failing registry tests**

Test that all records expose:

```python
for algorithm_id in (
    "fast_livo2", "fast_lio2", "point_lio", "dlio", "lio_sam",
    "glim_odometry", "glim_full_slam", "leg_kilo", "kiss_icp",
    "faster_lio", "slict", "leg_kilo2_lidar_imu",
):
    record = registry.load_algorithm(algorithm_id)
    assert record["tier"] in {"CORE", "RESEARCH", "LEGACY"}
    assert record["family"]
    assert record["evaluation_roles"]
    assert record["sensor_profile"]
```

Also assert:

```python
assert registry.load_algorithm("leg_kilo")["source"]["branch"] == "master"
assert registry.load_algorithm("leg_kilo2_lidar_imu")["algorithm_generation"] != registry.load_algorithm("leg_kilo")["algorithm_generation"]
```

- [ ] **Step 2: Run unit tests and verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_registry -v
```

Expected: failure because tier/family/roles/new registry records are absent.

- [ ] **Step 3: Add role/tier normalization and registry validation**

`algorithm_roles.py` defines string constants and validation helpers without adding external dependencies.

- [ ] **Step 4: Add/upgrade registry records**

Use canonical source identities and mark adapter readiness explicitly:

```json
"adapter_status": "NOT_TESTED"
```

until real-machine smoke passes.

- [ ] **Step 5: Run registry tests GREEN and full unit suite**

```bash
python3 -m unittest discover -s benchmark_base/tests -v
```

- [ ] **Step 6: Commit**

```bash
git add benchmark_base/lib benchmark_base/tests benchmark_base/registry/algorithms
git commit -m "feat: add baseline family and role registry"
```

---

### Task 2: Canonical Calibration and Convention Conversion

**Files:**
- Create: `benchmark_base/lib/calibration.py`
- Modify: `benchmark_base/lib/registry.py`
- Modify: `benchmark_base/lib/manifest.py`
- Create: `benchmark_base/tests/test_calibration.py`
- Modify: `benchmark_base/bin/lio-benchmark`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class RigidTransform:
    rotation: tuple[float, ...]  # row-major 3x3
    translation: tuple[float, float, float]

invert_transform(transform: RigidTransform) -> RigidTransform
resolve_algorithm_extrinsic(dataset: dict, algorithm: dict) -> dict
```

- [ ] **Step 1: Write RED tests for inverse extrinsics**

Test identity and non-trivial transforms and verify:

```text
R_il = R_li.T
t_il = -R_li.T @ t_li
```

Also verify `NONE`, `LIDAR_TO_IMU`, `IMU_TO_LIDAR` conventions.

- [ ] **Step 2: Run tests and verify failure**

- [ ] **Step 3: Implement pure calibration module**

No ROS imports. Reject malformed/non-finite matrices and unknown conventions.

- [ ] **Step 4: Freeze generated algorithm calibration at run init/prepare**

Write under:

```text
configs/generated/<algorithm>/calibration.json
```

including canonical source/status and generated convention.

- [ ] **Step 5: Add diagnostic-only calibration status propagation**

Formal LiDAR+IMU ranking must not claim comparable status when dataset calibration status is `UNCONFIRMED`.

- [ ] **Step 6: Run all tests and commit**

```bash
git commit -m "feat: add canonical calibration conversion"
```

---

### Task 3: Freeze Common LiDAR Scan Sampling Manifest

**Files:**
- Create: `benchmark_base/lib/map_sampling.py`
- Create: `evaluators/build_scan_manifest.py`
- Modify: `evaluators/standardize_map.py`
- Create: `benchmark_base/tests/test_map_sampling.py`

**Interfaces:**
- Produces `standardized/map_sampling/selected_scans.csv` with:

```text
scan_index,timestamp_s,timestamp_source,bag_record_time_s,lidar_topic,selected
```

- [ ] **Step 1: RED tests for deterministic selection**

Given timestamps 0..9 and `scan_step=3`, assert selected scan indices are `[0,3,6,9]` and preserved identically for every algorithm.

- [ ] **Step 2: Implement manifest model and CSV read/write**

- [ ] **Step 3: Implement bag manifest builder using the same timestamp precedence as map standardization**

Header stamp -> point time -> bag record time.

- [ ] **Step 4: Modify `standardize_map.py` to consume the frozen manifest**

Do not independently choose scans per algorithm. Missing trajectory matches are counted, not removed from the common manifest.

- [ ] **Step 5: Regression test green-house ratio semantics**

A 6230-frame bag with scan step 5 conceptually yields 1246 selected entries; algorithm matched count is separately recorded.

- [ ] **Step 6: Run tests/compile and commit**

```bash
git commit -m "feat: freeze common map scan sampling"
```

---

### Task 4: Upgrade Two-Map Artifact Contract with Backward Compatibility

**Files:**
- Modify: `benchmark_base/lib/artifacts.py`
- Modify: `evaluators/standardize_map.py`
- Create: `evaluators/collect_native_map.py`
- Modify: `benchmark_base/bin/lio-benchmark`
- Modify: `benchmark_base/tests/test_artifacts.py`

**Interfaces:**
- New layout:

```text
standardized/maps/<algorithm>/native/map.*
standardized/maps/<algorithm>/native/metadata.json
standardized/maps/<algorithm>/unified/map.ply
standardized/maps/<algorithm>/unified/metadata.json
```

- Compatibility mirrors remain readable:

```text
standardized/maps/<algorithm>/unified_map.ply
standardized/maps/<algorithm>/map_metadata.json
```

- [ ] **Step 1: RED tests for native/unified status**

Ensure `NATIVE` can be `AVAILABLE`, `NOT_PROVIDED`, `FAILED`; `UNIFIED_RECONSTRUCTION` includes sampling manifest and trajectory role.

- [ ] **Step 2: Implement map artifact helpers**

- [ ] **Step 3: Migrate unified output path without breaking existing V2 commands**

- [ ] **Step 4: Add native collector that copies/links only declared upstream output**

It must never reconstruct a map and call it native.

- [ ] **Step 5: Run tests and commit**

```bash
git commit -m "feat: separate native and unified map artifacts"
```

---

### Task 5: Add Display Alignment as a Pure Derived Transform

**Files:**
- Create: `benchmark_base/lib/display_alignment.py`
- Create: `benchmark_base/tests/test_display_alignment.py`
- Modify: `visualization/map_inspector.py`
- Modify: `reporting/generate_report.py`
- Modify: `reporting/generate_demo.py`

**Interfaces:**

```python
compute_display_alignment(initial_pose, mode: str) -> numpy.ndarray
apply_display_transform_xyz(points, matrix) -> numpy.ndarray
apply_display_transform_pose(position, quaternion, matrix) -> tuple
```

Supported modes exactly `NONE`, `START_XY_YAW`.

- [ ] **Step 1: RED tests proving START_XY_YAW behavior**

Assert transformed initial X/Y/yaw are zero while initial Z and roll/pitch remain unchanged within tolerance.

- [ ] **Step 2: Implement pure transform functions**

No ICP and no fitting against another algorithm.

- [ ] **Step 3: Persist transform metadata**

```text
figures/display_alignment/<algorithm>__<role>.json
```

- [ ] **Step 4: Integrate Inspector toggle and visible label**

Inspector loads scientific artifacts unchanged, applies transform to in-memory display geometry only.

- [ ] **Step 5: Integrate report/demo with shared alignment mode**

Figures/GIF use the same mode and state it in report metadata/caption helper.

- [ ] **Step 6: Verify artifact hashes do not change after aligned rendering**

Add a regression test that hashes an input PLY/CSV before and after derived-transform generation.

- [ ] **Step 7: Run tests and commit**

```bash
git commit -m "feat: add display-only start alignment"
```

---

### Task 6: Role-Aware Inspector, Report, Demo, and Scoreboards

**Files:**
- Create: `benchmark_base/lib/scoreboards.py`
- Modify: `visualization/map_inspector.py`
- Modify: `reporting/generate_report.py`
- Modify: `reporting/generate_demo.py`
- Create: `benchmark_base/tests/test_scoreboards.py`

**Interfaces:**
- Scoreboards: `COMMON_LIO`, `SYSTEM_MAPPING`, `CONTROL_EXTENSION`.
- Map selector: `native | unified`.
- Trajectory selector includes evaluation role.

- [ ] **Step 1: RED tests for scoreboard eligibility**

KISS-ICP must not appear in `COMMON_LIO`; FAST-LIVO2 LIV mode must not be mixed with LiDAR+IMU-only runs; GLIM backend appears in system mapping.

- [ ] **Step 2: Implement eligibility filters**

- [ ] **Step 3: Update Inspector controls/data labels**

- [ ] **Step 4: Update report summary tables and missing-status semantics**

- [ ] **Step 5: Update demo labels to include dataset, sensor profile, map kind, alignment mode**

- [ ] **Step 6: Run tests and commit**

```bash
git commit -m "feat: add role-aware benchmark views"
```

---

### Task 7: Add Generic Adapter Preflight/Prepare/Collect Framework

**Files:**
- Create: `benchmark_base/lib/adapters.py`
- Create: `benchmark_base/tests/test_adapters.py`
- Modify: `benchmark_base/bin/lio-benchmark`
- Modify: `benchmark_base/lib/live_debug.py`

**Interfaces:**

```python
preflight_algorithm(run_manifest: dict, algorithm_id: str) -> AdapterStatus
prepare_algorithm(run_dir: Path, algorithm_id: str) -> PreparedAdapter
collect_algorithm(run_dir: Path, algorithm_id: str) -> CollectionReport
```

- [ ] **Step 1: RED tests for missing repo/build/topic/calibration**

- [ ] **Step 2: Implement structured preflight result statuses**

Use only the approved status vocabulary.

- [ ] **Step 3: Generate run-local adapter configuration**

Never edit upstream YAML automatically.

- [ ] **Step 4: Make formal runner execute preflight before shell launch**

Blocked preflight writes metadata and exits without pretending algorithm failure.

- [ ] **Step 5: Reuse preflight in Live Debug session generation**

- [ ] **Step 6: Run tests and commit**

```bash
git commit -m "feat: add adapter lifecycle preflight"
```

---

### Task 8: FAST-LIO2 Core Adapter

**Files:**
- Create: `benchmark_base/registry/algorithms/fast_lio2.json`
- Create: `evaluators/run_fast_lio2_test.sh`
- Create: `benchmark_base/docs/adapters/FAST_LIO2.md`
- Modify: adapter tests/CI syntax list

**Interfaces:**
- Inputs: dataset LiDAR/IMU topics, canonical calibration, point-time contract.
- Outputs: native odometry, `cloud_registered` when available, native map/export when available, standardized ODOMETRY trajectory.

- [ ] **Step 1: Write registry/preflight test before adapter implementation**
- [ ] **Step 2: Add generated FAST-LIO2 config mapping canonical calibration**
- [ ] **Step 3: Implement runner with `BAG_PLAY_RATE=1.0` default and isolated output**
- [ ] **Step 4: Implement collect metadata/output declarations**
- [ ] **Step 5: `bash -n` + registry tests + compile**
- [ ] **Step 6: Commit**

```bash
git commit -m "feat: add FAST-LIO2 baseline adapter"
```

---

### Task 9: KISS-ICP LiDAR-Only Control Adapter

**Files:**
- Create: `benchmark_base/registry/algorithms/kiss_icp.json`
- Create: `evaluators/run_kiss_icp_test.sh`
- Create: `benchmark_base/docs/adapters/KISS_ICP.md`

**Interfaces:**
- Input: LiDAR only; calibration convention `NONE`.
- Output: LiDAR odometry; Native Map may be `NOT_PROVIDED`; Unified Map generated normally.

- [ ] **Step 1: RED test that KISS-ICP preflight does not require IMU/calibration**
- [ ] **Step 2: Implement registry and ROS topic remap adapter**
- [ ] **Step 3: Declare native-map status honestly**
- [ ] **Step 4: Verify control scoreboard membership**
- [ ] **Step 5: Run tests and commit**

```bash
git commit -m "feat: add KISS-ICP control adapter"
```

---

### Task 10: Current Leg-KILO Master Core Adapter

**Files:**
- Create: `benchmark_base/registry/algorithms/leg_kilo.json`
- Create: `evaluators/run_leg_kilo_test.sh` or replace only the current-master path while preserving historical adapter under a distinct filename
- Create: `benchmark_base/docs/adapters/LEG_KILO_MASTER.md`
- Preserve: historical `leg_kilo2_lidar_imu` record/adapter

**Interfaces:**
- Source identity: `ouguangjun/Leg-KILO`, branch `master`.
- Custom handheld mode: `sensor_type=LIO`, no kinematics.
- Upstream custom dataset contract includes Livox support, `time_scale`, topics, and upstream IMU-to-LiDAR extrinsic convention.
- Outputs: frontend ODOMETRY role, backend SYSTEM_MAPPING role, native global/tiled map references when exposed.

- [ ] **Step 1: RED tests that `leg_kilo` and historical `leg_kilo2_lidar_imu` are distinct generations**
- [ ] **Step 2: Generate current-master YAML from frozen dataset contract**
- [ ] **Step 3: Convert canonical LiDAR-to-IMU extrinsic to upstream required convention**
- [ ] **Step 4: Implement ROS2 launch runner without modifying upstream repository**
- [ ] **Step 5: Implement role-aware collection metadata**
- [ ] **Step 6: Run static tests and commit**

```bash
git commit -m "feat: add current Leg-KILO baseline adapter"
```

---

### Task 11: LIO-SAM and GLIM Role Migration

**Files:**
- Create: `benchmark_base/registry/algorithms/lio_sam.json`
- Create: `evaluators/run_lio_sam_test.sh`
- Create: `benchmark_base/docs/adapters/LIO_SAM.md`
- Modify: `glim_odometry.json`, `glim_full_slam.json`
- Modify: existing GLIM adapters and collection metadata only as required

**Interfaces:**
- LIO-SAM exposes mapOptimization/system mapping outputs and keyframe/loop diagnostics when available.
- GLIM legacy runnable IDs remain, both declare `family=glim` and distinct roles.

- [ ] **Step 1: RED tests for role grouping and legacy GLIM IDs**
- [ ] **Step 2: Add LIO-SAM registry/config generation/runner**
- [ ] **Step 3: Add GLIM family metadata without changing historical commands**
- [ ] **Step 4: Preserve odometry/backend artifacts separately**
- [ ] **Step 5: Run tests and commit**

```bash
git commit -m "feat: add LIO-SAM and GLIM role metadata"
```

---

### Task 12: Research Tier Adapters: Faster-LIO and SLICT

**Files:**
- Create: `benchmark_base/registry/algorithms/faster_lio.json`
- Create: `benchmark_base/registry/algorithms/slict.json`
- Create: `evaluators/run_faster_lio_test.sh`
- Create: `evaluators/run_slict_test.sh`
- Create: `benchmark_base/docs/adapters/FASTER_LIO.md`
- Create: `benchmark_base/docs/adapters/SLICT.md`

**Interfaces:**
- Tier `RESEARCH`; absence does not invalidate core-suite run.
- SLICT preflight reports unsupported/missing ROS environment explicitly instead of applying hidden porting patches.

- [ ] **Step 1: RED tests for research-tier optionality**
- [ ] **Step 2: Implement Faster-LIO registry/adapter contract**
- [ ] **Step 3: Implement SLICT registry/preflight contract and runner for supported environment**
- [ ] **Step 4: Run static tests and commit**

```bash
git commit -m "feat: add research baseline adapters"
```

---

### Task 13: CI, Documentation, Migration, and Real-Bag Acceptance Guide

**Files:**
- Modify: `.github/workflows/core-python.yml`
- Modify: `README.md`
- Modify: `benchmark_base/docs/V2_WORKFLOW.md`
- Create: `benchmark_base/docs/BASELINE_SUITE.md`
- Create: `docs/verification/baseline_suite_acceptance_template.md`

**Interfaces:**
- CI checks registry completeness, unit contracts, Python compile, and all shell adapters with `bash -n`.
- Real-bag acceptance remains local because algorithm workspaces and large datasets are external.

- [ ] **Step 1: Add CI registry matrix checks for Core 8 + Research 2 + legacy records**
- [ ] **Step 2: Add shell syntax check over every `evaluators/run_*_test.sh`**
- [ ] **Step 3: Document dataset workflow**

```text
register dataset
freeze calibration
preflight suite
short smoke
full run
standardize trajectories
freeze selected scans
native maps
unified maps
display alignment
inspect
report/demo
```

- [ ] **Step 4: Add real-bag acceptance template with PASS/BLOCKED status vocabulary**
- [ ] **Step 5: Run complete headless verification**

```bash
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
for script in evaluators/run_*_test.sh; do bash -n "$script"; done
benchmark_base/bin/lio-benchmark list algorithms
```

Expected: all headless contract checks PASS.

- [ ] **Step 6: Commit**

```bash
git commit -m "docs: finalize reusable baseline suite workflow"
```

---

## Implementation Gate Before Task 1

Before executing Task 1, verify remote implementation base contains the green-house real-data fixes:

```bash
git log --oneline --all --decorate | head -30
```

Required ancestry must include the pushed descendants of:

```text
3807a03 fix: support green-house custom rosbag contract
33e32b3 docs: record green-house v2 verification
```

If they are absent from the remote implementation branch, STOP code implementation and push/synchronize those commits first. Do not recreate them from the stale `582e8fc` branch because that risks losing validated bag-contract changes.

## Post-Implementation Real-Machine Acceptance Order

After headless CI passes, use the frozen green-house dataset in this order:

```text
FAST-LIVO2 regression
FAST-LIO2
KISS-ICP
Leg-KILO master
Point-LIO
DLIO
GLIM odometry/full
LIO-SAM
Faster-LIO
SLICT when supported
```

For each adapter: `preflight -> short smoke -> full bag -> trajectory standardization -> native map collection -> unified map -> Inspector -> report`.

Do not promote an adapter registry `adapter_status` to `PASS` until its real-machine smoke/full-bag acceptance record exists.