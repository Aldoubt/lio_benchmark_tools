# Frozen Native Rerun Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and register `viewer/diagnostic.rrd` inside an INCOMPLETE frozen experiment by reusing the stable Native Rerun recording builder, while treating map/LiDAR evidence as optional and bounded.

**Architecture:** Add a focused `evaluators/freeze_rerun.py` adapter around `rerun_diagnostic_viewer.log_recording`. The adapter reads freeze provenance, preflights optional point-cloud source access, chooses bounded Native recording options, saves the `.rrd` inside the frozen bundle, records the Rerun SDK/evidence policy in the freeze manifest, and registers the generated artifact through the freeze-core API. It does not finalize the bundle; report generation remains required before the final `COMPLETE` promotion.

**Tech Stack:** Python 3.10 stdlib, existing `rerun-sdk==0.36.3` Native viewer path, NumPy/ROS dependencies only when optional indexed LiDAR evidence is actually enabled, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-native-freeze-export-design.md`

## Global Constraints

- Native Rerun remains the formal interactive diagnosis path; WebViewer is experimental.
- Reuse `evaluators/rerun_diagnostic_viewer.py`; do not create a second recorder implementation.
- Do not replay algorithms or silently enable unbounded full-bag point-cloud logging.
- Default point-cloud evidence is anomaly-near when indexed source access is usable; otherwise omit it and disclose why.
- Missing optional map/LiDAR evidence must not invalidate an otherwise valid trajectory/resource/anomaly recording.
- The output path is exactly `viewer/diagnostic.rrd` inside the frozen bundle.
- Register the `.rrd` hash through `register_generated_artifact`; do not call `finalize_freeze` in this plan.
- Preserve `relative-to-baseline/diagnostic/non-ground-truth` semantics.

---

### Task 1: Optional point-cloud source preflight

**Files:**
- Create: `evaluators/freeze_rerun.py`
- Create: `tests/test_freeze_rerun.py`

**Interfaces:**
- Produces: `pointcloud_source_status(run: Path) -> dict[str, Any]`
- Result keys: `available: bool`, `reason: str | None`, `index_path: str | None`, `sqlite_db: str | None`.

- [ ] **Step 1: Write failing tests** for absent index, malformed index, missing SQLite DB, unusable ROS message runtime, and usable index.
- [ ] **Step 2: Run** `PYTHONPATH="$PWD/evaluators:$PWD/benchmark_base" python3 -m pytest -q tests/test_freeze_rerun.py` and verify import/name failure.
- [ ] **Step 3: Implement minimal preflight.** Require `metrics/pointcloud_frame_index.json` to be a JSON object with non-empty `sqlite_db`, `lidar_topic`, and `lidar_type`; resolve relative SQLite paths against the source run; require the DB to be a file, and preflight the ROS message runtime for the indexed `lidar_type`. Return a disclosure reason instead of raising for these optional-evidence failures.
- [ ] **Step 4: Re-run focused tests** and verify green.
- [ ] **Step 5: Commit** `feat: preflight frozen rerun pointcloud evidence`.

---

### Task 2: Build and register bounded Native recording

**Files:**
- Modify: `evaluators/freeze_rerun.py`
- Modify: `tests/test_freeze_rerun.py`

**Interfaces:**
- Consumes: `register_generated_artifact(...)`, `write_json_atomic(...)`, `rerun_diagnostic_viewer.log_recording(...)`, `parse_point_lods(DEFAULT_POINT_LODS)`.
- Produces: `build_frozen_rerun(frozen: Path) -> dict[str, Any]`.

- [ ] **Step 1: Write failing tests** using a monkeypatched recording builder that captures arguments and writes a deterministic fake `.rrd`.
  - no point-cloud source -> `pointcloud_mode="none"`, `world_pointcloud_mode="none"`;
  - usable point-cloud source -> both modes `"anomaly"`;
  - `spawn=False`, `save=<frozen>/viewer/diagnostic.rrd`, algorithms/baseline/language come from `freeze_manifest.json`;
  - output is registered with role `native_rerun_recording` and the freeze stays `INCOMPLETE`;
  - builder that returns without creating the file raises `RuntimeError`, records a `viewer/diagnostic.rrd` failure stage, and does not register it.
- [ ] **Step 2: Run focused tests** and verify RED.
- [ ] **Step 3: Implement `build_frozen_rerun`.** Require an INCOMPLETE manifest, source run path, non-empty algorithms, baseline and language; preflight point-cloud evidence; call the stable Native builder with `with_maps=True`, `map_point_step=4`, `pointcloud_period_s=1.0`, `point_step=20`, `point_lods=parse_point_lods(DEFAULT_POINT_LODS)`, baseline as the default world algorithm, `spawn=False`, and `save` set to the frozen `.rrd` path. Never use a sampled/full-bag default.
- [ ] **Step 4: After the builder succeeds**, explicitly `rr.flush()` and `rr.disconnect()` so the file sink is finalized before hashing; then require the `.rrd` file, register it, and atomically add `rerun_recording` metadata to `freeze_manifest.json` containing SDK version, optional-evidence decisions, omission reason, and the builder summary. Keep `freeze_state="INCOMPLETE"`.
- [ ] **Step 5: Run focused tests** and verify green.
- [ ] **Step 6: Run freeze-core regression** together with the new tests.
- [ ] **Step 7: Commit** `feat: generate frozen native rerun recording`.

---

### Task 3: Native viewer compatibility regression

**Files:**
- Modify: `tests/test_freeze_rerun.py` only if an integration seam is needed.

**Interfaces:**
- Verifies: the adapter calls the existing `log_recording` contract without changing Native viewer semantics.

- [ ] **Step 1: Run** `tests/test_rerun_diagnostic_viewer.py`, `tests/test_freeze_experiment.py`, and `tests/test_freeze_rerun.py` in an environment containing repository dependencies.
- [ ] **Step 2: If `rerun-sdk==0.36.3` is installed**, generate one real minimal `.rrd` from a completed source run and verify it is non-empty and registered. If the SDK/runtime is unavailable, record that as an environment verification limitation rather than replacing the test with a Web path.
- [ ] **Step 3: Commit only if fixes are needed.**

## Plan Self-Review

- **Spec coverage:** implements section 9 frozen Native Rerun recording and its bounded optional-evidence behavior; deliberately leaves report data/evidence, HTML/PDF, `open`, `export`, and final `freeze` CLI to later plans.
- **No duplicate recorder:** all recording semantics stay in `rerun_diagnostic_viewer.log_recording`.
- **Lifecycle:** generated `.rrd` is registered but does not promote the bundle to `COMPLETE` prematurely.
- **Verification limitation:** a real `.rrd` requires the Rerun SDK and, for indexed raw/world LiDAR, ROS message dependencies; unit tests isolate orchestration from those runtime dependencies.
