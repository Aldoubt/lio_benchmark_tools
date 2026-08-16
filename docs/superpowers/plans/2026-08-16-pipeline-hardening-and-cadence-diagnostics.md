# Pipeline Hardening and Cadence Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden one-bag acceptance reporting/provenance semantics, then add read-only cadence/coverage diagnostics that can localize the next real-bag failure without changing estimator or Relative SE(3) science contracts.

**Architecture:** P0 keeps runtime provenance `MATCH` as the implementation-identity gate but adds an orthogonal source/build reproducibility quality dimension and removes stale/ambiguous bundle reporting. P1 adds a ROS-independent cadence analysis core plus a ROS2 evaluator that compares the frozen replay LiDAR window with recorded trajectory output timing. The first new target-machine bag run is the stopping point; no P2 map-intersection changes are started before that evidence is reviewed.

**Tech Stack:** Python 3.10, unittest, ROS 2 Humble evaluator scripts, existing run-local CSV/JSON artifacts, GitHub Actions Core Contracts.

## Global Constraints

- Work only on `feat/lio-baseline-suite`; do not modify or merge `main`.
- Do not change Relative SE(3) V1 math, thresholds, tracked-frame semantics, calibration values, estimator parameters, or trajectory values.
- Formal benchmark source/build/install/run/output paths must not use `/tmp`.
- Existing historical runs remain immutable.
- Runtime provenance `MATCH` continues to mean execution-repository/frame identity match; dirty source is a separate reproducibility warning, not silently promoted to source mismatch.
- Stop before P2 once P1 repository-side diagnostics are green; the next step must be one fresh real-bag acceptance run.

---

### Task 1: P0 reporting consistency

**Files:**
- Modify: `benchmark_base/lib/diagnostic_bundle.py`
- Modify: `benchmark_base/tests/test_diagnostic_bundle.py`
- Modify: `benchmark_base/bin/lio-benchmark-core`
- Modify: `benchmark_base/tests/test_cli_manifest.py`

**Interfaces:**
- Consumes: existing run `manifest.json`, run status JSON, frame/provenance CSV/JSON.
- Produces: deterministic `RUN_STATUS.md` refresh and an unambiguous bundle summary with required vs legacy-optional evidence separated.

- [ ] **Step 1: Write failing bundle-summary tests**

Add tests proving:

```python
self.assertNotIn("metrics/smoke_diagnostics.csv", selection.missing)
self.assertNotIn("metrics/pairwise_disagreement.csv", selection.missing)
self.assertIn("frame evidence: AVAILABLE", summary)
self.assertIn("frame contract: MATCH", summary)
```

The two legacy diagnostics remain included when present but are never reported as required missing evidence.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_diagnostic_bundle -v
```

Expected: failure against the current `always_candidates` and ambiguous `frame audit` summary.

- [ ] **Step 3: Implement required/optional evidence split**

In `diagnostic_bundle.py`, keep required run evidence in `always_candidates`, move old smoke/pairwise diagnostics to an optional-existing-only tuple, and read `frame_contract_status` from `metrics/runtime_provenance.csv` separately from frame audit `status`.

Summary wording becomes:

```text
<algorithm>: runtime identity: FROZEN; runtime provenance: MATCH; frame evidence: AVAILABLE; frame contract: MATCH
```

- [ ] **Step 4: Write failing run-status refresh test**

Add a CLI/unit contract that creates run status JSON for selected algorithms and asserts a helper renders completion state from actual artifacts rather than leaving the initialization template as `pending`.

- [ ] **Step 5: Implement run-status refresh helper/command hook**

Add a small helper in `lio-benchmark-core` that rewrites `RUN_STATUS.md` from immutable evidence after commands that materially advance the run. Minimum fields:

```text
status: active|complete|blocked
frontends: <passed>/<selected>
trajectories: <available>/<selected>
frame audit: AVAILABLE|MISSING
runtime provenance: AVAILABLE|MISSING
relative se3: AVAILABLE|MISSING
bundle: AVAILABLE|MISSING
```

It must not infer scientific accuracy.

- [ ] **Step 6: Run focused and full tests**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_diagnostic_bundle benchmark_base.tests.test_cli_manifest -v
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add benchmark_base/lib/diagnostic_bundle.py benchmark_base/tests/test_diagnostic_bundle.py benchmark_base/bin/lio-benchmark-core benchmark_base/tests/test_cli_manifest.py
git commit -m "fix: align acceptance reporting with current evidence"
```

---

### Task 2: P0 source/build reproducibility quality

**Files:**
- Modify: `benchmark_base/lib/runtime_provenance.py`
- Modify: `benchmark_base/tests/test_runtime_provenance.py`
- Modify: `benchmark_base/lib/diagnostic_bundle.py`
- Modify: `benchmark_base/tests/test_diagnostic_bundle.py`

**Interfaces:**
- Consumes: frozen runtime identity `source.dirty`, source commit, executable fingerprint/mtime.
- Produces: non-blocking `source_reproducibility_status` and `source_reproducibility_reasons` fields in runtime provenance output.

- [ ] **Step 1: Write RED tests for dirty-source quality**

Add tests for frozen identity records:

```python
clean source  -> source_reproducibility_status == "CLEAN_SOURCE"
dirty source  -> source_reproducibility_status == "DIRTY_SOURCE_WARNING"
missing source dirty evidence -> "UNKNOWN_SOURCE_CLEANLINESS"
```

Keep top-level `status == "MATCH"` when repository/frame identity matches. This prevents source cleanliness from silently changing the meaning of runtime provenance.

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_runtime_provenance -v
```

Expected: new fields absent.

- [ ] **Step 3: Implement orthogonal reproducibility classifier**

Add a pure helper returning status/reasons from frozen source evidence, then append:

```text
source_reproducibility_status
source_reproducibility_reasons
```

to `build_runtime_provenance_record()`.

Do not claim binary-to-source rebuild equivalence. A dirty tree is explicitly a warning that the frozen binary hash is exact but source rebuild provenance is not cleanly demonstrated.

- [ ] **Step 4: Surface warnings in diagnostic bundle summary**

When runtime provenance is `MATCH` but source reproducibility is warning/unknown, print it explicitly in `SUMMARY.txt`; do not turn bundle creation into a failure.

- [ ] **Step 5: Run full verification and commit**

Run the full suite/compile/shell checks, then commit:

```bash
git commit -m "feat: expose runtime source reproducibility quality"
```

---

### Task 3: P1 cadence/coverage diagnostic core

**Files:**
- Create: `benchmark_base/lib/trajectory_coverage.py`
- Create: `benchmark_base/tests/test_trajectory_coverage.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class TimestampSeriesStats:
    count: int
    first_s: float
    last_s: float
    duration_s: float
    effective_hz: float | None
    median_period_s: float | None
    p95_period_s: float | None
    max_period_s: float | None
    gap_count_over_1p5x_median: int


def summarize_timestamps(values: Sequence[float]) -> TimestampSeriesStats

def coverage_against_input(input_ts: Sequence[float], output_ts: Sequence[float]) -> dict[str, float | int | None]
```

- [ ] **Step 1: Write RED math tests**

Cover strictly increasing validation, effective Hz, median/P95/max period, large-gap count, first-output lag, last-output lead/lag, and output/input count ratio.

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_trajectory_coverage -v
```

Expected: module missing.

- [ ] **Step 3: Implement the pure diagnostic core**

No ROS imports. Do not classify an algorithm as good/bad from cadence alone. The module only describes timing/coverage evidence.

- [ ] **Step 4: Verify focused tests GREEN**

Run the focused test file and then full suite.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add trajectory cadence diagnostics core"
```

---

### Task 4: P1 run-level cadence evaluator and KISS input-boundary evidence

**Files:**
- Create: `evaluators/audit_trajectory_coverage.py`
- Modify: `evaluators/run_kiss_icp_test.sh`
- Modify: `benchmark_base/bin/lio-benchmark-core`
- Modify: `benchmark_base/lib/diagnostic_bundle.py`
- Create: `benchmark_base/tests/test_trajectory_coverage_cli.py`
- Modify: `benchmark_base/tests/test_execution_contract.py`
- Modify: `benchmark_base/tests/test_diagnostic_bundle.py`

**Interfaces:**
- CLI:

```bash
benchmark_base/bin/lio-benchmark audit trajectory-coverage --run <run> [--algorithms ...]
```

- Output:

```text
metrics/trajectory_coverage.csv
metadata/trajectory_coverage/<algorithm>.json
```

- [ ] **Step 1: Write RED CLI/evidence tests**

Require the new audit command and deterministic output paths. Add a runner-structure test requiring the KISS recorder to include the converter output topic `/lio_benchmark/kiss_icp_points` in the same run-local raw bag used for diagnostics.

- [ ] **Step 2: Verify RED**

Run the new CLI test and execution-contract tests; expect failure because the command and input evidence are absent.

- [ ] **Step 3: Record KISS converter output without changing estimator input**

Extend KISS `ros2 bag record` topics to include:

```text
/lio_benchmark/kiss_icp_points
```

This is diagnostic evidence only; the estimator already consumes that topic. Do not change conversion, QoS, filtering, timestamps, estimator launch arguments, or replay timing in this task.

- [ ] **Step 4: Implement run-level audit evaluator**

For each algorithm, use the frozen replay window and run-local artifacts to report:

```text
input_lidar_count
input_lidar_effective_hz
adapter_output_count (KISS when recorded)
adapter_output_effective_hz
trajectory_count
trajectory_effective_hz
trajectory_median_period_s
trajectory_p95_period_s
trajectory_max_period_s
first_trajectory_lag_from_input_s
last_trajectory_delta_to_input_end_s
trajectory_to_input_count_ratio
adapter_to_input_count_ratio
trajectory_to_adapter_count_ratio
```

Input LiDAR timestamps come from the frozen dataset bag/replay window. KISS adapter-output timestamps come from the newly recorded PointCloud2 topic. Other algorithms may leave adapter fields null because no equivalent adapter boundary is present.

- [ ] **Step 5: Add bundle inclusion**

Include coverage CSV/JSON when present; absence remains optional for historical runs.

- [ ] **Step 6: Full repository verification**

Run:

```bash
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

- [ ] **Step 7: Commit and exact-head CI**

```bash
git commit -m "feat: audit trajectory input and output coverage"
```

Wait for exact-head `Core Contracts` success.

---

### Task 5: Stop for the next real-bag acceptance

**No P2 code changes in this task.**

After Tasks 1–4 are green, stop and request one fresh bag run. The next acceptance must additionally execute:

```bash
benchmark_base/bin/lio-benchmark audit trajectory-coverage \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp
```

The evidence should let us distinguish at least these boundaries for KISS:

```text
source bag LiDAR count/rate
  -> CustomMsg-to-PointCloud2 adapter count/rate
  -> KISS odometry count/rate
```

Only after this fresh run do we decide whether the 7.48 Hz observation is input conversion loss, estimator publication behavior, recorder/lifecycle behavior, or a normal algorithm cadence. P2 strict common matched-scan intersection starts only after that diagnosis.
