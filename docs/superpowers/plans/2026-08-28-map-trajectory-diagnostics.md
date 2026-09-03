# Map + Trajectory Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quantify map consistency and timestamp trajectory discontinuities for the current LIO run while preserving diagnostic/non-ground-truth semantics.

**Architecture:** Add one pure map-consistency module consumed by the existing map enhancement stage, plus one ROS-free trajectory-discontinuity stage consuming standardized CSVs. Integrate both into current-run reporting and the existing `compare` orchestration. The future interactive frontend is deferred but receives stable CSV/JSON artifacts from this work.

**Tech Stack:** Python 3.10, NumPy, SciPy `cKDTree`, Matplotlib, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-map-trajectory-diagnostics-design.md`

## Global Constraints

- No independent ground truth; baseline-relative quantities remain diagnostic/non-ground-truth.
- Do not replay any LIO algorithm.
- Keep trajectory health and map health separate.
- Deterministic bounded sampling for nearest-neighbour map metrics.
- `*_all` map figures retain failed/crashed partial maps.
- Discontinuity events are not automatic trajectory-health failures.

---

### Task 1: Pure map-consistency metrics

**Files:**
- Create: `evaluators/map_consistency.py`
- Create: `tests/test_map_consistency.py`

**Interfaces:**
- `robust_extent_xyz(cloud, low_percentile=1.0, high_percentile=99.0) -> np.ndarray`
- `voxel_iou(reference, candidate, voxel_m) -> float`
- `symmetric_nn_metrics(reference, candidate, max_points=50000) -> dict`
- `map_health_flags(candidate_metrics, baseline_metrics) -> list[str]`

- [ ] Write tests covering outlier-resistant extent, identical/disjoint voxel IoU, symmetric NN distance and conservative health flags.
- [ ] Verify the tests fail before implementation.
- [ ] Implement deterministic metric helpers.
- [ ] Verify focused tests pass.
- [ ] Commit.

### Task 2: Map comparison integration and map-health gating

**Files:**
- Modify: `evaluators/enhance_map_comparison.py`
- Modify: `tests/test_map_comparison_enhancement.py`

**Interfaces:**
- `build_metrics(..., baseline: str, comparison_voxel_m: float) -> dict`
- `choose_map_sets(..., map_metrics=None) -> (primary, all)`

- [ ] Add failing tests that map-health-fail algorithms leave primary figures but remain in `*_all`.
- [ ] Extend map metrics with robust extent, IoU, symmetric NN metrics, map-health flags/pass and thresholds metadata.
- [ ] Keep raw extent for audit.
- [ ] Verify focused tests pass.
- [ ] Commit.

### Task 3: Timestamped trajectory discontinuity diagnostics

**Files:**
- Create: `evaluators/trajectory_discontinuity.py`
- Create: `tests/test_trajectory_discontinuity.py`

**Interfaces:**
- `step_series(trajectory, origin_timestamp_s) -> dict[str, np.ndarray]`
- `robust_jump_threshold(values, floor) -> float`
- `summarize_discontinuities(algorithm, trajectory, origin_timestamp_s) -> dict`

- [ ] Add tests for position jumps, yaw unwrap/no false wrap jump, threshold floors and timestamped event schema.
- [ ] Implement ROS-free per-step metrics, CSV output, JSON/Markdown summary and two timeline figures.
- [ ] Verify focused tests pass.
- [ ] Commit.

### Task 4: Report and postprocess integration

**Files:**
- Modify: `evaluators/current_run_report.py`
- Modify: `benchmark_base/lio_benchmark/postprocess.py`
- Modify: `tests/test_current_run_report.py`
- Modify: `tests/test_postprocess.py`

**Interfaces:**
- current report consumes `map_comparison_metrics.json` and `metrics/trajectory_discontinuity.json` when present.
- `compare` and `visualize` invoke `trajectory_discontinuity.py` before `current_run_report.py`.

- [ ] Add failing report/postprocess tests.
- [ ] Make map-health failure affect `recommendation_eligible` only when map evidence exists.
- [ ] Expose map health and discontinuity counts/maxima in JSON/Markdown/CSV.
- [ ] Add discontinuity stage to orchestration.
- [ ] Verify focused tests pass.
- [ ] Commit.

### Task 5: Verification/docs contract

**Files:**
- Modify: `evaluators/check_phase_pipeline.sh`
- Modify: `benchmark_base/docs/COMPARISON_VISUALIZATION.md`

- [ ] Add new modules/tests to static/self-check.
- [ ] Document quantitative map metrics, discontinuity outputs and future frontend contract.
- [ ] Run `bash evaluators/check_phase_pipeline.sh` on the Ubuntu benchmark host.
- [ ] Run `git diff --check`.
- [ ] Re-run `compare --with-maps` on `greenhouse_full623_round1_001` without rerunning algorithms.
- [ ] Inspect Point-LIO/FAST/LIO-SAM/GLIM/KISS/MOLA/DLIO metrics and anomaly plots before any Round2 tuning.
