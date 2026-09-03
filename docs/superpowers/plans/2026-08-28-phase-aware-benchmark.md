# Phase-aware LIO Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline phase-aware LIO diagnostic pipeline that aligns trajectory and resource timelines, labels motion phases from a shared FAST-LIVO2 baseline, supports historical approximate alignment and future strict `/clock` alignment, and exposes the result through `lio-benchmark phase-analysis`.

**Architecture:** Keep analysis, plotting, and runtime time anchoring as separate modules. `phase_analysis.py` consumes standardized CSV trajectories, `bag_analysis.json`, run status, resource histories, and optional clock anchors; `plot_phase_analysis.py` only consumes the resulting JSON; `clock_anchor_recorder.py` is a small ROS 2 process managed by both automatic and manual runners.

**Tech Stack:** Python 3, NumPy, Matplotlib, pytest, ROS 2 Humble/rclpy, rosgraph_msgs/Clock, existing benchmark CLI and shell runner.

**Spec:** `docs/superpowers/specs/2026-08-28-phase-aware-benchmark-design.md`

## Global Constraints

- No independent ground truth means `metric_class=relative-to-baseline/diagnostic/non-ground-truth`; do not emit ATE/RPE or absolute-accuracy claims.
- Time alignment modes are exactly `strict/clock-anchored`, `approximate/lifecycle-aligned`, or `trajectory-only`.
- `/clock` is rosbag recorded/playback time; standardized trajectory time is message header time. Apply `record_minus_header_s` median from `metrics/bag_analysis.json` and preserve evidence.
- Phase priority is exactly `INITIALIZATION > STATIONARY > TURN > HIGH_CURVATURE > STRAIGHT`; `RETURN_NEAR_START` is a tag only.
- Default phase parameters: resample 10 Hz, stationary speed 0.05 m/s, turn yaw rate 8 deg/s, high curvature 0.12 1/m, minimum phase 1.5 s, sustained motion 2.0 s, near-start radius 3.0 m.
- Existing `visualize`, `compare`, and resource-dashboard semantics must remain unchanged.
- Core offline analysis must not require ROS imports.

---

### Task 1: Offline time alignment and phase engine

**Files:**
- Create: `evaluators/phase_analysis.py`
- Create: `tests/test_phase_analysis.py`

**Interfaces:**
- Produces: `piecewise_wall_to_recorded(wall_time_s, anchors)`, `recorded_to_header_offset(bag_analysis, lidar_topic)`, `align_resource_samples(...)`, `build_phases(rows, parameters)`, `compute_phase_trajectory_metrics(...)`, `aggregate_resource_phase(...)`, and `run_phase_analysis(run, baseline, phase_parameters=None)`.

- [ ] **Step 1: Write failing tests** for strict piecewise interpolation, recorded→header median offset, lifecycle fallback, `trajectory-only` downgrade, phase priority, short-fragment merge, trajectory metrics, resource aggregation, health-fail retention, and output contract.
- [ ] **Step 2: Run** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_phase_analysis.py` and confirm RED because `phase_analysis` is missing.
- [ ] **Step 3: Implement minimal pure-Python/NumPy engine** matching the spec, including explicit alignment evidence and warnings.
- [ ] **Step 4: Re-run** the focused test until all tests pass.
- [ ] **Step 5: Commit** with `feat: add offline phase-aware analysis core`.

### Task 2: CLI orchestration

**Files:**
- Modify: `benchmark_base/lio_benchmark/postprocess.py`
- Modify: `benchmark_base/lio_benchmark/entry.py`
- Modify: `tests/test_postprocess.py`
- Modify: `tests/test_entry.py`

**Interfaces:**
- Produces: `lio-benchmark phase-analysis --run <run> --baseline <algorithm> [--phase-param key=value] [--no-plot] [--dry-run]`.

- [ ] **Step 1: Add failing CLI tests** asserting deterministic command expansion and argument forwarding.
- [ ] **Step 2: Run** focused entry/postprocess tests and confirm RED on the unknown command.
- [ ] **Step 3: Add `phase-analysis` dispatch** without changing existing stages.
- [ ] **Step 4: Re-run** focused tests and the existing postprocess/entry suite.
- [ ] **Step 5: Commit** with `feat: expose phase-aware analysis CLI`.

### Task 3: Phase figures

**Files:**
- Create: `evaluators/plot_phase_analysis.py`
- Create: `tests/test_phase_plot.py`

**Interfaces:**
- Consumes: `metrics/phase_analysis.json`.
- Produces: `phase_timeline.png`, `trajectory_error_by_phase.png`, `z_change_by_phase.png`, `cpu_by_phase.png`, `rss_growth_by_phase.png`, and `phase_dashboard.png` under `figures/phase_analysis/`.

- [ ] **Step 1: Add a synthetic JSON plotting test** that expects all six files, including graceful `trajectory-only` resource panels.
- [ ] **Step 2: Run the test** and confirm RED because the plotter is missing.
- [ ] **Step 3: Implement plotting only from JSON**, with no ROS dependency and no recomputation of metrics.
- [ ] **Step 4: Re-run** the plotting test.
- [ ] **Step 5: Commit** with `feat: add phase-aware benchmark figures`.

### Task 4: Strict `/clock` anchor recorder

**Files:**
- Create: `evaluators/clock_anchor_recorder.py`
- Create: `tests/test_clock_anchor_recorder.py`

**Interfaces:**
- Produces: `raw/<algorithm>/clock_anchors.json` containing wall epoch nanoseconds, ISO wall time, ROS time nanoseconds/seconds, sequence, status, and backtrack diagnostics.

- [ ] **Step 1: Add pure helper tests** for anchor serialization and monotonic/backtrack accounting without importing ROS at module import time.
- [ ] **Step 2: Run the focused test** and confirm RED.
- [ ] **Step 3: Implement the recorder**, importing `rclpy`/`rosgraph_msgs.msg.Clock` only in runtime entry code and writing snapshots atomically.
- [ ] **Step 4: Re-run** pure tests; on ROS 2 Humble additionally run a short `/clock` publisher integration test.
- [ ] **Step 5: Commit** with `feat: record wall to ros clock anchors`.

### Task 5: Runner lifecycle integration

**Files:**
- Modify: `evaluators/run_algorithm.sh`
- Modify: `evaluators/manual_run_controller.py`
- Modify: `tests/test_manual_run_controller.py`
- Create: `tests/test_clock_anchor_runner_contract.py`

**Interfaces:**
- Automatic and manual runs must start the clock recorder before bag playback and reliably stop it during cleanup/finalization.

- [ ] **Step 1: Add failing contract/controller tests** that verify recorder creation, output path, and cleanup ownership.
- [ ] **Step 2: Run focused tests** and confirm RED.
- [ ] **Step 3: Integrate recorder lifecycle** into both runners while leaving resource monitoring unchanged.
- [ ] **Step 4: Re-run** controller/contract tests and perform one short ROS smoke run to confirm `strict/clock-anchored` analysis.
- [ ] **Step 5: Commit** with `feat: capture strict clock anchors during runs`.

### Task 6: Historical-run and regression verification

**Files:**
- Modify: `benchmark_base/docs/COMPARISON_VISUALIZATION.md`
- Modify: `benchmark_base/docs/USER_MANUAL_ZH.md`

**Interfaces:**
- Historical run command: `benchmark_base/bin/lio-benchmark phase-analysis --run /home/yangxuan/lio_benchmark_runs/mapping_20260719_172810_full807_round1_001 --baseline fast_livo2`.

- [ ] **Step 1: Run the historical 807 s analysis without replaying the bag** and record whether it resolves to `approximate/lifecycle-aligned` or `trajectory-only` based on actual evidence.
- [ ] **Step 2: Inspect `phase_analysis.json`** for phase parameters, alignment evidence, warnings, health-fail retention, and absence of ATE/RPE.
- [ ] **Step 3: Run focused and regression tests**: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_phase_analysis.py tests/test_phase_plot.py tests/test_postprocess.py tests/test_entry.py tests/test_manual_run_controller.py tests/test_clock_anchor_recorder.py tests/test_clock_anchor_runner_contract.py`.
- [ ] **Step 4: Document the CLI, outputs, and strict-vs-approximate interpretation** without changing existing comparison semantics.
- [ ] **Step 5: Commit** with `docs: document phase-aware benchmark workflow`.
