# Trajectory From Run Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `lio-benchmark standardize trajectory-from-run` so a frozen run can convert its own raw ROS 2 trajectory bag into the existing standardized trajectory CSV contract without manual CSV conversion.

**Architecture:** Extract ROS 2 bag/topic/pose reading from `audit_trajectory_frames.py` into one shared ROS-dependent module. Keep pose-to-standardized-trajectory conversion in a ROS-independent helper so CI can test scientific invariants without ROS. Add a dedicated evaluator and CLI entry point; keep frame audit read-only and make it consume the same shared reader.

**Tech Stack:** Python 3.10, ROS 2 Humble `rosbag2_py`, `rclpy.serialization`, `rosidl_runtime_py`, existing `PoseSample` / `Trajectory` contract, `unittest`, GitHub Actions.

## Global Constraints

- The command is `lio-benchmark standardize trajectory-from-run --run <run> --algorithm <algorithm_id>`.
- It only changes representation: no tracked-frame conversion, world-gauge normalization, display alignment, calibration transform, interpolation, resampling, warm-up trim, or scoring.
- Supported raw pose types are `nav_msgs/msg/Odometry`, `geometry_msgs/msg/PoseStamped`, and `geometry_msgs/msg/PoseWithCovarianceStamped`.
- Timestamp policy is `HEADER_STAMP_ELSE_BAG_RECORD_TIME`.
- Search only under `raw/<algorithm>/`; zero or multiple matching bags fail closed.
- Output is `standardized/trajectories/<algorithm>.csv` using the existing standard columns.
- Metadata is `metadata/algorithms/<algorithm>/trajectory_standardization.json`.
- Existing standardized trajectory output is never silently overwritten; this phase has no `--overwrite` option.
- `audit trajectory-frames` remains read-only and shares the same ROS bag reader.

---

### Task 1: ROS-independent pose conversion contract

**Files:**
- Create: `benchmark_base/lib/trajectory_from_run.py`
- Create: `benchmark_base/tests/test_trajectory_from_run.py`

**Interfaces:**
- Consumes: `benchmark_base.lib.frame_audit.RawPoseObservation`, `benchmark_base.lib.trajectory.PoseSample`, `Trajectory`, `normalize_quaternion`, `rpy_from_quaternion`.
- Produces: `trajectory_from_observations(observations, source_topic) -> Trajectory` and `build_trajectory_standardization_metadata(...) -> dict[str, Any]`.

- [ ] **Step 1: Write failing conversion tests**

Cover quaternion normalization, unchanged XYZ, derived RPY, preserved `source_topic`, non-monotonic timestamp rejection, and metadata fields.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_trajectory_from_run -v
```

Expected: failure because `benchmark_base.lib.trajectory_from_run` does not exist.

- [ ] **Step 3: Implement the minimal pure helper**

Use each `RawPoseObservation.timestamp_s/x/y/z/q*` directly, normalize only the quaternion, derive RPY from that normalized quaternion, build `PoseSample`, and construct `Trajectory` so existing finite/strict-monotonic validation remains authoritative.

Metadata builder must emit schema version 1, algorithm ID, `RUN_LOCAL_ROS2_BAG`, source bag/topic/type, timestamp policy, sample count, first/last timestamps, and run-relative output path.

- [ ] **Step 4: Re-run focused tests and verify GREEN**

```bash
python3 -m unittest benchmark_base.tests.test_trajectory_from_run -v
```

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/trajectory_from_run.py benchmark_base/tests/test_trajectory_from_run.py
git commit -m "feat: add run trajectory conversion contract"
```

---

### Task 2: Shared ROS 2 trajectory bag reader

**Files:**
- Create: `benchmark_base/lib/rosbag_trajectory.py`
- Modify: `evaluators/audit_trajectory_frames.py`

**Interfaces:**
- Produces: `normalize_topic`, `storage_identifier`, `open_reader`, `topic_map`, `find_bag_for_topic`, `stamp_seconds`, `pose_fields`, `read_pose_observations`.
- `read_pose_observations(...) -> tuple[RawPoseObservation, ...]`.

- [ ] **Step 1: Add a structural regression test**

Extend `test_trajectory_from_run.py` to read `audit_trajectory_frames.py` as text and assert it imports the shared reader and no longer defines its own `open_reader`, `find_bag_for_topic`, or `read_observations` implementation.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
python3 -m unittest benchmark_base.tests.test_trajectory_from_run -v
```

Expected: structural test fails because audit still owns those helpers.

- [ ] **Step 3: Extract the existing proven ROS bag logic**

Move the existing topic normalization, storage detection, reader creation, topic discovery, bag selection, timestamp extraction, supported pose-message extraction, and observation creation into `benchmark_base/lib/rosbag_trajectory.py` without changing semantics.

Update frame audit to import and call the shared functions. Preserve frame audit output and failure semantics.

- [ ] **Step 4: Run focused tests and syntax/compile checks**

```bash
python3 -m unittest benchmark_base.tests.test_trajectory_from_run -v
python3 -m compileall -q benchmark_base evaluators
```

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/rosbag_trajectory.py evaluators/audit_trajectory_frames.py benchmark_base/tests/test_trajectory_from_run.py
git commit -m "refactor: share ROS bag trajectory reader"
```

---

### Task 3: Run-local trajectory standardizer evaluator

**Files:**
- Create: `evaluators/standardize_trajectory_from_run.py`
- Modify: `benchmark_base/tests/test_trajectory_from_run.py`

**Interfaces:**
- CLI: `standardize_trajectory_from_run.py --run <path> --algorithm <id>`.
- Uses frozen `manifest.json`, shared ROS bag reader, and pure conversion helper.
- Writes standardized CSV and metadata artifact exactly once.

- [ ] **Step 1: Write evaluator contract tests that do not require ROS runtime**

Test source-topic resolution from frozen algorithm contract, output/metadata path construction, and refusal when the standardized output already exists. Keep ROS bag IO behind functions that the test can avoid importing/executing directly.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python3 -m unittest benchmark_base.tests.test_trajectory_from_run -v
```

Expected: failure because the evaluator/helper interface is missing.

- [ ] **Step 3: Implement evaluator**

Processing order:

```text
load frozen manifest
→ validate selected algorithm
→ resolve frozen trajectory output topic
→ refuse existing standardized output
→ find exactly one raw bag containing the topic
→ read supported pose observations
→ convert to Trajectory
→ write standardized CSV
→ write trajectory_standardization.json
→ print metadata JSON/path summary
```

Use atomic-ish ordering: validate everything first, write CSV, then metadata. On failure never synthesize an empty result or PASS status.

- [ ] **Step 4: Re-run focused tests**

```bash
python3 -m unittest benchmark_base.tests.test_trajectory_from_run -v
```

- [ ] **Step 5: Commit**

```bash
git add evaluators/standardize_trajectory_from_run.py benchmark_base/tests/test_trajectory_from_run.py
git commit -m "feat: standardize trajectory from run-local rosbag"
```

---

### Task 4: Main CLI integration and diagnostic bundle coverage

**Files:**
- Modify: `benchmark_base/bin/lio-benchmark`
- Modify: `benchmark_base/tests/test_cli_manifest.py`
- Modify: `benchmark_base/lib/diagnostic_bundle.py`
- Modify: `benchmark_base/tests/test_diagnostic_bundle.py`

**Interfaces:**
- Adds parser node `standardize trajectory-from-run` with required `--run` and `--algorithm` only.
- Runs evaluator through `run_python_ros(...)` so ROS workspace overlays are available.
- Minimal bundle includes `metadata/algorithms/<algorithm>/trajectory_standardization.json` when present.

- [ ] **Step 1: Write CLI and bundle RED tests**

Assert help contains `--run`/`--algorithm` and no `--overwrite`. Assert the minimal diagnostic bundle includes trajectory-standardization metadata for dynamically discovered algorithms.

- [ ] **Step 2: Verify RED**

```bash
python3 -m unittest benchmark_base.tests.test_cli_manifest benchmark_base.tests.test_diagnostic_bundle -v
```

- [ ] **Step 3: Implement CLI dispatch and bundle inclusion**

Add `cmd_standardize_trajectory_from_run`, calling `run_python_ros(run, manifest, "evaluators/standardize_trajectory_from_run.py", ["--run", str(run), "--algorithm", args.algorithm])`.

- [ ] **Step 4: Verify GREEN**

```bash
python3 -m unittest benchmark_base.tests.test_cli_manifest benchmark_base.tests.test_diagnostic_bundle -v
```

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/bin/lio-benchmark benchmark_base/tests/test_cli_manifest.py benchmark_base/lib/diagnostic_bundle.py benchmark_base/tests/test_diagnostic_bundle.py
git commit -m "feat: expose trajectory-from-run CLI"
```

---

### Task 5: Workflow docs and fresh repository verification

**Files:**
- Modify: `benchmark_base/docs/V2_WORKFLOW.md`
- Modify: `README.md`
- Create: `docs/verification/trajectory_from_run_verification.md`

**Interfaces:**
- Documents the fresh three-algorithm smoke order and explicitly labels target-machine ROS integration as pending until run artifacts prove it.

- [ ] **Step 1: Update workflow docs**

Document:

```bash
for ALG in fast_livo2 fast_lio2 kiss_icp; do
  benchmark_base/bin/lio-benchmark standardize trajectory-from-run \
    --run "$RUN" --algorithm "$ALG"
done
```

Place it between algorithm execution and trajectory-frame audit.

- [ ] **Step 2: Add verification note**

Record repository-side contract coverage separately from target-machine integration status. Do not claim real-bag PASS until a new run has been executed.

- [ ] **Step 3: Run fresh full verification on the final HEAD**

```bash
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 benchmark_base/bin/lio-benchmark list algorithms >/dev/null
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit docs/verification**

```bash
git add README.md benchmark_base/docs/V2_WORKFLOW.md docs/verification/trajectory_from_run_verification.md
git commit -m "docs: add trajectory-from-run smoke workflow"
```

- [ ] **Step 5: Re-run the same full verification on the documentation commit**

Do not report repository-side completion until this final fresh verification is green.
