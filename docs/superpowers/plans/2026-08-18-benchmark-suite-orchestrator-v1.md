# Benchmark Suite Orchestrator V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one fail-closed, artifact-derived, resumable `SAME_BAG_MAPPING_V1` orchestration surface that executes the accepted Same-Bag command chain without rerunning any estimator after runtime identity has been frozen.

**Architecture:** Freeze an immutable suite plan, derive every stage state from canonical run artifacts, preserve append-only operational events, and delegate scientific work to existing public benchmark commands. Keep plan/status/event logic ROS-independent so GitHub Actions verifies the orchestration contract without a target ROS environment; a real 45 s three-estimator target run proves stage-boundary interruption and resume.

**Tech Stack:** Python 3.10, stdlib `argparse`, `csv`, `json`, `hashlib`, `fcntl`, `signal`, `subprocess`, `uuid`, existing `unittest` Core Contracts, existing benchmark CLI/evaluators, ROS 2 Humble only on target-machine stage execution.

**Spec:** `docs/superpowers/specs/2026-08-18-benchmark-suite-orchestrator-v1-design.md`

## Global Constraints

- Branch: `feat/lio-baseline-suite`.
- Strict RED -> GREEN for every task.
- V1 profile is exactly `SAME_BAG_MAPPING_V1`.
- Algorithm set/order comes only from the frozen resolved run manifest; target acceptance uses `fast_livo2`, `fast_lio2`, `kiss_icp` in that order.
- No invocation-time algorithm/replay/calibration/topic/map/tolerance overrides.
- No `--force`, `--overwrite`, `--skip`, `--jobs`, `--parallel`, `--ignore-failure`, or `--rerun-algorithm`.
- No estimator or post-processing parallelism.
- Artifact state is authoritative; event history never overrides artifact validation.
- Existing canonical scientific artifacts are never automatically deleted, repaired, replaced, or overwritten.
- Once `metadata/algorithms/<alg>/runtime_identity.json` exists, that estimator is never launched again inside that run.
- `FAIL_ALGORITHM` is terminal for that estimator/run; retry requires a new run ID.
- Independent ready estimator attempts continue after another estimator fails; comparison-wide downstream stages remain blocked rather than shrinking the frozen algorithm set.
- Dataset identity must be a valid frozen 64-hex SHA-256 and is checked once before and once after the sequential estimator group.
- Raw frame-audit `AVAILABLE` must not be confused with semantic runtime-provenance `MATCH`.
- Trajectory-coverage success means valid descriptive evidence only; do not add quality thresholds.
- `suite status` is strictly read-only.
- First SIGINT/SIGTERM requests stage-boundary stop: the active child stage finishes, no new stage starts, then suite exits 130/143.
- Do not add P3, new adapters, GT metrics, report/demo/README work, multi-bag orchestration, repeated trials, or a generic workflow engine.

---

## File Structure

Create:

- `benchmark_base/lib/suite_plan.py` — fixed stage graph, priority, plan schema/build/validation.
- `benchmark_base/lib/suite_status.py` — ROS-independent artifact ownership/validation and derived stage/suite state.
- `benchmark_base/lib/suite_events.py` — append-only event ledger and flock observation.
- `benchmark_base/lib/suite_orchestrator.py` — dataset identity gates, command dispatch, failure/recovery policy, graceful stop.
- `benchmark_base/tests/suite_test_utils.py` — temporary-run/artifact builders shared only by P2 tests.
- `benchmark_base/tests/test_suite_plan.py`.
- `benchmark_base/tests/test_suite_status.py`.
- `benchmark_base/tests/test_suite_events.py`.
- `benchmark_base/tests/test_suite_identity.py`.
- `benchmark_base/tests/test_suite_orchestrator.py`.
- `benchmark_base/tests/test_suite_cli.py`.
- `docs/verification/benchmark_suite_orchestrator_v1_verification.md`.

Modify:

- `benchmark_base/bin/lio-benchmark-core` — extract reusable `initialize_run(config: Path, run_id: str | None) -> Path` without changing historical `init` semantics.
- `benchmark_base/bin/lio-benchmark` — expose `suite run`, `suite status`, `suite resume` only.

Do not change estimator adapters, algorithm registry entries, trajectory/map scientific algorithms, Relative SE(3) semantics, or Same-Bag summary readiness unless a new failing regression test first proves a P2-blocking implementation bug.

---

### Task 1: Immutable Suite Plan and Fixed DAG

**Files:**
- Create: `benchmark_base/lib/suite_plan.py`
- Create: `benchmark_base/tests/suite_test_utils.py`
- Create: `benchmark_base/tests/test_suite_plan.py`

**Interfaces:**
- `SuitePlanError(ValueError)`.
- `StageDefinition(stage_id: str, dependencies: tuple[str, ...], recovery_policy: str, priority: int)`.
- `build_stage_definitions(algorithm_ids: list[str]) -> tuple[StageDefinition, ...]`.
- `build_suite_plan(run: Path, manifest: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]`.
- `write_suite_plan(run: Path, payload: dict[str, Any]) -> Path`.
- `load_and_validate_suite_plan(run: Path) -> dict[str, Any]`.
- `validate_suite_plan_payload(payload: dict[str, Any]) -> None`.
- `validate_manifest_fingerprint(run: Path, plan: dict[str, Any]) -> None`.
- Constants: `SUITE_PLAN_SCHEMA`, `SUITE_PROFILE`, `REUSABLE_IF_VALID`, `RECHECKABLE_BEFORE_RUNTIME`, `SINGLE_RUNTIME_ATTEMPT`.

- [ ] **Step 1: Write RED plan/DAG tests**

In `test_suite_plan.py`, create a temporary run with algorithms `fast_livo2`, `fast_lio2`, `kiss_icp` and a 64-hex dataset SHA. Assert exact expansion:

```python
expected = [
    "snapshot", "analyze_bag",
    "preflight/fast_livo2", "preflight/fast_lio2", "preflight/kiss_icp",
    "dataset_identity/pre",
    "runtime/fast_livo2", "runtime/fast_lio2", "runtime/kiss_icp",
    "dataset_identity/post",
    "trajectory/fast_livo2", "trajectory/fast_lio2", "trajectory/kiss_icp",
    "audit/trajectory_timestamps", "audit/trajectory_frames",
    "audit/runtime_provenance", "audit/trajectory_coverage",
    "scan_manifest", "common_map_manifest",
    "unified_map/fast_livo2", "unified_map/fast_lio2", "unified_map/kiss_icp",
    "relative_se3", "same_bag_summary",
]
self.assertEqual(expected, [s.stage_id for s in build_stage_definitions(ALGORITHMS)])
```

Assert exact runtime/pre-identity contracts:

```python
by_id = {s.stage_id: s for s in build_stage_definitions(ALGORITHMS)}
self.assertEqual(
    ("dataset_identity/pre", "preflight/fast_lio2"),
    by_id["runtime/fast_lio2"].dependencies,
)
self.assertEqual("SINGLE_RUNTIME_ATTEMPT", by_id["runtime/fast_lio2"].recovery_policy)
self.assertEqual(("snapshot", "analyze_bag"), by_id["dataset_identity/pre"].dependencies)
```

Assert plan schema/profile/order/manifest SHA/dataset SHA. For a missing dataset SHA:

```python
with self.assertRaises(SuitePlanError) as ctx:
    build_suite_plan(run, manifest_without_sha)
self.assertIn("BLOCKED_INPUT_IDENTITY_UNAVAILABLE", str(ctx.exception))
```

Also test write-once `plan.json` and `FAIL_MANIFEST_MUTATION` after editing the frozen manifest.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_plan -v
```

Expected: import failure for `benchmark_base.lib.suite_plan`.

- [ ] **Step 3: Implement minimal plan module**

Use dataclasses + stdlib. Plan writing must be exclusive-create:

```python
path = run / "metadata" / "suite" / "plan.json"
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("x", encoding="utf-8") as stream:
    json.dump(payload, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
return path
```

`validate_manifest_fingerprint()` SHA-256s current `run/manifest.json` and raises `SuitePlanError("FAIL_MANIFEST_MUTATION: ...")` on mismatch.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m unittest benchmark_base.tests.test_suite_plan -v
python3 -m unittest benchmark_base.tests.test_manifest_dataset_file benchmark_base.tests.test_registry -v
python3 -m compileall -q benchmark_base/lib/suite_plan.py benchmark_base/tests/suite_test_utils.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/suite_plan.py benchmark_base/tests/suite_test_utils.py benchmark_base/tests/test_suite_plan.py
git commit -m "feat: freeze benchmark suite plan"
```

---

### Task 2: Artifact-Derived Stage and Suite Status

**Files:**
- Create: `benchmark_base/lib/suite_status.py`
- Create: `benchmark_base/tests/test_suite_status.py`

**Interfaces:**
- `StageState(stage_id: str, state: str, reason_code: str | None, detail: str | None, artifacts: tuple[str, ...])`.
- `SuiteStatus(run: Path, state: str, stages: tuple[StageState, ...])`.
- `derive_stage_state(run: Path, plan: dict[str, Any], stage: StageDefinition) -> StageState`.
- `derive_suite_status(run: Path) -> SuiteStatus`.
- `status_to_dict(status: SuiteStatus) -> dict[str, Any]`.
- Stage states: `PENDING`, `READY`, `RUNNING`, `PASS`, `BLOCKED`, `FAIL`; Task 2 does not emit RUNNING yet.
- Overall state rule before Task 3 RUNNING support: `PASS` if canonical summary stage PASS; else `FAIL` if any terminal stage FAIL; else `BLOCKED` if no READY stage and at least one recoverable BLOCKED stage; else `READY` if any stage READY; else `PENDING`.

- [ ] **Step 1: Write RED artifact/status tests**

Cover all canonical ownership rules from the spec:

1. `snapshot`: `metadata/environment_snapshot.json` object.
2. `analyze_bag`: `metrics/bag_analysis.json` object.
3. `preflight/<alg>`: runnable true -> PASS; `BLOCKED_ENVIRONMENT` + no runtime identity -> BLOCKED.
4. `runtime/<alg>`: require runtime identity + `metadata/run_<alg>.json`; PASS additionally requires complete `metrics/runtime/<alg>.json`; identity + `FAIL_ALGORITHM` -> terminal FAIL; identity with missing/inconsistent status -> `FAIL_ARTIFACT_INVALID`.
5. `trajectory/<alg>`: require both trajectory CSV and `trajectory_standardization.json`; exactly one -> `FAIL_PARTIAL_ARTIFACT`.
6. timestamp audit: every `metrics/trajectory_timestamp_audit/<alg>.csv` + `metadata/trajectory_timestamp_audit/<alg>.json`.
7. frame audit: every `metadata/frame_audit/<alg>.json` + `metrics/trajectory_frame_audit.csv`; raw row `status=AVAILABLE` is accepted evidence.
8. runtime provenance: every per-alg JSON + CSV; each selected row must have `status=MATCH`, `frame_contract_status=MATCH`, `identity_evidence_source=RUNTIME_IDENTITY`, `runtime_identity_status=FROZEN`.
9. coverage: every per-alg JSON + `metrics/trajectory_coverage.csv`; no rate/gap/ratio threshold.
10. scan manifest: `selected_scans.csv` + `metadata.json`, positive selected count, frozen LiDAR topic consistent with run manifest.
11. common-map manifest: `common_matched_scans.csv` + `common_matched_metadata.json`; call existing `validate_common_map_manifest(run)` and map its stale/incomplete error to `FAIL_ARTIFACT_STALE`.
12. unified map: canonical map+metadata and existing compatibility map+metadata all present; `scan_set_policy=STRICT_COMMON_INTERSECTION`; point_count>0; selected>0; matched==selected; unmatched==0; common manifest SHA matches current file.
13. Relative SE(3): require `metadata.json`, `normalized_motion.csv`, `pairwise_samples.csv`, `pairwise_summary.csv`, `onset_thresholds.csv`; metadata requested algorithms exactly equal frozen selected set and `terminology=PAIRWISE_DISAGREEMENT`.
14. Same-Bag summary: require canonical four-file package and JSON `artifact_role=CANONICAL_FINAL_SUMMARY`; never substitute finalization package for a new suite run.
15. terminal failed selected runtime causes all complete-set downstream stages to become `BLOCKED_DEPENDENCY`, never READY with a reduced set.
16. status is read-only: filesystem snapshot before/after is identical.

Partial canonical ownership test pattern:

```python
trajectory = run / "standardized/trajectories/fast_livo2.csv"
trajectory.parent.mkdir(parents=True, exist_ok=True)
trajectory.write_text("timestamp_s,x_m\n", encoding="utf-8")
state = stage_state(status, "trajectory/fast_livo2")
self.assertEqual("FAIL", state.state)
self.assertEqual("FAIL_PARTIAL_ARTIFACT", state.reason_code)
```

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_status -v
```

Expected: import failure for `suite_status`.

- [ ] **Step 3: Implement pure validators**

Implement exact helper signatures:

```python
def _artifact_set(paths: Sequence[Path]) -> str:
    present = sum(path.exists() for path in paths)
    if present == 0:
        return "ABSENT"
    if present == len(paths):
        return "COMPLETE"
    return "PARTIAL"
```

```python
def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value
```

Implement `_csv_rows(path: Path) -> list[dict[str, str]]` using `csv.DictReader` and reject missing/empty required tables where the stage contract requires rows.

For every `REUSABLE_IF_VALID` stage apply exactly:

```text
complete + valid       -> PASS
all owned absent       -> READY/PENDING from dependencies
partial                -> FAIL_PARTIAL_ARTIFACT
complete but invalid   -> FAIL_ARTIFACT_INVALID
complete but stale     -> FAIL_ARTIFACT_STALE
```

Do not read event files in Task 2.

- [ ] **Step 4: Run GREEN + exact existing regressions**

```bash
python3 -m unittest benchmark_base.tests.test_suite_status -v
python3 -m unittest benchmark_base.tests.test_same_bag_summary benchmark_base.tests.test_same_bag_summary_finalization -v
python3 -m unittest benchmark_base.tests.test_common_map_manifest benchmark_base.tests.test_strict_common_map -v
python3 -m unittest benchmark_base.tests.test_relative_se3_run benchmark_base.tests.test_runtime_provenance -v
python3 -m compileall -q benchmark_base/lib/suite_status.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/suite_status.py benchmark_base/tests/test_suite_status.py
git commit -m "feat: derive suite state from artifacts"
```

---

### Task 3: Append-Only Events, Exclusive Lock, and RUNNING Semantics

**Files:**
- Create: `benchmark_base/lib/suite_events.py`
- Create: `benchmark_base/tests/test_suite_events.py`
- Modify: `benchmark_base/lib/suite_status.py`
- Modify: `benchmark_base/tests/test_suite_status.py`

**Interfaces:**
- `SuiteEventError(ValueError)`.
- `LockObservation(locked: bool, active_invocation_id: str | None, active_stage_id: str | None)`.
- `append_event(run: Path, *, invocation_id: str, event_type: str, stage_id: str | None, plan_sha256: str, command: list[str] | None = None, returncode: int | None = None, observed_state: str | None = None, reason_code: str | None = None, timestamp: str | None = None) -> Path`.
- `read_events(run: Path) -> tuple[dict[str, Any], ...]`.
- `validate_event_payload(payload: dict[str, Any]) -> None`.
- `SuiteExecutionLock(run: Path)` context manager using `fcntl.flock(LOCK_EX | LOCK_NB)`.
- `observe_execution(run: Path) -> LockObservation` with no file creation when `suite.lock` is absent.
- Extend `derive_suite_status(run: Path, execution: LockObservation | None = None) -> SuiteStatus`.

- [ ] **Step 1: Write RED event/lock tests**

Use concrete event calls:

```python
first = append_event(
    run,
    invocation_id="inv-1",
    event_type="SUITE_INVOCATION_STARTED",
    stage_id=None,
    plan_sha256="a" * 64,
    timestamp="2026-08-18T00:00:00+00:00",
)
second = append_event(
    run,
    invocation_id="inv-1",
    event_type="STAGE_STARTED",
    stage_id="snapshot",
    plan_sha256="a" * 64,
    command=["python3", "lio-benchmark", "snapshot"],
    timestamp="2026-08-18T00:00:01+00:00",
)
self.assertEqual("000001.json", first.name)
self.assertEqual("000002.json", second.name)
```

Assert six-digit monotonic IDs, schema `lio_benchmark_suite_event/v1`, exclusive-create/no overwrite, and fail-closed malformed/gapped ledger reading.

Use `multiprocessing.Process` to hold `SuiteExecutionLock`; a second executor must raise error containing `BLOCKED_EXECUTOR_LOCKED`.

Assert `observe_execution()` on absent `suite.lock` creates nothing. Assert historical unmatched `STAGE_STARTED` without a live kernel lock is not RUNNING. When another process owns the lock and latest live invocation has an unmatched `STAGE_STARTED`, `derive_suite_status(..., execution=observe_execution(run))` reports that stage RUNNING.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_events -v
```

Expected: import failure for `suite_events`.

- [ ] **Step 3: Implement ledger/flock**

`append_event()` scans existing six-digit JSON names, validates the ledger, chooses `last_id + 1`, and writes with mode `x`. No mutable ledger-index file.

`observe_execution()` behavior:

```python
lock_path = run / "metadata/suite/suite.lock"
if not lock_path.exists():
    return LockObservation(False, None, None)
```

Open an existing lock without creation, perform a nonblocking flock probe, release immediately if acquired, and combine the result with append-only events to identify active invocation/stage. Lock ownership is required for RUNNING.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m unittest benchmark_base.tests.test_suite_events benchmark_base.tests.test_suite_status -v
python3 -m compileall -q benchmark_base/lib/suite_events.py benchmark_base/lib/suite_status.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/suite_events.py benchmark_base/lib/suite_status.py benchmark_base/tests/test_suite_events.py benchmark_base/tests/test_suite_status.py
git commit -m "feat: add append-only suite execution ledger"
```

---

### Task 4: Dataset Identity Pre/Post Gates

**Files:**
- Create: `benchmark_base/lib/suite_orchestrator.py` with identity helpers only in this task.
- Create: `benchmark_base/tests/test_suite_identity.py`
- Reuse unchanged: `benchmark_base/lib/bag_probe.py`

**Interfaces:**
- `SuiteOrchestratorError(RuntimeError)` with `reason_code: str`.
- `capture_dataset_identity(run: Path, plan: dict[str, Any], phase: Literal["pre", "post"], *, captured_at: str | None = None) -> Path`.
- `validate_dataset_identity_record(run: Path, plan: dict[str, Any], phase: Literal["pre", "post"]) -> dict[str, Any]`.
- Record schema `lio_benchmark_suite_dataset_identity/v1`.

- [ ] **Step 1: Write RED identity tests**

Create a regular temporary bag-shaped directory containing `metadata.yaml`, `part_0.db3`, `part_1.db3`; compute expected SHA with P1 `build_bag_identity()`.

PASS assertions:

```python
path = capture_dataset_identity(
    run,
    plan,
    "pre",
    captured_at="2026-08-18T00:00:00+00:00",
)
record = json.loads(path.read_text(encoding="utf-8"))
self.assertEqual("PASS", record["status"])
self.assertEqual(expected, record["expected_bag_content_sha256"])
self.assertEqual(expected, record["observed_bag_content_sha256"])
```

Mutate one storage file before pre capture and assert raised `reason_code == "FAIL_INPUT_MUTATION"`, while immutable pre record preserves the mismatch. Mutate between pre/post and assert the post record also preserves mismatch and fails. Assert second capture to the same phase refuses overwrite.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_identity -v
```

Expected: import failure for `suite_orchestrator`.

- [ ] **Step 3: Implement with P1 identity semantics**

Call exactly:

```python
identity = build_bag_identity(Path(plan["dataset"]["bag_dir"]))
observed = identity["bag_content_sha256"]
expected = plan["dataset"]["expected_bag_content_sha256"]
```

Persist expected/observed aggregate, P1 metadata fingerprint, ordered storage fingerprints, phase, captured_at, and PASS/FAIL status. For post phase, first validate pre record and require `post_observed == pre_observed == expected`.

Construct a temporary sibling file and `os.replace()` it only when the final path does not already exist; mismatch evidence is still written once before raising `SuiteOrchestratorError("FAIL_INPUT_MUTATION", ...)`.

- [ ] **Step 4: Run GREEN + P1 regressions**

```bash
python3 -m unittest benchmark_base.tests.test_suite_identity benchmark_base.tests.test_bag_probe benchmark_base.tests.test_dataset_intake -v
python3 -m compileall -q benchmark_base/lib/suite_orchestrator.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/suite_orchestrator.py benchmark_base/tests/test_suite_identity.py
git commit -m "feat: gate suite execution on bag identity"
```

---

### Task 5: Deterministic Orchestrator, Failure Policy, Resume, and Graceful Stop

**Files:**
- Modify: `benchmark_base/lib/suite_orchestrator.py`
- Create: `benchmark_base/tests/test_suite_orchestrator.py`
- Modify if a test requires status integration: `benchmark_base/lib/suite_status.py`

**Interfaces:**
- `StageCommand(stage_id: str, argv: tuple[str, ...])`.
- `OrchestratorResult(run: Path, state: str, exit_code: int, started_stage_ids: tuple[str, ...], stop_reason: str | None)`.
- `StopController.request(signum: int) -> None`, `StopController.requested: bool`, `StopController.exit_code: int | None`.
- `build_stage_command(run: Path, plan: dict[str, Any], stage_id: str, cli_path: Path) -> StageCommand | None`; identity stages return `None`.
- `execute_suite(run: Path, *, cli_path: Path, command_runner: Callable[[Sequence[str]], int] | None = None, install_signal_handlers: bool = True, stop_controller: StopController | None = None) -> OrchestratorResult`.

- [ ] **Step 1: Write RED exact-command tests**

Assert runtime command:

```python
cmd = build_stage_command(run, plan, "runtime/fast_livo2", cli)
self.assertEqual(
    (sys.executable, str(cli), "run", "--run", str(run), "--algorithm", "fast_livo2"),
    cmd.argv,
)
```

Assert Relative SE(3) command includes the **entire frozen order**:

```python
cmd = build_stage_command(run, plan, "relative_se3", cli)
self.assertEqual(
    (sys.executable, str(cli), "compare", "relative-se3", "--run", str(run),
     "--algorithms", "fast_livo2", "fast_lio2", "kiss_icp"),
    cmd.argv,
)
```

Assert no generated command contains `--overwrite`, `--allow-diagnostic-calibration`, `--parallel`, or an algorithm subset for a global stage.

- [ ] **Step 2: Write RED execution-policy tests with fake runner**

The fake runner creates the canonical artifact set for the requested stage and returns a controlled integer. Cover:

1. clean all-PASS run starts stages in exact priority order;
2. valid PASS artifact means subsequent invocation never starts that stage;
3. after FAST-LIVO2 runtime completes and stop controller is requested, invocation stops before FAST-LIO2; resume skips FAST-LIVO2 and continues remaining work;
4. existing runtime identity + PASS is never rerun;
5. existing runtime identity + `FAIL_ALGORITHM` is never rerun and makes complete-set downstream stages blocked;
6. FAST-LIO2 `FAIL_ALGORITHM` still permits later independent KISS runtime in the same invocation;
7. one `BLOCKED_ENVIRONMENT` preflight permits other PASS-preflight runtimes, prevents post identity/post-processing, and is the only stage allowed to refresh on resume while its runtime identity is absent;
8. partial post-processing artifact is terminal and its command is not called;
9. pre identity mismatch starts zero estimator commands;
10. post identity mismatch starts zero trajectory/comparison commands;
11. summary is not called before every frozen dependency is PASS;
12. completed suite resume starts zero scientific stages.

- [ ] **Step 3: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_orchestrator -v
```

Expected: failures because scheduler/command engine is not implemented.

- [ ] **Step 4: Implement command builder and executor loop**

Default command runner:

```python
def _default_command_runner(argv: Sequence[str]) -> int:
    return subprocess.run(list(argv), cwd=MODULE_ROOT, check=False).returncode
```

Executor control flow must be equivalent to:

```python
with SuiteExecutionLock(run):
    invocation_id = str(uuid.uuid4())
    append_invocation_started(run, invocation_id, plan_sha)
    while True:
        execution = LockObservation(True, invocation_id, active_stage_id)
        status = derive_suite_status(run, execution=execution)
        stage = choose_next_safe_stage(status, plan)
        if stage is None or stop_controller.requested:
            break
        append_stage_started(run, invocation_id, stage, plan_sha)
        returncode = execute_one_stage(run, plan, stage, cli_path, runner)
        observed = derive_stage_state_after_execution(run, plan, stage)
        append_stage_finished(run, invocation_id, stage, plan_sha, returncode, observed)
        if stop_controller.requested:
            append_stop_requested(run, invocation_id, stage, plan_sha, stop_controller.exit_code)
            break
    final_status = derive_suite_status(run)
    append_invocation_finished(run, invocation_id, plan_sha, final_status, stop_controller)
```

The named helper functions above are private implementation helpers in `suite_orchestrator.py`; tests may exercise only public interfaces unless a helper contains independent logic.

Rules:

- return code is lineage only; always re-derive artifact state after command completion;
- zero return + invalid/missing artifacts fails closed;
- nonzero return + independently valid canonical PASS artifact is still PASS, with nonzero code preserved in event history;
- `BLOCKED_ENVIRONMENT` preflight is the sole recheckable stage; choose it again on resume only if no runtime identity exists;
- continue later independent runtimes after `FAIL_ALGORITHM`;
- never shrink selected algorithms;
- never call a stage command if owned artifacts are partial/invalid/stale;
- second no-op resume may append invocation start/finish events but no `STAGE_STARTED` event.

Signal handler:

```python
def _handler(signum: int, _frame: object) -> None:
    stop_controller.request(signum)
```

The handler does not signal/kill the child. Once child command returns, record stop request, validate stage, append invocation finish, release lock, and return exit 130 for SIGINT or 143 for SIGTERM.

- [ ] **Step 5: Run GREEN**

```bash
python3 -m unittest benchmark_base.tests.test_suite_orchestrator benchmark_base.tests.test_suite_status benchmark_base.tests.test_suite_events benchmark_base.tests.test_suite_identity -v
python3 -m compileall -q benchmark_base/lib/suite_orchestrator.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add benchmark_base/lib/suite_orchestrator.py benchmark_base/lib/suite_status.py benchmark_base/tests/test_suite_orchestrator.py
git commit -m "feat: orchestrate resumable same-bag suite"
```

---

### Task 6: Public CLI and Initialization Reuse

**Files:**
- Modify: `benchmark_base/bin/lio-benchmark-core`
- Modify: `benchmark_base/bin/lio-benchmark`
- Create: `benchmark_base/tests/test_suite_cli.py`
- Regression: `benchmark_base/tests/test_cli_manifest.py`, `benchmark_base/tests/test_dataset_intake_cli.py`

**Interfaces:**
- Core: `initialize_run(config: Path, run_id: str | None = None) -> Path`.
- Dispatcher: `cmd_suite_run(args: argparse.Namespace) -> int`.
- Dispatcher: `cmd_suite_status(args: argparse.Namespace) -> int`.
- Dispatcher: `cmd_suite_resume(args: argparse.Namespace) -> int`.

- [ ] **Step 1: Write RED initialization-refactor test**

Load `lio-benchmark-core` using the repository's existing SourceFileLoader pattern. Assert extracted `initialize_run()` preserves current directory creation, resolved frozen manifest, `input/DATASET.txt`, `RUN_STATUS.md`, run-id validation, source-manifest fields, and no-overwrite behavior. Assert historical `cmd_init(args)` only prints returned path.

- [ ] **Step 2: Write RED suite parser/handler tests**

Required parser examples:

```python
run_args = parser.parse_args([
    "suite", "run", "--config", "/tmp/experiment.json", "--run-id", "suite_smoke_001"
])
self.assertEqual("suite_smoke_001", run_args.run_id)

status_args = parser.parse_args(["suite", "status", "--run", "/tmp/run", "--json"])
self.assertTrue(status_args.json)

resume_args = parser.parse_args(["suite", "resume", "--run", "/tmp/run"])
self.assertEqual(Path("/tmp/run"), resume_args.run)
```

`--run-id` is required for `suite run`. Assert parser rejects each forbidden option: `--algorithms`, `--algorithm`, `--rate`, `--duration-s`, `--start-offset-s`, `--overwrite`, `--force`, `--parallel`, `--jobs`, `--allow-diagnostic-calibration`.

Handler assertions:

- status calls only plan/status/lock-observation readers and formatting; no subprocess, ROS, init, event write, or lock-file creation;
- run order is config validation + valid dataset SHA -> `initialize_run()` -> `build/write_suite_plan()` -> `execute_suite()`;
- if plan creation fails after init, expose run path and refuse adoption/repair;
- resume requires existing plan and valid manifest fingerprint; never adopts a historical run.

- [ ] **Step 3: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_suite_cli -v
```

Expected: suite parser/handlers and `initialize_run()` missing.

- [ ] **Step 4: Extract initialization helper**

Implement:

```python
def initialize_run(config: Path, run_id: str | None = None) -> Path:
    config = config.resolve()
    source, resolved = resolve_config(config)
    resolved_run_id = run_id or f"{source['name']}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    # Continue with the exact existing cmd_init directory/manifest/DATASET/RUN_STATUS logic.
    return run
```

The comment refers to moving the existing code verbatim, not inventing new behavior. `cmd_init` becomes:

```python
def cmd_init(args: argparse.Namespace) -> None:
    print(initialize_run(args.config, args.run_id))
```

- [ ] **Step 5: Wire suite CLI**

Add `suite` to public dispatcher with exactly `run`, `status`, `resume`. Human status prints run/profile/dataset, every stage state/reason, and overall state. `--json` prints only `json.dumps(status_to_dict(status), ensure_ascii=False, indent=2)`.

- [ ] **Step 6: Run GREEN + full tracked Core Contracts**

```bash
python3 -m unittest benchmark_base.tests.test_suite_cli benchmark_base.tests.test_cli_manifest benchmark_base.tests.test_dataset_intake_cli -v
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 benchmark_base/bin/lio-benchmark --help >/dev/null
python3 benchmark_base/bin/lio-benchmark suite --help >/dev/null
python3 benchmark_base/bin/lio-benchmark suite run --help >/dev/null
python3 benchmark_base/bin/lio-benchmark suite status --help >/dev/null
python3 benchmark_base/bin/lio-benchmark suite resume --help >/dev/null
python3 benchmark_base/bin/lio-benchmark list algorithms >/dev/null
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add benchmark_base/bin/lio-benchmark-core benchmark_base/bin/lio-benchmark benchmark_base/tests/test_suite_cli.py
git commit -m "feat: expose benchmark suite orchestration cli"
```

---

### Task 7: Repository Acceptance and 45 s Target-Machine Verification

**Files:**
- Create: `docs/verification/benchmark_suite_orchestrator_v1_verification.md`

**Repository markers:**

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

**Target marker:**

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_CONTRACT=PASS
```

- [ ] **Step 1: Write frozen target input/config generation**

Use the already accepted P1 dataset file only:

```text
/home/yangxuan/lio_benchmark_runs/green_house/mid360_intake_v1_20260818_073506/dataset/dataset.json
```

Runbook verifies the dataset file and its accepted bag-content SHA before use. It creates a unique config outside the repository by loading `benchmark_base/config/green_house_three_full_bag_v1.json` and changing only:

```text
name = unique P2 smoke name
remove dataset
set dataset_file = accepted absolute P1 dataset.json
replay = {rate: 1.0, start_offset_s: 0.0, duration_s: 45.0}
output_root = /home/yangxuan/lio_benchmark_runs/green_house
```

Algorithms remain exactly `fast_livo2`, `fast_lio2`, `kiss_icp`; execution overrides, standardization values, map sampling, and trajectory tolerance remain unchanged.

- [ ] **Step 2: Write exact-head/environment gate**

Runbook requires the caller to export the repository-accepted SHA; it never contains a future placeholder:

```bash
test -n "${BENCHMARK_SUITE_ORCHESTRATOR_V1_EXPECTED_HEAD:-}" || exit 1
git switch feat/lio-baseline-suite
git pull --ff-only
test "$(git rev-parse HEAD)" = "$BENCHMARK_SUITE_ORCHESTRATOR_V1_EXPECTED_HEAD"
test -z "$(git status --short)"
source /opt/ros/humble/setup.bash
source /home/yangxuan/agt_navigation_v2/install/setup.bash
```

Verify the same executable/overlay prerequisites used by accepted Same-Bag V1.

- [ ] **Step 3: Write automated stage-boundary interruption acceptance**

Set `RUN=/home/yangxuan/lio_benchmark_runs/green_house/$RUN_ID` before launch. Start parent only:

```bash
python3 benchmark_base/bin/lio-benchmark suite run \
  --config "$CONFIG" --run-id "$RUN_ID" >"$RUN_LOG" 2>&1 &
SUITE_PID=$!
```

Poll `"$RUN/metadata/suite/events"` until a valid `STAGE_STARTED` event for `runtime/fast_livo2` appears, then:

```bash
kill -INT "$SUITE_PID"
set +e
wait "$SUITE_PID"
FIRST_RC=$?
set -e
test "$FIRST_RC" -eq 130
```

Do not signal estimator child/process group. Assert FAST-LIVO2 runtime identity/status/performance are complete and first invocation has no `STAGE_STARTED` for FAST-LIO2/KISS runtime.

- [ ] **Step 4: Write first-resume acceptance**

Fingerprint FAST-LIVO2 `runtime_identity.json` and `run_fast_livo2.json`; record event IDs. Run:

```bash
python3 benchmark_base/bin/lio-benchmark suite resume --run "$RUN"
python3 benchmark_base/bin/lio-benchmark suite status --run "$RUN" --json > "$ACCEPT_ROOT/status_after_resume.json"
```

Require suite PASS and prove:

```text
FAST-LIVO2 runtime identity SHA unchanged
FAST-LIVO2 run-status SHA unchanged
resume invocation has no runtime/fast_livo2 STAGE_STARTED
runtime/fast_lio2 STAGE_STARTED exactly once overall
runtime/kiss_icp STAGE_STARTED exactly once overall
post dataset identity PASS
all trajectories/audits/maps PASS
Relative SE3 PASS
canonical Same-Bag summary PASS
```

- [ ] **Step 5: Write completed-suite no-op resume acceptance**

Record all runtime identity/run-status SHA values and count of all `STAGE_STARTED` events, then:

```bash
python3 benchmark_base/bin/lio-benchmark suite resume --run "$RUN"
```

Require all runtime SHA values unchanged, `STAGE_STARTED` count unchanged, suite remains PASS. Invocation start/finish lineage events may increase.

- [ ] **Step 6: Write authoritative target machine contract**

Final Python contract independently loads plan, status, events, pre/post identity, common-map/unified-map metadata, Relative SE3 metadata, and canonical summary. It prints:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_CONTRACT=PASS
```

only after proving exact HEAD/clean git, 45 s replay, exact selected set/order, pre==post==frozen bag SHA, first invocation stage-boundary interruption after FAST-LIVO2, no FAST-LIVO2 re-execution, first resume completed only remaining scientific work, second resume started zero scientific stages, strict common-map/unified-map contracts PASS, Relative SE3 requested exact set, and canonical summary PASS.

No marker means FAIL/BLOCKED.

- [ ] **Step 7: Final repository verification before completion claim**

Invoke `superpowers:verification-before-completion`, then fresh-run:

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

Verify GitHub Actions `Core Contracts` is `completed/success` for the exact final commit SHA.

- [ ] **Step 8: Commit target runbook**

```bash
git add docs/verification/benchmark_suite_orchestrator_v1_verification.md
git commit -m "docs: add suite orchestrator target verification"
```

After exact-head CI succeeds, stop at:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_REPOSITORY_ACCEPTANCE = PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_MACHINE_ACCEPTANCE = PENDING
```

Do not start P3 or a new adapter.
