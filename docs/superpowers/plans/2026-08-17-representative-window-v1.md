# Representative Window V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic raw-sensor representative-window selector that emits four fresh 45 s experiment configs without using estimator outputs.

**Architecture:** Keep scientific scoring ROS-independent in `benchmark_base/lib/representative_windows.py`; keep ROS bag deserialization in a thin evaluator; expose one additive `plan representative-windows` command through the existing dispatcher and shared formal ROS workspace runner. Generated selector evidence and child configs are immutable run-local artifacts.

**Tech Stack:** Python 3.10, NumPy, ROS 2 Humble rosbag2/rclpy for target-machine evaluator, existing benchmark manifest/diagnostic-bundle helpers, unittest/GitHub Actions.

## Global Constraints

- Selection inputs are raw LiDAR + raw IMU only; estimator outputs and ground truth are forbidden.
- V1 constants are fixed: 45 s windows, 5 s stride, 15 s post-initialization guard, LiDAR point step 20, 0.5 m near filter, 30 m / 32-bin range histogram.
- Labels are descriptive candidates; `geometric_degeneracy_candidate` is not a proof of estimator degeneracy.
- Selected windows are pairwise non-overlapping.
- Selector run replay must be `start_offset_s=0`, `duration_s=null`.
- Outputs are immutable and fail closed on partial/stale evidence.
- Existing historical runs remain valid and are not rewritten.

---

### Task 1: Pure representative-window scoring contract

**Files:**
- Create: `benchmark_base/lib/representative_windows.py`
- Create: `benchmark_base/tests/test_representative_windows.py`

**Interfaces:**
- Consumes: timestamped raw LiDAR feature samples and raw IMU norm samples in bag-record offset seconds.
- Produces: `WindowFeature`, `SelectedWindow`, `select_representative_windows(...)`, fixed V1 constants.

- [ ] **Step 1: Write failing tests**

Tests must cover:

```python
# initialization is exactly [0, 45]
# high_angular_motion selects maximum gyro p95
# all four selected windows are non-overlapping
# geometric_degeneracy_candidate prefers high raw structure score among moving candidates
# steady_translation_candidate prefers scene change + low angular motion
# ties resolve to earlier start time
# insufficient non-overlapping candidates fail closed
```

Synthetic tests use only pure numeric samples; no ROS imports.

- [ ] **Step 2: Run exact-head Unit Contracts and confirm RED**

Expected failure: missing `benchmark_base.lib.representative_windows`.

- [ ] **Step 3: Implement minimal pure logic**

Implement:

```python
WINDOW_DURATION_S = 45.0
WINDOW_STRIDE_S = 5.0
POST_INITIALIZATION_GUARD_S = 15.0
MIN_LIDAR_SCANS_PER_WINDOW = 100
MIN_IMU_SAMPLES_PER_WINDOW = 500
```

and deterministic feature aggregation/ranking exactly as the approved design specifies.

- [ ] **Step 4: Run exact-head CI and confirm GREEN**

All pre-existing tests must remain green.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add representative window selection core"
```

---

### Task 2: ROS bag evaluator and child experiment generation

**Files:**
- Create: `evaluators/plan_representative_windows.py`
- Create: `benchmark_base/config/green_house_representative_window_selector.json`
- Create: `benchmark_base/tests/test_representative_window_planner.py`

**Interfaces:**
- Consumes: one schema-v2 frozen selector run with full-bag replay.
- Produces:
  - `metadata/representative_windows/window_features.csv`
  - `metadata/representative_windows/selected_windows.json`
  - `metadata/representative_windows/selection_metadata.json`
  - four `configs/representative_windows/*.json`
  - `reports/REPRESENTATIVE_WINDOW_PLAN.md`

- [ ] **Step 1: Write failing planner tests**

Lock these contracts:

```python
# selector run must be schema-v2, replay start=0, duration=None
# child config preserves dataset_ref/algorithm_refs/execution_overrides/runtime_overlays/standardization
# child config changes only name + replay start/duration
# child duration is always 45.0
# generated config start offsets use bag record-time offsets
# partial existing artifacts fail closed
# identical complete rerun returns existing evidence without rewrite
```

Also source-contract-test the evaluator for:

```text
rclpy.deserialize_message
shared cloud_rows(...)
bag record timestamps for window boundaries
no standardized trajectory/map/Relative SE3 reads
```

- [ ] **Step 2: Confirm RED in exact-head CI**

Expected failure: planner evaluator/config not present.

- [ ] **Step 3: Implement target evaluator**

Evaluator responsibilities:

```text
open frozen bag
establish first bag record timestamp
read only LiDAR and IMU topics for scoring
LiDAR: cloud_rows -> radial histogram + covariance entropy score
IMU: ||omega|| + ||a||
convert all sample times to bag-record offsets
call pure selector
write artifacts atomically
fingerprint generated child configs
```

Generated selector config must preserve the same three algorithms and full-bag replay:

```json
"replay": {"rate": 1.0, "start_offset_s": 0.0, "duration_s": null}
```

- [ ] **Step 4: Run exact-head CI and confirm GREEN**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: plan representative windows from raw bag"
```

---

### Task 3: CLI, bundle evidence, workflow documentation

**Files:**
- Modify: `benchmark_base/bin/lio-benchmark`
- Modify: `benchmark_base/lib/diagnostic_bundle.py`
- Create: `benchmark_base/tests/test_representative_window_cli.py`
- Create: `benchmark_base/tests/test_representative_window_bundle.py`
- Modify: `benchmark_base/docs/V2_WORKFLOW.md`
- Create: `docs/verification/representative_window_v1_verification.md`

**Interfaces:**
- Consumes: selector run.
- Produces: public CLI `lio-benchmark plan representative-windows --run <run>` and portable selector evidence.

- [ ] **Step 1: Write failing CLI/bundle tests**

Lock:

```text
plan representative-windows exposes only --run
handler uses _core.resolve_run + _core.run_python_ros
no window-duration/stride/score tuning flags exist
bundle optionally includes representative-window CSV/JSON/config/plan report
historical runs do not report these as missing
raw/db3/mcap/ply/pcd remain excluded
```

- [ ] **Step 2: Confirm RED in exact-head CI**

- [ ] **Step 3: Wire CLI and bundle**

Use the formal ROS workspace runner because Livox CustomMsg must resolve from the frozen workspace.

- [ ] **Step 4: Document target-machine acceptance boundary**

Verification document must record:

```text
repository implementation = CI-verified
selector science = RAW_SENSOR_ONLY
factory extrinsic baseline remains unchanged
real 623 s greenhouse selection = PENDING
four fresh algorithm runs = PENDING
```

- [ ] **Step 5: Run final exact-head verification**

Required successful steps:

```text
Unit Contracts
Compile Python sources
Shell adapter syntax
Registry smoke
```

- [ ] **Step 6: Stop before real bag execution**

Provide Codex with one acceptance chain that:

```text
creates a fresh selector run
plans four representative windows
validates generated child configs
checks raw-sensor-only provenance and non-overlap
then runs all three algorithms fresh in each selected window
builds coverage/provenance/frame/common-map/Relative-SE3 evidence per window
packages a compact multi-window acceptance report
```

Do not run or merge `main` automatically.
