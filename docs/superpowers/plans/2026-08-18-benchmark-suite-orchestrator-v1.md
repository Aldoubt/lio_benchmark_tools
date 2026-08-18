# Benchmark Suite Orchestrator V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one fail-closed, artifact-derived, resumable `SAME_BAG_MAPPING_V1` orchestration surface that executes the accepted Same-Bag command chain without rerunning any estimator after runtime identity has been frozen.

**Architecture:** Build an immutable suite plan, derive every stage state from canonical run artifacts, record only append-only operational events, and execute stages through the existing public benchmark commands. Keep all status/plan/event logic ROS-independent so GitHub Actions can verify the orchestration contracts without a target ROS environment; target-machine acceptance proves the real 45 s three-estimator interruption/resume path.

**Tech Stack:** Python 3.10, stdlib `argparse`/`json`/`hashlib`/`fcntl`/`signal`/`subprocess`/`uuid`, existing `unittest` Core Contracts, existing benchmark CLI/evaluators, ROS 2 Humble only on target-machine execution paths.

**Spec:** `docs/superpowers/specs/2026-08-18-benchmark-suite-orchestrator-v1-design.md`

## Global Constraints

- Branch: `feat/lio-baseline-suite`.
- Strict RED -> GREEN for every task; do not combine an unverified RED/GREEN pair with unrelated work.
- V1 profile is exactly `SAME_BAG_MAPPING_V1`.
- Initial accepted algorithm set/order is frozen by the run manifest; target acceptance uses `fast_livo2`, `fast_lio2`, `kiss_icp` in that order.
- No invocation-time algorithm/replay/calibration/topic/map/tolerance overrides.
- No `--force`, `--overwrite`, `--skip`, `--jobs`, `--parallel`, `--ignore-failure`, or `--rerun-algorithm`.
- No estimator or post-processing parallelism.
- Artifact state is authoritative; event history never overrides artifact validation.
- Existing canonical scientific artifacts are never automatically deleted, repaired, replaced, or overwritten.
- `runtime_identity.json` existence makes that estimator non-rerunnable inside the same run.
- `FAIL_ALGORITHM` is terminal for that estimator/run; retry requires a new run ID.
- Independent ready estimator attempts continue after another estimator fails; comparison-wide downstream stages remain blocked rather than shrinking the frozen algorithm set.
- Dataset identity must be a valid frozen 64-hex SHA-256 and is checked once before and once after the sequential estimator group.
- Raw frame-audit `AVAILABLE` must not be confused with semantic runtime-provenance `MATCH`.
- Trajectory-coverage success means valid descriptive evidence only; do not add quality thresholds.
- `suite status` must be strictly read-only.
- First SIGINT/SIGTERM requests stage-boundary stop: the active child stage finishes, no new stage starts, then the suite exits 130/143.
- P2 does not add Point-LIO, DLIO, Leg-KILO, LIO-SAM, GLIM, report/demo/README work, multi-bag orchestration, repeated trials, or ground-truth metrics.

---

## File Structure

Create:

- `benchmark_base/lib/suite_plan.py` — fixed stage graph, scheduling priority, immutable plan schema/build/validation.
- `benchmark_base/lib/suite_status.py` — ROS-independent artifact ownership/validation and derived stage/suite state.
- `benchmark_base/lib/suite_events.py` — append-only event ledger and non-authoritative active invocation reading.
- `benchmark_base/lib/suite_orchestrator.py` — exclusive executor lock, stage dispatch, failure policy, graceful stop, run/resume engine.
- `benchmark_base/tests/suite_test_utils.py` — small temporary-run builders for pure orchestration contract tests.
- `benchmark_base/tests/test_suite_plan.py`.
- `benchmark_base/tests/test_suite_status.py`.
- `benchmark_base/tests/test_suite_events.py`.
- `benchmark_base/tests/test_suite_identity.py`.
- `benchmark_base/tests/test_suite_orchestrator.py`.
- `benchmark_base/tests/test_suite_cli.py`.
- `docs/verification/benchmark_suite_orchestrator_v1_verification.md`.

Modify:

- `benchmark_base/bin/lio-benchmark-core` — extract reusable `initialize_run(config: Path, run_id: str | None) -> Path` without changing historical `init` semantics.
- `benchmark_base/bin/lio-benchmark` — expose `suite run`, `suite status`, and `suite resume` only.

Do not modify estimator adapters, registry algorithm definitions, map/trajectory scientific algorithms, or Same-Bag summary semantics unless a repository test exposes an implementation bug that directly prevents the frozen P2 contract; any such change requires its own RED first.

---

### Task 1: Immutable Suite Plan and Fixed DAG

**Files:**
- Create: `benchmark_base/lib/suite_plan.py`
- Create: `benchmark_base/tests/suite_test_utils.py`
- Create: `benchmark_base/tests/test_suite_plan.py`

**Interfaces:**
- Produces: `StageDefinition(stage_id: str, dependencies: tuple[str, ...], recovery_policy: str, priority: int)`.
- Produces: `build_stage_definitions(algorithm_ids: list[str]) -> tuple[StageDefinition, ...]`.
- Produces: `build_suite_plan(run: Path, manifest: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]`.
- Produces: `write_suite_plan(run: Path, payload: dict[str, Any]) -> Path` with exclusive-create/no-overwrite semantics.
- Produces: `load_and_validate_suite_plan(run: Path) -> dict[str, Any]`.
- Produces: `validate_suite_plan_payload(payload: dict[str, Any]) -> None`.
- Produces: `validate_manifest_fingerprint(run: Path, plan: dict[str, Any]) -> None`.
- Produces: constants `SUITE_PLAN_SCHEMA`, `SUITE_PROFILE`, recovery-policy strings, and stable stage ordering.

- [ ] **Step 1: Write the RED plan/DAG tests**

Test a temporary frozen run manifest with exactly three algorithms and a valid dataset SHA. Assert exact stage expansion and priority:

```python
expected = [
    "snapshot",
    "analyze_bag",
    "preflight/fast_livo2",
    "preflight/fast_lio2",
    "preflight/kiss_icp",
    "dataset_identity/pre",
    "runtime/fast_livo2",
    "runtime/fast_lio2",
    "runtime/kiss_icp",
    "dataset_identity/post",
    "trajectory/fast_livo2",
    "trajectory/fast_lio2",
    "trajectory/kiss_icp",
    "audit/trajectory_timestamps",
    "audit/trajectory_frames",
    "audit/runtime_provenance",
    "audit/trajectory_coverage",
    "scan_manifest",
    "common_map_manifest",
    "unified_map/fast_livo2",
    "unified_map/fast_lio2",
    "unified_map/kiss_icp",
    "relative_se3",
    "same_bag_summary",
]
self.assertEqual(expected, [stage.stage_id for stage in build_stage_definitions(ALGORITHMS)])
```

Also assert:

```python
runtime = by_id["runtime/fast_lio2"]
self.assertEqual(("dataset_identity/pre", "preflight/fast_lio2"), runtime.dependencies)
self.assertEqual("SINGLE_RUNTIME_ATTEMPT", runtime.recovery_policy)

self.assertEqual(
    ("snapshot", "analyze_bag"),
    by_id["dataset_identity/pre"].dependencies,
)
```

Assert the plan freezes:

```python
self.assertEqual("lio_benchmark_suite_plan/v1", plan["schema"])
self.assertEqual("SAME_BAG_MAPPING_V1", plan["profile"])
self.assertEqual(ALGORITHMS, plan["selected_algorithms"])
self.assertEqual(sha256_file(run / "manifest.json"), plan["manifest_sha256"])
self.assertEqual(DATASET_SHA, plan["dataset"]["expected_bag_content_sha256"])
```

Assert missing/malformed dataset SHA raises `SuitePlanError("BLOCKED_INPUT_IDENTITY_UNAVAILABLE...")`; writing `plan.json` twice refuses overwrite; changing `manifest.json` after plan creation causes `FAIL_MANIFEST_MUTATION`.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_plan -v
```

Expected: FAIL because `benchmark_base.lib.suite_plan` does not exist.

- [ ] **Step 3: Implement the minimal plan module**

Use dataclasses and pure stdlib only. `build_stage_definitions()` must materialize exact dependencies from the spec, but scheduling priority must preserve the accepted clean-run order even where the logical DAG is looser (for example Relative SE(3) executes after Unified Maps in V1).

`write_suite_plan()` must:

```python
path = run / "metadata" / "suite" / "plan.json"
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("x", encoding="utf-8") as stream:
    json.dump(payload, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
```

`validate_manifest_fingerprint()` must SHA-256 the current frozen `manifest.json` and compare it exactly with the plan.

- [ ] **Step 4: Run GREEN plus existing manifest contracts**

```bash
python3 -m unittest benchmark_base.tests.test_suite_plan -v
python3 -m unittest benchmark_base.tests.test_manifest_dataset_file benchmark_base.tests.test_registry -v
python3 -m compileall -q benchmark_base/lib/suite_plan.py benchmark_base/tests/suite_test_utils.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add benchmark_base/lib/suite_plan.py \
        benchmark_base/tests/suite_test_utils.py \
        benchmark_base/tests/test_suite_plan.py
git commit -m "feat: freeze benchmark suite plan"
```

---

### Task 2: Artifact-Derived Stage and Suite Status

**Files:**
- Create: `benchmark_base/lib/suite_status.py`
- Create: `benchmark_base/tests/test_suite_status.py`
- Modify only if necessary for pure reuse: `benchmark_base/lib/common_map_manifest.py`

**Interfaces:**
- Consumes: `load_and_validate_suite_plan()` and `StageDefinition` from Task 1.
- Produces: `StageState(stage_id: str, state: str, reason_code: str | None, detail: str | None, artifacts: tuple[str, ...])`.
- Produces: `SuiteStatus(run: Path, state: str, stages: tuple[StageState, ...])`.
- Produces: `derive_stage_state(run: Path, plan: dict[str, Any], stage: StageDefinition, *, lock_probe: Callable[[], LockObservation] | None = None) -> StageState`.
- Produces: `derive_suite_status(run: Path, *, lock_probe: Callable[[], LockObservation] | None = None) -> SuiteStatus`.
- Produces: `status_to_dict(status: SuiteStatus) -> dict[str, Any]`.
- Produces: stable state/reason-code constants from the spec.

- [ ] **Step 1: Write RED tests for artifact ownership and fail-closed classification**

Cover at minimum:

1. setup artifacts:
   - `metadata/environment_snapshot.json` complete JSON -> `snapshot PASS`;
   - invalid JSON -> `FAIL_ARTIFACT_INVALID`;
   - absent -> READY/PENDING according to dependencies.
2. `metrics/bag_analysis.json` complete object -> `analyze_bag PASS`.
3. preflight:
   - `{runnable: true}` -> PASS;
   - `{status: "BLOCKED_ENVIRONMENT", runnable: false}` with no runtime identity -> BLOCKED/`BLOCKED_ENVIRONMENT`;
   - blocked preflight does not turn another algorithm runtime into blocked.
4. runtime:
   - no identity -> never PASS;
   - identity `FROZEN` + `metadata/run_<alg>.json status=PASS` + complete `metrics/runtime/<alg>.json` -> PASS;
   - identity exists + run status `FAIL_ALGORITHM` -> FAIL/`FAIL_ALGORITHM`;
   - identity exists + missing run-status -> FAIL/`FAIL_ARTIFACT_INVALID`.
5. trajectory:
   - both `standardized/trajectories/<alg>.csv` and `metadata/algorithms/<alg>/trajectory_standardization.json` valid -> PASS;
   - only one exists -> FAIL/`FAIL_PARTIAL_ARTIFACT`.
6. audit ownership:
   - trajectory timestamp audit requires every per-alg CSV+JSON;
   - frame audit requires every `metadata/frame_audit/<alg>.json` plus `metrics/trajectory_frame_audit.csv` and accepts row status `AVAILABLE`;
   - runtime provenance requires per-alg JSON + CSV rows `status=MATCH`, `frame_contract_status=MATCH`, `identity_evidence_source=RUNTIME_IDENTITY`, `runtime_identity_status=FROZEN`;
   - coverage requires per-alg JSON + `metrics/trajectory_coverage.csv` but imposes no quality threshold.
7. scan/common map:
   - scan manifest owns `selected_scans.csv` + `metadata.json`;
   - common-map validation uses the existing pure strict common-map validator and distinguishes stale from invalid.
8. unified map:
   - owns canonical `standardized/maps/<alg>/unified/map.ply` + `metadata.json` plus compatibility artifacts already written by the current evaluator;
   - requires `scan_set_policy=STRICT_COMMON_INTERSECTION`, positive `point_count`, selected>0, matched==selected, unmatched==0, and recorded common-manifest SHA equal current common manifest;
   - one owned artifact without the rest -> `FAIL_PARTIAL_ARTIFACT`.
9. Relative SE(3): all five files under `metrics/relative_se3/` required; metadata must request the exact frozen algorithm set and `terminology=PAIRWISE_DISAGREEMENT`.
10. Same-Bag summary: canonical four-file package required and `same_bag_mapping_v1.json` must have `artifact_role=CANONICAL_FINAL_SUMMARY`; do not accept the historical append-only recovery package as a new clean suite canonical summary.
11. dependency propagation: a failed selected runtime makes global comparison stages `BLOCKED_DEPENDENCY`, never READY with a reduced algorithm set.
12. read-only behavior: calling `derive_suite_status()` on a copied tree must not create/modify any path.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_status -v
```

Expected: FAIL because `suite_status` does not exist.

- [ ] **Step 3: Implement pure status validators**

Keep ROS imports out of this module. Use small helpers:

```python
def _artifact_set(paths: Sequence[Path]) -> Literal["ABSENT", "PARTIAL", "COMPLETE"]: ...
def _load_object(path: Path) -> dict[str, Any]: ...
def _csv_rows(path: Path) -> list[dict[str, str]]: ...
def _blocked_by_dependencies(...): ...
```

Do not use event files to claim PASS. Events are consulted only for RUNNING after Task 3 supplies a lock observation.

For `REUSABLE_IF_VALID`, implement exactly:

```text
complete + valid       -> PASS
all owned absent       -> READY/PENDING based on dependencies
partial                -> FAIL_PARTIAL_ARTIFACT
complete but invalid   -> FAIL_ARTIFACT_INVALID
complete but stale     -> FAIL_ARTIFACT_STALE
```

For downstream stages, terminal failed dependencies produce `BLOCKED_DEPENDENCY` rather than silently removing that dependency.

- [ ] **Step 4: Run GREEN and Same-Bag regression tests**

```bash
python3 -m unittest benchmark_base.tests.test_suite_status -v
python3 -m unittest benchmark_base.tests.test_same_bag_mapping -v
python3 -m unittest benchmark_base.tests.test_common_map_manifest -v
python3 -m compileall -q benchmark_base/lib/suite_status.py
```

If any named historical test module does not exist, use the repository's actual corresponding Same-Bag/common-map test filename found in `benchmark_base/tests`; do not omit that coverage.

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add benchmark_base/lib/suite_status.py benchmark_base/tests/test_suite_status.py
git commit -m "feat: derive suite state from artifacts"
```

---

### Task 3: Append-Only Events, Exclusive Lock, and RUNNING Semantics

**Files:**
- Create: `benchmark_base/lib/suite_events.py`
- Create: `benchmark_base/tests/test_suite_events.py`
- Extend: `benchmark_base/lib/suite_status.py`
- Extend: `benchmark_base/tests/test_suite_status.py`

**Interfaces:**
- Produces: `SuiteEventError`.
- Produces: `append_event(run: Path, *, invocation_id: str, event_type: str, stage_id: str | None, plan_sha256: str, command: list[str] | None = None, returncode: int | None = None, observed_state: str | None = None, reason_code: str | None = None, timestamp: str | None = None) -> Path`.
- Produces: `read_events(run: Path) -> tuple[dict[str, Any], ...]`.
- Produces: `validate_event_payload(payload: dict[str, Any]) -> None`.
- Produces: `SuiteExecutionLock(run: Path)` context manager using `fcntl.flock(LOCK_EX | LOCK_NB)`.
- Produces: `LockObservation(owned_by_other: bool, active_invocation_id: str | None, active_stage_id: str | None)`.
- Produces: `observe_lock(run: Path) -> LockObservation` with no file creation from status.

- [ ] **Step 1: Write RED event/lock tests**

Assert:

```python
first = append_event(... event_type="SUITE_INVOCATION_STARTED" ...)
second = append_event(... event_type="STAGE_STARTED", stage_id="snapshot" ...)
self.assertEqual("000001.json", first.name)
self.assertEqual("000002.json", second.name)
```

Assert existing event files are never overwritten, malformed gaps/duplicate IDs fail closed, and each event has schema `lio_benchmark_suite_event/v1`.

Use a subprocess or `multiprocessing.Process` to hold the lock and assert a second `SuiteExecutionLock` raises a stable `BLOCKED_EXECUTOR_LOCKED` error.

Assert `observe_lock()` on a run where `suite.lock` does not exist leaves the filesystem byte-for-byte unchanged and reports unlocked.

Assert an unmatched historical `STAGE_STARTED` event with no currently-owned lock does **not** produce RUNNING. With another process actively holding the lock and the current invocation having `STAGE_STARTED` without a terminal event, the stage is RUNNING.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_events -v
```

Expected: FAIL because `suite_events` does not exist.

- [ ] **Step 3: Implement append-only ledger and flock**

`append_event()` must allocate the next six-digit ID while the caller owns the executor lock and create the file with mode `x`. Do not rewrite a ledger index file.

`observe_lock()` must not create `suite.lock`; if absent, return unlocked. If present, open without creation and use a nonblocking probe. Releasing the probe immediately must not mutate lock contents.

Active stage derivation reads the latest active invocation's events, but RUNNING is reported only when the kernel lock is currently owned by another executor.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m unittest benchmark_base.tests.test_suite_events benchmark_base.tests.test_suite_status -v
python3 -m compileall -q benchmark_base/lib/suite_events.py benchmark_base/lib/suite_status.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add benchmark_base/lib/suite_events.py \
        benchmark_base/lib/suite_status.py \
        benchmark_base/tests/test_suite_events.py \
        benchmark_base/tests/test_suite_status.py
git commit -m "feat: add append-only suite execution ledger"
```

---

### Task 4: Dataset Identity Pre/Post Gates

**Files:**
- Extend: `benchmark_base/lib/suite_orchestrator.py` (create initially with identity helpers only)
- Create: `benchmark_base/tests/test_suite_identity.py`
- Reuse: `benchmark_base/lib/bag_probe.py`

**Interfaces:**
- Produces: `capture_dataset_identity(run: Path, plan: dict[str, Any], phase: Literal["pre", "post"], *, now: str | None = None) -> Path`.
- Produces: `validate_dataset_identity_record(run: Path, plan: dict[str, Any], phase: Literal["pre", "post"]) -> dict[str, Any]`.
- Record schema: `lio_benchmark_suite_dataset_identity/v1`.

- [ ] **Step 1: Write RED identity tests**

Build a temporary ROS-bag-shaped directory using regular fixture files (`metadata.yaml` plus two `.db3` files); no ROS packages are needed. Freeze the expected aggregate SHA with the existing P1 `build_bag_identity()` helper.

Assert pre capture writes once:

```text
metadata/suite/dataset_identity_pre.json
```

with:

```python
self.assertEqual("PASS", record["status"])
self.assertEqual(expected, record["expected_bag_content_sha256"])
self.assertEqual(expected, record["observed_bag_content_sha256"])
```

Mutate a storage file before pre capture and assert `FAIL_INPUT_MUTATION`, with no estimator-related artifact created by the helper.

For post capture, assert observed post SHA must equal both plan expected and validated pre observed SHA. Mutating the bag between pre/post produces `FAIL_INPUT_MUTATION`.

Assert pre/post files are write-once: a second capture attempt is refused rather than overwriting the old evidence.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_identity -v
```

Expected: FAIL because identity-gate helpers do not exist.

- [ ] **Step 3: Implement identity gates using P1 semantics**

Call `build_bag_identity(Path(plan["dataset"]["bag_dir"]))`; do not introduce a second hashing algorithm. Persist the complete storage/metadata fingerprints returned by P1 plus expected/observed aggregate, phase, capture time, and status.

Use atomic temporary-write + `os.replace` only after evidence is fully constructed, while still refusing an already-existing final file. On mismatch, the immutable record still records the mismatch and the caller receives a typed orchestration error with `FAIL_INPUT_MUTATION`.

- [ ] **Step 4: Run GREEN and P1 regressions**

```bash
python3 -m unittest benchmark_base.tests.test_suite_identity benchmark_base.tests.test_bag_probe benchmark_base.tests.test_dataset_intake -v
python3 -m compileall -q benchmark_base/lib/suite_orchestrator.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add benchmark_base/lib/suite_orchestrator.py benchmark_base/tests/test_suite_identity.py
git commit -m "feat: gate suite execution on bag identity"
```

---

### Task 5: Deterministic Orchestrator, Failure Policy, Resume, and Graceful Stop

**Files:**
- Extend: `benchmark_base/lib/suite_orchestrator.py`
- Create: `benchmark_base/tests/test_suite_orchestrator.py`
- Extend as needed: `benchmark_base/lib/suite_status.py`

**Interfaces:**
- Consumes all Tasks 1–4.
- Produces: `StageCommand(stage_id: str, argv: tuple[str, ...])`.
- Produces: `build_stage_command(run: Path, plan: dict[str, Any], stage_id: str, cli_path: Path) -> StageCommand | None`; dataset identity stages return `None` because they execute internally.
- Produces: `OrchestratorResult(run: Path, state: str, exit_code: int, started_stage_ids: tuple[str, ...], stop_reason: str | None)`.
- Produces: `execute_suite(run: Path, *, cli_path: Path, command_runner: Callable[[Sequence[str]], int] = subprocess_runner, install_signal_handlers: bool = True) -> OrchestratorResult`.
- Produces: `request_stage_boundary_stop(signum: int) -> None` or equivalent internal stop-controller abstraction testable without real signals.

- [ ] **Step 1: Write RED scheduler/command tests**

Assert exact public commands, for example:

```python
self.assertEqual(
    (sys.executable, str(cli), "run", "--run", str(run), "--algorithm", "fast_livo2"),
    build_stage_command(run, plan, "runtime/fast_livo2", cli).argv,
)
self.assertEqual(
    (sys.executable, str(cli), "compare", "relative-se3", "--run", str(run),
     "--algorithms", "fast_livo2", "fast_lio2", "kiss_icp"),
    build_stage_command(run, plan, "relative_se3", cli).argv,
)
```

No stage command may include `--overwrite`, `--allow-diagnostic-calibration`, an algorithm subset for global comparisons, or any profile-changing option.

- [ ] **Step 2: Write RED execution-policy tests with a fake command runner**

Use the fake runner to materialize the exact canonical artifact(s) for each requested stage and return controlled codes. Cover:

1. new all-PASS run executes stages in exact priority order;
2. after a stage artifact validates PASS, a subsequent `execute_suite()` never calls that stage again;
3. after `runtime/fast_livo2` PASS and a stage-boundary stop request, invocation exits interrupted before `runtime/fast_lio2`; resume skips FAST-LIVO2 and continues FAST-LIO2/KISS;
4. runtime identity exists + PASS -> never rerun;
5. runtime identity exists + FAIL_ALGORITHM -> never rerun and suite ultimately FAIL/BLOCK downstream;
6. FAST-LIO2 `FAIL_ALGORITHM` still allows later independent KISS runtime in the same invocation;
7. one preflight `BLOCKED_ENVIRONMENT` allows other PASS-preflight runtimes to run but prevents post identity/post-processing; later resume may refresh only that blocked preflight while its runtime identity is absent;
8. partial canonical post-processing artifact produces terminal failure and command runner is not invoked for that stage;
9. dataset pre mismatch starts zero runtime commands;
10. dataset post mismatch blocks all trajectory/comparison stages;
11. same-bag summary is not started until all dependencies are PASS;
12. a completed suite second resume starts zero stages.

- [ ] **Step 3: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_orchestrator -v
```

Expected: FAIL because orchestration engine is incomplete.

- [ ] **Step 4: Implement deterministic executor loop**

Core loop shape:

```python
with SuiteExecutionLock(run):
    invocation_id = str(uuid.uuid4())
    append_event(... "SUITE_INVOCATION_STARTED" ...)
    while True:
        status = derive_suite_status(run)
        if terminal_or_complete(status):
            break
        stage = next_safe_stage_in_priority(status)
        if stage is None:
            break
        if stop_requested:
            break
        append_event(... "STAGE_STARTED" ...)
        code = execute_one_stage(...)
        observed = derive_suite_status(run)
        append_event(... "STAGE_FINISHED" ..., returncode=code, observed_state=...)
        if stop_requested:
            break
    append_event(... "SUITE_INVOCATION_FINISHED" ...)
```

Important behavior:

- Treat command return code as operational evidence only; always re-derive stage state from artifacts after command completion.
- A command returns nonzero but leaves complete valid PASS artifact -> artifact truth wins and stage is PASS, while event preserves the nonzero return code for diagnosis; do not invent PASS from code alone.
- A command returns zero but leaves no/partial/invalid artifact -> fail closed according to status validator.
- Preflight is the only refreshable stage: if status is `BLOCKED_ENVIRONMENT` and no runtime identity exists, resume may call preflight again even though old `preflight.json` exists.
- Continue to later independently READY runtimes after one `FAIL_ALGORITHM`.
- Once no further safe stages can execute, derive overall state and return; never shrink the algorithm set.

Graceful signals:

```python
def handler(signum, frame):
    stop_controller.request(signum)
```

Do not terminate the active child. The handler only records in-memory intent; append `SUITE_STOP_REQUESTED` when Python control safely returns from the active stage. Then validate the completed stage, append invocation-finished, release the lock, and return 130/143.

- [ ] **Step 5: Run GREEN**

```bash
python3 -m unittest benchmark_base.tests.test_suite_orchestrator benchmark_base.tests.test_suite_status benchmark_base.tests.test_suite_events benchmark_base.tests.test_suite_identity -v
python3 -m compileall -q benchmark_base/lib/suite_orchestrator.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add benchmark_base/lib/suite_orchestrator.py \
        benchmark_base/lib/suite_status.py \
        benchmark_base/tests/test_suite_orchestrator.py
git commit -m "feat: orchestrate resumable same-bag suite"
```

---

### Task 6: Public CLI and Initialization Reuse

**Files:**
- Modify: `benchmark_base/bin/lio-benchmark-core`
- Modify: `benchmark_base/bin/lio-benchmark`
- Create: `benchmark_base/tests/test_suite_cli.py`
- Regression test: `benchmark_base/tests/test_dataset_intake_cli.py`

**Interfaces:**
- Core produces: `initialize_run(config: Path, run_id: str | None = None) -> Path`.
- Dispatcher produces: `cmd_suite_run(args: argparse.Namespace) -> int`.
- Dispatcher produces: `cmd_suite_status(args: argparse.Namespace) -> int`.
- Dispatcher produces: `cmd_suite_resume(args: argparse.Namespace) -> int`.

- [ ] **Step 1: Write RED initialization-refactor tests**

Load `lio-benchmark-core` as the existing tests load scripts. Patch a temporary schema-v2 config/registry fixture and assert `initialize_run()` creates exactly the same run structure and frozen manifest fields that historical `cmd_init` created. Assert `cmd_init()` is now a thin wrapper that calls the helper and prints its path.

Do not change existing `init` CLI arguments or output semantics.

- [ ] **Step 2: Write RED suite CLI parser/handler tests**

Assert parser surfaces exactly:

```text
suite run --config <Path> --run-id <required>
suite status --run <Path> [--json]
suite resume --run <Path>
```

`run-id` is required for `suite run` in V1 so target/research evidence never depends on an implicit timestamp chosen by the wrapper.

Assert forbidden args fail parsing:

```text
--algorithms
--algorithm
--rate
--duration-s
--start-offset-s
--overwrite
--force
--parallel
--jobs
--allow-diagnostic-calibration
```

Assert `suite status` calls only pure `derive_suite_status()`/formatting and never `subprocess.run`, ROS, `initialize_run`, plan writer, event writer, or lock creation.

Assert `suite run` order is:

```text
validate existing config + valid dataset SHA
-> initialize_run()
-> write_suite_plan()
-> execute_suite()
```

If plan creation fails after init, handler reports the run path and refuses adoption/repair; user must choose a new run ID.

Assert `suite resume` requires an existing `metadata/suite/plan.json`, validates manifest fingerprint, then calls `execute_suite()`; it never adopts a historical non-suite run.

- [ ] **Step 3: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_cli -v
```

Expected: FAIL because suite CLI does not exist and core lacks `initialize_run()`.

- [ ] **Step 4: Extract `initialize_run()` without semantic drift**

Move the body of existing `cmd_init()` into:

```python
def initialize_run(config: Path, run_id: str | None = None) -> Path:
    ...
    return run
```

Keep existing `cmd_init(args)`:

```python
def cmd_init(args):
    print(initialize_run(args.config.resolve(), args.run_id))
```

All existing manifest, `DATASET.txt`, directory creation, no-overwrite behavior, `RUN_STATUS.md`, timestamps, and run-id validation remain unchanged.

- [ ] **Step 5: Wire suite CLI**

Add one `suite` parser with `run/status/resume`. Keep `compare` special dispatch and all existing dataset/audit/standardize behavior unchanged.

Human status should print run/profile/dataset plus one row per stage and final suite state. JSON status must be the stable `status_to_dict()` result and nothing else on stdout.

Machine-readable repository markers are printed only by verification tests/runbook, not by normal status output.

- [ ] **Step 6: Run GREEN and complete CLI regression**

```bash
python3 -m unittest benchmark_base.tests.test_suite_cli benchmark_base.tests.test_dataset_intake_cli -v
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 benchmark_base/bin/lio-benchmark --help
python3 benchmark_base/bin/lio-benchmark suite --help
python3 benchmark_base/bin/lio-benchmark suite run --help
python3 benchmark_base/bin/lio-benchmark suite status --help
python3 benchmark_base/bin/lio-benchmark suite resume --help
python3 benchmark_base/bin/lio-benchmark list algorithms >/dev/null
```

Expected: all PASS; existing dataset CLI remains unchanged.

- [ ] **Step 7: Commit Task 6**

```bash
git add benchmark_base/bin/lio-benchmark-core \
        benchmark_base/bin/lio-benchmark \
        benchmark_base/tests/test_suite_cli.py
git commit -m "feat: expose benchmark suite orchestration cli"
```

---

### Task 7: Repository Acceptance Markers and 45 s Target-Machine Verification

**Files:**
- Create: `docs/verification/benchmark_suite_orchestrator_v1_verification.md`
- Add/extend focused contract tests only if needed for stable marker generation.

**Interfaces:**
- Repository acceptance markers:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_PLAN=PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_STATUS=PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_EVENTS_LOCK=PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_IDENTITY=PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_RESUME=PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_CLI=PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_CORE_CONTRACTS=PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_REPOSITORY_ACCEPTANCE=PASS
```

- Target marker:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_CONTRACT=PASS
```

- [ ] **Step 1: Write the target runbook with frozen P1 dataset evidence**

The authoritative target source dataset is the already accepted P1 artifact:

```text
/home/yangxuan/lio_benchmark_runs/green_house/mid360_intake_v1_20260818_073506/dataset/dataset.json
```

The runbook must first verify its dataset ID/content hash contract and must not modify it.

Create a unique temporary target config under a new acceptance root by loading:

```text
benchmark_base/config/green_house_three_full_bag_v1.json
```

and changing only experiment-local fields required by the P2 smoke acceptance:

```text
name -> unique suite smoke name
dataset -> removed
dataset_file -> absolute P1 dataset.json
replay.rate -> 1.0
replay.start_offset_s -> 0.0
replay.duration_s -> 45.0
output_root -> /home/yangxuan/lio_benchmark_runs/green_house
```

Keep algorithms exactly `fast_livo2`, `fast_lio2`, `kiss_icp`, keep all execution overrides/standardization/tolerance values unchanged, and write this config outside the repository.

- [ ] **Step 2: Freeze exact-head and environment gates**

The runbook requires:

```bash
EXPECTED_HEAD=<repository-accepted-head>
git switch feat/lio-baseline-suite
git pull --ff-only
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git status --short)"
source /opt/ros/humble/setup.bash
source /home/yangxuan/agt_navigation_v2/install/setup.bash
```

It must verify the same executable/overlay prerequisites required by the existing 3-algorithm Same-Bag profile before starting the suite.

- [ ] **Step 3: Specify automated stage-boundary interruption acceptance**

Launch:

```bash
python3 benchmark_base/bin/lio-benchmark suite run \
  --config "$CONFIG" \
  --run-id "$RUN_ID" >"$RUN_LOG" 2>&1 &
SUITE_PID=$!
```

Poll `metadata/suite/events/*.json` until `runtime/fast_livo2` has a real `STAGE_STARTED` event, then send **only the suite parent**:

```bash
kill -INT "$SUITE_PID"
```

Do not send SIGINT/SIGKILL to the estimator child/process group.

`wait "$SUITE_PID"` must yield exit `130`. Assert FAST-LIVO2 completed with valid runtime identity/status/performance evidence, and assert no `STAGE_STARTED` event exists for `runtime/fast_lio2` or `runtime/kiss_icp` in that first invocation.

- [ ] **Step 4: Specify first resume acceptance**

Fingerprint FAST-LIVO2 runtime identity and run-status files before resume. Record event IDs/counts. Run:

```bash
python3 benchmark_base/bin/lio-benchmark suite resume --run "$RUN"
```

Require final `suite status --json` state `PASS`.

Prove FAST-LIVO2 was not rerun by all of:

```text
same runtime_identity SHA before/after
same run_fast_livo2.json SHA before/after
no new STAGE_STARTED runtime/fast_livo2 event in resume invocation
FAST-LIO2 runtime started exactly once
KISS-ICP runtime started exactly once
```

Require post dataset identity PASS, all three trajectories/audits/maps, Relative SE(3), and canonical Same-Bag summary PASS.

- [ ] **Step 5: Specify completed-suite no-op resume acceptance**

Before second resume record:

```text
all runtime identity SHA values
all run_<alg>.json SHA values
count of STAGE_STARTED events
```

Run:

```bash
python3 benchmark_base/bin/lio-benchmark suite resume --run "$RUN"
```

Then require:

```text
all runtime SHA values unchanged
STAGE_STARTED count unchanged
suite state still PASS
```

Invocation-start/finished lineage events may increase; scientific stages must not.

- [ ] **Step 6: Specify target machine contract script**

The runbook's final Python machine contract must independently load artifacts/events and print exactly:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_CONTRACT=PASS
```

only after proving:

```text
exact repository HEAD
clean git status
45 s frozen replay
exact three-algorithm set/order
pre bag identity == frozen dataset SHA
post bag identity == pre == frozen dataset SHA
first invocation interrupted after FAST-LIVO2 stage boundary
FAST-LIVO2 runtime identity never changed and was never re-executed
first resume executed only remaining scientific work
second resume executed zero scientific stages
strict common map contract PASS for all algorithms
Relative SE3 requested exact frozen set
canonical Same-Bag summary PASS
```

No marker means FAIL/BLOCKED; never infer PASS from logs.

- [ ] **Step 7: Run final repository verification at exact HEAD**

Before claiming repository acceptance, invoke `superpowers:verification-before-completion` and execute fresh:

```bash
python3 -m unittest benchmark_base.tests.test_suite_plan -v
python3 -m unittest benchmark_base.tests.test_suite_status -v
python3 -m unittest benchmark_base.tests.test_suite_events -v
python3 -m unittest benchmark_base.tests.test_suite_identity -v
python3 -m unittest benchmark_base.tests.test_suite_orchestrator -v
python3 -m unittest benchmark_base.tests.test_suite_cli -v
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 benchmark_base/bin/lio-benchmark list algorithms >/dev/null
python3 benchmark_base/bin/lio-benchmark suite --help >/dev/null
```

Then verify the GitHub Actions `Core Contracts` workflow completed `success` for the exact final commit SHA.

Print/store the repository markers only after those checks are true.

- [ ] **Step 8: Commit runbook/final repository contract**

```bash
git add docs/verification/benchmark_suite_orchestrator_v1_verification.md \
        benchmark_base/tests
git commit -m "docs: add suite orchestrator target verification"
```

After exact-head CI success, stop with:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_REPOSITORY_ACCEPTANCE = PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_MACHINE_ACCEPTANCE = PENDING
```

Do not start P3 or any new algorithm adapter.
