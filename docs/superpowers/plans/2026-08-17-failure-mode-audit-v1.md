# Failure-Mode Audit V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only batch audit that compares trajectory coverage-degradation timing with existing Relative SE(3) sustained descriptive onsets for the accepted Representative Window V1 runs.

**Architecture:** Put all scientific/event logic in a ROS-independent `benchmark_base.lib.failure_mode_audit` module. A thin evaluator writes the immutable audit directory, and the public CLI invokes it directly without resolving a ROS workspace. Existing child-run coverage, standardized trajectories, and Relative SE(3) artifacts are read-only inputs; no source bag or estimator process is touched.

**Tech Stack:** Python 3.10 standard library, existing unittest suite, existing `lio-benchmark` argparse dispatcher, GitHub Actions Core Contracts.

## Global Constraints

- Branch starts from `feat/lio-baseline-suite@55c103821bb8b20181524b0bcbaaf853325b16fc`.
- Do not replay or scan the full 623 s greenhouse bag.
- Do not rerun FAST-LIVO2, FAST-LIO2, or KISS-ICP.
- Do not recompute existing Relative SE(3) outputs.
- Do not mutate any Representative Window V1 child run.
- Preserve `DESCRIPTIVE_NO_GROUND_TRUTH`; never claim failure time, causal drift onset, accuracy, or ranking.
- Reuse the existing `1.5 x median period` large-gap semantics; expose no V1 tuning flag.
- Resolve exactly four Representative Window V1 child runs from one batch ID.
- Refuse to overwrite an existing Failure-Mode Audit V1 output directory.

---

### Task 1: Pure failure-mode event and relation contracts

**Files:**
- Create: `benchmark_base/tests/test_failure_mode_audit.py`
- Create: `benchmark_base/lib/failure_mode_audit.py`

**Interfaces:**
- Consumes: existing coverage CSV rows, standardized trajectory CSV timestamps, Relative SE(3) metadata and onset CSV rows.
- Produces: `extract_coverage_events(...)`, `relate_onsets_to_coverage(...)`, and `audit_batch(...)` with deterministic CSV/JSON/report records.

- [ ] **Step 1: Write failing unit tests**

Cover these exact behaviors:

```python
# input-relative degradation uses the frozen 1.5x input median criterion
# onset time is previous trajectory timestamp + threshold
# non-increasing trajectory timestamps fail closed
# crossed Relative SE(3) onsets are related to first/nearest before/nearest after gaps
# NO_COVERAGE_DEGRADATION_EVENT and NO_CROSSED_RELATIVE_SE3_ONSET are explicit
# four child runs are required
# existing output directory is refused
# source evidence files are SHA-256 fingerprinted
# target summaries are produced only for high_angular_motion/kiss_icp and
# steady_translation_candidate/fast_livo2
```

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
python3 -m unittest benchmark_base.tests.test_failure_mode_audit -v
```

Expected: import/module failure because `benchmark_base.lib.failure_mode_audit` does not yet exist.

- [ ] **Step 3: Implement the minimal pure module**

Required constants:

```python
SCHEMA = "lio_benchmark_failure_mode_audit/v1"
GAP_MULTIPLIER = 1.5
WINDOW_LABELS = (
    "initialization",
    "high_angular_motion",
    "geometric_degeneracy_candidate",
    "steady_translation_candidate",
)
EXPECTED_ALGORITHMS = ("fast_livo2", "fast_lio2", "kiss_icp")
TARGET_CASES = (
    ("high_angular_motion", "kiss_icp"),
    ("steady_translation_candidate", "fast_livo2"),
)
```

The module must use only standard-library imports and must never import ROS packages. It must validate every source artifact before creating the output directory, then write atomically into a newly created immutable directory.

- [ ] **Step 4: Run the focused test and confirm GREEN**

```bash
python3 -m unittest benchmark_base.tests.test_failure_mode_audit -v
```

Expected: all focused tests PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/failure_mode_audit.py benchmark_base/tests/test_failure_mode_audit.py
git commit -m "feat: add failure-mode audit core"
```

---

### Task 2: Public evaluator and CLI contract

**Files:**
- Create: `evaluators/audit_failure_modes.py`
- Create: `benchmark_base/tests/test_failure_mode_audit_cli.py`
- Modify: `benchmark_base/bin/lio-benchmark`

**Interfaces:**
- Consumes: `audit_batch(run_root: Path, batch_id: str) -> Path` from Task 1.
- Produces: `lio-benchmark audit failure-mode --run-root <path> --batch-id <id>`.

- [ ] **Step 1: Write failing CLI tests**

Require:

```text
audit failure-mode
--run-root required
--batch-id required
no threshold/window tuning flags
direct Python evaluator invocation
no _core.resolve_run
no _core.run_python_ros
```

Also assert the evaluator source does not import `rclpy`, `rosbag2_py`, or any bag-reading helper.

- [ ] **Step 2: Run the focused CLI test and confirm RED**

```bash
python3 -m unittest benchmark_base.tests.test_failure_mode_audit_cli -v
```

Expected: parser/handler missing.

- [ ] **Step 3: Add the evaluator and minimal CLI wiring**

Evaluator arguments:

```text
--run-root PATH
--batch-id STRING
```

Handler command shape:

```python
[
    sys.executable,
    str(MODULE_ROOT / "evaluators/audit_failure_modes.py"),
    "--run-root", str(args.run_root),
    "--batch-id", args.batch_id,
]
```

Return the subprocess return code. Do not source a ROS workspace.

- [ ] **Step 4: Run focused CLI tests and core unit tests**

```bash
python3 -m unittest \
  benchmark_base.tests.test_failure_mode_audit \
  benchmark_base.tests.test_failure_mode_audit_cli -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluators/audit_failure_modes.py benchmark_base/bin/lio-benchmark benchmark_base/tests/test_failure_mode_audit_cli.py
git commit -m "feat: expose failure-mode audit cli"
```

---

### Task 3: Repository verification and scientific contract documentation

**Files:**
- Create: `docs/verification/failure_mode_audit_v1_verification.md`

**Interfaces:**
- Consumes: implementation and CI evidence from Tasks 1-2.
- Produces: exact target-machine acceptance command and unclaimed PENDING state.

- [ ] **Step 1: Run the repository contract suite**

```bash
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 benchmark_base/bin/lio-benchmark list algorithms
```

Expected: zero failures/errors and exit status 0 for every command.

- [ ] **Step 2: Record repository verification**

Document exact implementation HEAD and exact successful Core Contracts workflow run. Keep target-machine acceptance `PENDING`; repository CI has no access to the four real child-run directories.

- [ ] **Step 3: Freeze the target-machine command**

```bash
cd ~/lio_benchmark_tools
git switch feat/lio-baseline-suite
git pull --ff-only

python3 benchmark_base/bin/lio-benchmark audit failure-mode \
  --run-root /home/yangxuan/lio_benchmark_runs/green_house \
  --batch-id repv1_final_20260817_133745
```

No bag replay or estimator command is part of acceptance.

- [ ] **Step 4: Freeze target acceptance checks**

Verify the new audit directory contains exactly the expected six artifacts, both target rows exist, all four child labels occur in `coverage_context.csv`, fingerprints resolve to the existing child evidence, and the Markdown report states `DESCRIPTIVE_NO_GROUND_TRUTH` plus measured signed timing deltas.

- [ ] **Step 5: Commit documentation**

```bash
git add docs/verification/failure_mode_audit_v1_verification.md
git commit -m "docs: add failure-mode audit verification"
```

Stop here. Do not start another benchmark, estimator rerun, or full-bag replay.
