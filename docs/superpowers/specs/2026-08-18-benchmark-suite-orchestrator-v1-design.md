# Benchmark Suite Orchestrator V1 Design

Date: 2026-08-18
Branch: `feat/lio-baseline-suite`

## 1. Purpose

`Benchmark Suite Orchestrator V1` turns the already-validated Same-Bag Mapping Benchmark V1 command chain into one auditable, resumable execution surface without changing the scientific meaning of any existing evaluator.

The orchestrator is not a new benchmark algorithm and is not a replacement for the existing `lio-benchmark` commands. It is a coordination layer that:

1. freezes one immutable suite plan from one already-frozen experiment manifest;
2. derives stage state from existing run artifacts and validators rather than trusting a mutable status database;
3. executes only stages that are both dependency-ready and safe to execute;
4. never re-executes an estimator after that estimator has established a run-local runtime identity;
5. continues independent estimator attempts when another estimator fails;
6. blocks all comparison-wide downstream stages when the frozen selected-algorithm set is no longer complete;
7. preserves append-only operational lineage;
8. supports stage-boundary interruption and safe resume;
9. keeps estimator execution sequential in V1.

The user-facing flow is:

```bash
lio-benchmark suite run \
  --config /absolute/path/to/experiment.json \
  --run-id greenhouse_suite_20260818_01

lio-benchmark suite status \
  --run /absolute/path/to/run

lio-benchmark suite resume \
  --run /absolute/path/to/run
```

`run` creates one new immutable benchmark run and executes the suite. `status` is read-only. `resume` re-derives all stage states from artifacts and executes only missing stages that are still safe to execute.

## 2. Scope

V1 supports exactly one suite profile:

```text
SAME_BAG_MAPPING_V1
```

The profile schedules the existing Same-Bag Mapping V1 capabilities for the algorithms frozen in the experiment manifest. Initial repository and target-machine acceptance use exactly:

```text
fast_livo2
fast_lio2
kiss_icp
```

V1 does not add algorithm-specific behavior. A later adapter may participate only after it has independently passed its own adapter acceptance and the suite profile is explicitly revised in a later spec.

## 3. Non-goals

V1 explicitly does not implement:

- Point-LIO, DLIO, Leg-KILO, LIO-SAM, GLIM, Faster-LIO, SLICT, or any new adapter acceptance;
- Representative Window selection or Representative Window gating inside the suite;
- Failure-Mode Audit automation;
- estimator parallelism;
- post-processing parallelism;
- `--force`, `--overwrite`, `--skip`, `--jobs`, `--parallel`, `--ignore-failure`, or `--rerun-algorithm`;
- dynamic algorithm selection at suite invocation time;
- changing replay, calibration, topics, map reconstruction parameters, or trajectory tolerance after run creation;
- automatic deletion, repair, replacement, or overwriting of partial scientific artifacts;
- automatic recovery of a `FAIL_ALGORITHM` estimator attempt inside the same run;
- ground-truth accuracy metrics;
- algorithm ranking;
- report/demo/README generation;
- multi-bag orchestration;
- repeated-trial performance statistics;
- a generic workflow engine for arbitrary user-defined DAGs.

## 4. Scientific boundary

The orchestrator must preserve the scientific labels and contracts already accepted by Same-Bag Mapping Benchmark V1:

```text
benchmark_profile = DEFAULT_ADAPTED
scientific_status = DESCRIPTIVE_NO_GROUND_TRUTH
performance_status = SINGLE_RUN_DESCRIPTIVE
Unified Map policy = STRICT_COMMON_INTERSECTION
Relative SE(3) = PAIRWISE_DISAGREEMENT
```

KISS-ICP remains a LiDAR-only control. FAST-LIVO2 and FAST-LIO2 remain LiDAR+IMU methods. Orchestration must not describe the three algorithms as having identical modality.

A suite `PASS` means the frozen workflow and its evidence contracts completed successfully. It does not mean any estimator is accurate or superior.

Trajectory coverage remains descriptive evidence. A coverage audit `PASS` means the audit produced valid evidence; it does not impose a new quality threshold on rate, large-gap count, boundary lag, or count ratio.

Raw trajectory frame audit and semantic frame compatibility remain distinct:

```text
trajectory_frame_audit.csv status = AVAILABLE
runtime_provenance.csv status = MATCH
runtime_provenance.csv frame_contract_status = MATCH
```

The orchestrator must never require the raw frame-audit evidence-layer status to equal `MATCH`.

## 5. Architectural principle: artifact-derived state

The orchestrator must not use a mutable `state.json` as the source of truth.

Authoritative state is derived from existing run artifacts plus their existing validators:

```text
immutable/frozen artifact
        +
artifact validator
        ↓
derived stage state
        ↓
orchestrator scheduling decision
```

Operational events record what the orchestrator attempted, but events never override artifact truth.

For example, an event saying that `runtime/fast_lio2` exited with return code `0` does not by itself make the stage `PASS`. The runtime stage is `PASS` only when the accepted runtime-status and runtime-identity artifacts satisfy the runtime validator.

Likewise, strict common-map state is derived from `common_matched_scans.csv`, `common_matched_metadata.json`, selected-scan evidence, standardized trajectory fingerprints, and the existing strict common-map validator.

## 6. New modules and responsibilities

The implementation should introduce four focused library modules:

```text
benchmark_base/lib/
├── suite_plan.py
├── suite_status.py
├── suite_events.py
└── suite_orchestrator.py
```

### 6.1. `suite_plan.py`

Responsibilities:

- define `SAME_BAG_MAPPING_V1` stage IDs;
- define deterministic dependencies and scheduling order;
- build the immutable `plan.json` payload from the frozen run manifest;
- validate the plan schema;
- validate that the current run manifest still matches the plan fingerprint;
- expose stage metadata and recovery policy to status/orchestrator code.

It must not execute ROS, estimators, or evaluators.

### 6.2. `suite_status.py`

Responsibilities:

- read the run manifest and suite plan;
- inspect existing artifacts without modifying them;
- invoke pure validators where available;
- classify every stage as `PENDING`, `READY`, `RUNNING`, `PASS`, `BLOCKED`, or `FAIL`;
- attach stable reason codes;
- derive the overall suite state;
- provide both structured and human-readable status views.

It must be read-only.

### 6.3. `suite_events.py`

Responsibilities:

- append one immutable event file per event;
- allocate deterministic monotonically increasing event filenames while the suite executor holds the exclusive lock;
- validate event schema;
- read event lineage for diagnostics and active-stage display.

Events are lineage, not source-of-truth state.

### 6.4. `suite_orchestrator.py`

Responsibilities:

- acquire/release the suite execution lock;
- create/validate the suite plan;
- derive current state;
- choose the next dependency-ready safe stage according to deterministic execution order;
- delegate stage execution to existing public benchmark capabilities;
- record append-only events;
- implement the failure policy;
- implement graceful stage-boundary stop on first SIGINT/SIGTERM;
- stop once no further safe stage can execute or the suite is complete.

It must not duplicate estimator, trajectory, map, Relative SE(3), audit, or summary algorithms.

## 7. Run-local suite layout

Every suite-managed run adds only:

```text
metadata/suite/
├── plan.json
├── suite.lock
├── dataset_identity_pre.json
├── dataset_identity_post.json
└── events/
    ├── 000001.json
    ├── 000002.json
    ├── 000003.json
    └── ...
```

`plan.json`, `dataset_identity_pre.json`, `dataset_identity_post.json`, and every event file are write-once.

`suite.lock` is only a lock inode/path. Its file contents are not authoritative evidence.

No mutable suite-state database is created.

## 8. Immutable suite plan contract

The plan schema is:

```text
lio_benchmark_suite_plan/v1
```

Required top-level fields:

```json
{
  "schema": "lio_benchmark_suite_plan/v1",
  "profile": "SAME_BAG_MAPPING_V1",
  "created_at": "...",
  "run_id": "...",
  "run_dir": "/absolute/path/to/run",
  "manifest_path": "/absolute/path/to/run/manifest.json",
  "manifest_sha256": "...",
  "dataset": {
    "dataset_id": "...",
    "bag_dir": "/absolute/path/to/bag",
    "expected_bag_content_sha256": "..."
  },
  "selected_algorithms": [
    "fast_livo2",
    "fast_lio2",
    "kiss_icp"
  ],
  "execution_policy": "SEQUENTIAL_ESTIMATORS",
  "failure_policy": "CONTINUE_INDEPENDENT_BLOCK_DEPENDENTS",
  "state_policy": "ARTIFACT_DERIVED",
  "event_policy": "APPEND_ONLY",
  "lock_policy": "PROCESS_EXCLUSIVE_FLOCK",
  "stages": []
}
```

The exact selected algorithm order comes from the frozen resolved run manifest and is preserved.

The plan freezes the absolute run directory, manifest SHA-256, dataset identity expectation, stage graph, and execution order. It must not be rewritten on resume.

If `plan.json` already exists, `suite resume` validates it. A plan/manifest mismatch is terminal for that run:

```text
status = FAIL
reason_code = FAIL_MANIFEST_MUTATION
```

The user must create a new run rather than update the plan.

## 9. Dataset identity precondition

P2 requires a frozen content identity for the source bag.

The resolved dataset must contain a non-empty 64-hex-character SHA-256 in:

```text
dataset.sha256
```

For datasets produced by MID360 Bag Intake V1, this value is the content-based aggregate `bag_content_sha256` built from `metadata.yaml` plus ordered ROS 2 storage files.

P2 does not require the dataset to originate specifically from `dataset_file`; a registry dataset is acceptable only if it carries the same valid frozen content hash contract.

A dataset with missing or malformed `dataset.sha256` is rejected before run execution:

```text
BLOCKED_INPUT_IDENTITY_UNAVAILABLE
```

No estimator may start without this identity.

## 10. Dataset identity gates

The suite has two mandatory bag-byte identity gates.

### 10.1. Pre-execution identity

Before the first estimator is started, compute the current bag identity using the same content-identity semantics established by MID360 Bag Intake V1.

Write once:

```text
metadata/suite/dataset_identity_pre.json
```

It records at minimum:

```text
expected_bag_content_sha256
observed_bag_content_sha256
storage file fingerprints
metadata.yaml fingerprint
captured_at
status
```

It passes only when:

```text
observed == expected
```

Mismatch is terminal:

```text
status = FAIL
reason_code = FAIL_INPUT_MUTATION
```

No estimator runs.

### 10.2. Post-execution identity

The post identity is computed only after every selected runtime stage has reached a non-recheckable terminal runtime outcome:

```text
PASS
or
FAIL_ALGORITHM
```

If any selected runtime remains `BLOCKED_ENVIRONMENT`, the post identity remains pending and downstream post-processing does not begin.

Write once:

```text
metadata/suite/dataset_identity_post.json
```

It must equal both the plan expectation and the pre-execution identity.

Any mismatch is terminal:

```text
status = FAIL
reason_code = FAIL_INPUT_MUTATION
```

All downstream standardization/comparison stages become `BLOCKED_DEPENDENCY`.

V1 intentionally hashes the bag before the estimator group and after the estimator group rather than before every estimator. Estimators remain sequential, and the post gate detects any mutation during the execution interval without adding a full multi-gigabyte hash pass before each algorithm.

## 11. Stage state vocabulary

Every stage has exactly one top-level state:

```text
PENDING
READY
RUNNING
PASS
BLOCKED
FAIL
```

Meaning:

- `PENDING`: required dependencies have not yet passed and no dependency has failed/blocked;
- `READY`: all dependencies required for this stage have passed, no conflicting artifact exists, and execution is safe;
- `RUNNING`: the suite lock is currently held by an executor and append-only events identify this stage as the active stage;
- `PASS`: authoritative artifacts exist and satisfy the stage validator;
- `BLOCKED`: execution is currently not allowed, but the stage itself has not produced a terminal failure artifact;
- `FAIL`: the run contains a terminal contract violation or a non-retryable failed attempt for this stage.

Every `BLOCKED` or `FAIL` state includes a stable `reason_code`.

## 12. Reason codes

V1 defines at least:

```text
BLOCKED_DEPENDENCY
BLOCKED_ENVIRONMENT
BLOCKED_INPUT_IDENTITY_UNAVAILABLE
BLOCKED_EXECUTOR_LOCKED

FAIL_ALGORITHM
FAIL_INPUT_MUTATION
FAIL_MANIFEST_MUTATION
FAIL_PARTIAL_ARTIFACT
FAIL_ARTIFACT_INVALID
FAIL_ARTIFACT_STALE
FAIL_COMMAND
```

A stage validator may include a human-readable `detail`, but machine acceptance must key off the stable reason code.

## 13. Recovery policy classes

Each stage declares one of three recovery policies.

### 13.1. `REUSABLE_IF_VALID`

Used for deterministic post-processing/scientific artifact stages.

Rules:

- complete + valid artifact -> `PASS`, never rerun;
- no artifact -> `READY` when dependencies pass;
- partial artifact -> `FAIL_PARTIAL_ARTIFACT`;
- complete but invalid/stale artifact -> `FAIL_ARTIFACT_INVALID` or `FAIL_ARTIFACT_STALE`;
- V1 never auto-deletes or overwrites these artifacts.

### 13.2. `RECHECKABLE_BEFORE_RUNTIME`

Used only for preflight/environment observations.

A preflight that is blocked because the target environment is temporarily unavailable may be re-evaluated on a later `suite resume` provided no runtime identity exists for that algorithm.

The latest preflight JSON may be refreshed by the existing preflight machinery. Every orchestrator attempt remains preserved in append-only suite events.

This is an explicit exception to the write-once scientific artifact policy because preflight is an operational environment observation, not estimator output.

### 13.3. `SINGLE_RUNTIME_ATTEMPT`

Used for each estimator runtime.

Once `metadata/algorithms/<algorithm>/runtime_identity.json` exists, that estimator is never started again inside the same run.

Possible outcomes:

```text
runtime identity absent + environment currently runnable -> READY
runtime identity absent + BLOCKED_ENVIRONMENT -> BLOCKED, resume allowed
runtime identity exists + run status PASS -> PASS
runtime identity exists + run status FAIL_ALGORITHM -> FAIL
runtime identity exists + inconsistent/missing run status -> FAIL_ARTIFACT_INVALID
```

A `FAIL_ALGORITHM` is terminal for the run. Retrying that estimator requires a new run ID.

## 14. Stage IDs

V1 stage IDs are fixed.

Run-global setup/input stages:

```text
snapshot
analyze_bag
dataset_identity/pre
```

Per-algorithm operational/runtime stages, expanded in frozen selected-algorithm order:

```text
preflight/<algorithm_id>
runtime/<algorithm_id>
```

Run-global post-runtime identity:

```text
dataset_identity/post
```

Per-algorithm trajectory stages:

```text
trajectory/<algorithm_id>
```

Global audit stages:

```text
audit/trajectory_timestamps
audit/trajectory_frames
audit/runtime_provenance
audit/trajectory_coverage
```

Map/comparison stages:

```text
scan_manifest
common_map_manifest
unified_map/<algorithm_id>
relative_se3
same_bag_summary
```

The overall suite state is derived and is not a write-once stage artifact.

## 15. Stage dependency graph

Dependencies are deterministic.

### 15.1. Setup

```text
snapshot                 <- plan
analyze_bag              <- plan
preflight/<alg>          <- snapshot + analyze_bag

dataset_identity/pre     <- snapshot + analyze_bag + all preflight stages not terminal-failed
```

Preflight may run for every selected algorithm even if another algorithm is blocked.

The pre-identity gate must pass before any runtime starts.

### 15.2. Runtime group

```text
runtime/<alg>            <- dataset_identity/pre + preflight/<alg>
```

Runtime stages are independent with respect to algorithm outcome but executed sequentially in frozen algorithm order.

A `FAIL_ALGORITHM` does not prevent later independent estimator runtimes in the same invocation from being attempted.

`BLOCKED_ENVIRONMENT` for one algorithm does not prevent already-ready independent estimator runtimes for other algorithms from being attempted. However, post-runtime processing does not begin until all selected runtimes are non-recheckable terminal outcomes.

### 15.3. Post-runtime input identity

```text
dataset_identity/post    <- all selected runtime stages terminal as PASS or FAIL_ALGORITHM
```

The identity stage may still run when one runtime has `FAIL_ALGORITHM`; it records whether the bag remained immutable during the attempted estimator group.

### 15.4. Trajectory standardization

```text
trajectory/<alg>         <- dataset_identity/post + runtime/<alg> PASS
```

A failed selected estimator therefore prevents a complete all-algorithm trajectory set.

### 15.5. Global audits

Formal global audits require all selected standardized trajectories:

```text
audit/trajectory_timestamps <- all trajectory/<alg> PASS
audit/trajectory_frames     <- all trajectory/<alg> PASS
audit/trajectory_coverage   <- all trajectory/<alg> PASS

audit/runtime_provenance    <- all runtime/<alg> PASS
                              + all trajectory/<alg> PASS
                              + audit/trajectory_frames PASS
```

The audit validators preserve existing evidence-layer semantics.

### 15.6. Scan/map comparison

```text
scan_manifest           <- all trajectory/<alg> PASS
                           + dataset_identity/post PASS

common_map_manifest     <- scan_manifest PASS
                           + all trajectory/<alg> PASS

unified_map/<alg>       <- common_map_manifest PASS
                           + trajectory/<alg> PASS
```

Every Unified Map consumes the same strict common intersection.

### 15.7. Relative SE(3)

Logical dependencies:

```text
relative_se3            <- all trajectory/<alg> PASS
                           + audit/trajectory_timestamps PASS
                           + audit/trajectory_frames PASS
                           + audit/runtime_provenance PASS
```

Relative SE(3) does not logically depend on Unified Maps, but the V1 deterministic scheduler executes it after all Unified Maps to preserve the established Same-Bag clean-run ordering.

### 15.8. Summary

```text
same_bag_summary        <- all runtime/<alg> PASS
                           + all trajectory/<alg> PASS
                           + all unified_map/<alg> PASS
                           + relative_se3 PASS
                           + audit/trajectory_timestamps PASS
                           + audit/trajectory_frames PASS
                           + audit/runtime_provenance PASS
                           + audit/trajectory_coverage PASS
```

The existing `same_bag_summary.py` readiness gate remains authoritative for runtime identity, runtime performance, strict Unified Map policy/counts, and trajectory availability. The orchestrator must not copy or weaken that readiness logic.

## 16. Deterministic V1 scheduling order

The dependency graph and scheduling order are separate concepts. V1 remains sequential and uses exactly this priority order when multiple stages are `READY`:

```text
1. snapshot
2. analyze_bag
3. preflight/<algorithms in frozen order>
4. dataset_identity/pre
5. runtime/<algorithms in frozen order>
6. dataset_identity/post
7. trajectory/<algorithms in frozen order>
8. audit/trajectory_timestamps
9. audit/trajectory_frames
10. audit/runtime_provenance
11. audit/trajectory_coverage
12. scan_manifest
13. common_map_manifest
14. unified_map/<algorithms in frozen order>
15. relative_se3
16. same_bag_summary
```

V1 does not execute two stages concurrently.

## 17. Failure policy

The suite policy is frozen as:

```text
CONTINUE_INDEPENDENT_BLOCK_DEPENDENTS
```

### 17.1. Estimator failure

Example:

```text
runtime/fast_livo2 = PASS
runtime/fast_lio2  = FAIL_ALGORITHM
runtime/kiss_icp   = not yet attempted
```

The same invocation still attempts `runtime/kiss_icp` if it is independently `READY`.

If the final runtime outcomes are:

```text
fast_livo2 = PASS
fast_lio2  = FAIL
kiss_icp   = PASS
```

then all comparison-wide stages that require the frozen complete algorithm set become:

```text
BLOCKED
reason_code = BLOCKED_DEPENDENCY
```

The selected algorithm set is never silently reduced to the two surviving algorithms.

The overall suite is `FAIL` because at least one terminal stage failed.

### 17.2. Environment block

If an algorithm is `BLOCKED_ENVIRONMENT` and no runtime identity exists for it, other independent ready runtimes may execute. Post-runtime processing does not begin while any selected runtime remains recheckably blocked.

If no terminal failure exists, the overall suite is `BLOCKED` and may later be resumed after the environment is repaired.

### 17.3. Terminal fail and later resume

If the suite already contains a terminal `FAIL_ALGORITHM`, `FAIL_INPUT_MUTATION`, `FAIL_MANIFEST_MUTATION`, partial artifact failure, stale artifact failure, or other terminal contract failure, `suite resume` must not start new work. It reports the derived failure and requires a new run.

The policy to continue independent estimators applies within the invocation in which the terminal runtime failure is first observed; it is not a license to add more experimental execution after a failed run has already been closed and later revisited.

## 18. Artifact validation and no-overwrite rules

For every `REUSABLE_IF_VALID` stage:

```text
complete + valid       -> PASS / skip
all expected absent    -> READY when dependencies pass
partial                -> FAIL_PARTIAL_ARTIFACT
complete but invalid   -> FAIL_ARTIFACT_INVALID
complete but stale     -> FAIL_ARTIFACT_STALE
```

The orchestrator must not call a stage command when any output owned by that stage already exists but the stage validator cannot prove the complete valid contract.

This prevents an existing evaluator that normally writes directly to a path from overwriting historical evidence during `resume`.

### 18.1. Unified Map validator

At minimum, each Unified Map stage requires:

```text
standardized/maps/<alg>/unified/map.ply
standardized/maps/<alg>/unified/metadata.json
```

and validates:

```text
scan_set_policy == STRICT_COMMON_INTERSECTION
common manifest SHA matches validated common-map evidence
selected_scan_count > 0
matched_scan_count == selected_scan_count
unmatched_scan_count == 0
point_count > 0
trajectory/common-scan fingerprints remain valid
```

If `map.ply` exists without metadata, or metadata exists without the map, the stage is terminal `FAIL_PARTIAL_ARTIFACT`. V1 does not regenerate over the partial artifact.

### 18.2. Canonical summary

If canonical summary outputs already exist, the stage validator either proves them to be the complete accepted canonical package or fails closed. V1 orchestrator does not automatically invoke historical append-only finalization logic as a normal clean-run recovery mechanism.

`same-bag-finalize` remains a specific recovery tool for the already-documented historical premature-summary incident, not a general suite stage.

## 19. Runtime identity rule

The strongest resume invariant is:

> Once an estimator runtime identity exists in a run, the orchestrator never launches that estimator again in that run.

The runtime identity remains:

```text
metadata/algorithms/<algorithm>/runtime_identity.json
```

The existing execution contract already treats this artifact as write-once. P2 must preserve that contract.

If a runtime identity exists but the associated run-status artifact is missing or inconsistent, the stage is not retried. It is `FAIL_ARTIFACT_INVALID` and requires a new run.

## 20. Append-only event ledger

Event directory:

```text
metadata/suite/events/
```

Event filenames are six-digit monotonically increasing integers:

```text
000001.json
000002.json
...
```

Each event is created with exclusive-create semantics and never replaced.

Event schema:

```text
lio_benchmark_suite_event/v1
```

Required fields:

```json
{
  "schema": "lio_benchmark_suite_event/v1",
  "event_id": 1,
  "invocation_id": "uuid",
  "event_type": "STAGE_STARTED",
  "stage_id": "runtime/fast_livo2",
  "timestamp": "...",
  "plan_sha256": "...",
  "command": [],
  "returncode": null,
  "observed_state": null,
  "reason_code": null
}
```

Supported event types include:

```text
SUITE_INVOCATION_STARTED
STAGE_STARTED
STAGE_FINISHED
STAGE_SKIPPED_VALID
STAGE_BLOCKED
SUITE_STOP_REQUESTED
SUITE_INVOCATION_FINISHED
```

Events may include diagnostic fields such as child process PID or detail text, but those fields are not used as artifact-truth state.

## 21. Exclusive executor lock

The lock path is:

```text
metadata/suite/suite.lock
```

Executor commands (`suite run` after initialization and `suite resume`) acquire:

```text
fcntl.flock(LOCK_EX | LOCK_NB)
```

Only one executor may act on a suite-managed run at a time.

If lock acquisition fails:

```text
status = BLOCKED
reason_code = BLOCKED_EXECUTOR_LOCKED
```

The process does not execute any stage.

The lock is kernel-owned. If the executor process exits or crashes, the lock is released automatically. The file's existence alone never means the suite is running.

`suite status` never acquires the exclusive lock and never writes to the run. It may attempt a nonblocking lock probe only to determine whether another process currently holds the executor lock.

## 22. `RUNNING` derivation

A stale unmatched `STAGE_STARTED` event does not imply `RUNNING`.

A stage is `RUNNING` only when both are true:

1. another executor currently holds the suite lock;
2. the latest active invocation contains a `STAGE_STARTED` event for that stage without a corresponding terminal stage event.

If the executor crashed and released the lock, status is re-derived from artifacts. The unmatched historical event remains lineage but does not create a permanent `RUNNING` state.

## 23. Graceful interruption contract

The first SIGINT or SIGTERM received by the suite executor requests a stage-boundary stop.

Rules:

1. record `SUITE_STOP_REQUESTED` append-only;
2. do not start another stage after the current stage finishes;
3. allow the currently active child stage to finish normally so it either produces a complete valid artifact or a normal stage failure;
4. record the resulting stage event;
5. record `SUITE_INVOCATION_FINISHED` with `outcome=INTERRUPTED_AT_STAGE_BOUNDARY`;
6. release the lock;
7. exit with code `130` for SIGINT or `143` for SIGTERM.

V1 intentionally prioritizes artifact integrity over immediate termination. A Ctrl-C received during a long estimator requests stop after that estimator attempt completes; it does not kill the estimator halfway through and leave ambiguous partial runtime evidence.

A later `suite resume` re-derives state and continues from the next safe stage.

Hard process termination (`SIGKILL`, power loss, kernel crash) cannot be made stage-boundary safe. On the next `status`/`resume`, existing artifacts are validated. Partial or inconsistent artifacts fail closed according to Section 18.

## 24. CLI contract

### 24.1. `suite run`

```bash
lio-benchmark suite run \
  --config <schema-v2-config> \
  --run-id <new-run-id>
```

Required behavior:

- validate config with existing manifest validation;
- require frozen dataset content SHA;
- refuse an existing run directory;
- initialize the run using existing run-manifest semantics;
- create `metadata/suite/plan.json` exactly once;
- acquire suite lock;
- execute until PASS, recoverable BLOCKED, terminal FAIL, or graceful interruption;
- print the run path and final derived suite state.

No algorithm/replay/calibration override flags are accepted.

If run initialization succeeds but plan creation itself fails before any stage starts, the run is not adopted or repaired by V1. The command fails closed and the user creates a new run ID.

### 24.2. `suite status`

```bash
lio-benchmark suite status --run <run>
```

Optional output-format flag:

```bash
--json
```

Status is strictly read-only. It must not:

- create directories;
- create events;
- refresh preflight;
- validate by mutating outputs;
- repair artifacts;
- acquire the exclusive executor lock;
- run ROS;
- execute subprocess stages.

If the run has no suite plan, status fails with a clear "not a suite-managed run" error rather than attempting to adopt a historical run.

### 24.3. `suite resume`

```bash
lio-benchmark suite resume --run <run>
```

Behavior:

- require existing immutable plan;
- validate plan/manifest fingerprint;
- acquire exclusive lock;
- re-derive all stage states from artifacts;
- if overall suite already `PASS`, execute zero stages and return success;
- if any terminal `FAIL` already exists, execute zero stages and report that failure;
- otherwise execute only `READY` stages according to deterministic order;
- never rerun an estimator with existing runtime identity;
- preserve all previous events/artifacts.

## 25. CLI exit codes

Executor commands use:

```text
0   = suite PASS (including already-complete PASS with zero execution)
1   = terminal suite FAIL
2   = recoverable suite BLOCKED
130 = SIGINT graceful stage-boundary interruption
143 = SIGTERM graceful stage-boundary interruption
```

`suite status` returns `0` when inspection itself succeeds regardless of whether the derived suite state is PASS/BLOCKED/FAIL. Machine consumers use `--json` to read the state.

## 26. Human-readable status view

Example:

```text
Benchmark Suite
────────────────────────────────────────────────────────
Run       greenhouse_suite_20260818_01
Profile   SAME_BAG_MAPPING_V1
Dataset   greenhouse_mid360_intake_v1_20260818_073506

Stage                                      Status
────────────────────────────────────────────────────────
snapshot                                   PASS
analyze_bag                                PASS
dataset_identity/pre                       PASS

preflight/fast_livo2                       PASS
preflight/fast_lio2                        PASS
preflight/kiss_icp                         PASS

runtime/fast_livo2                         PASS
runtime/fast_lio2                          PASS
runtime/kiss_icp                           PASS

dataset_identity/post                      PASS

trajectory/fast_livo2                      PASS
trajectory/fast_lio2                       PASS
trajectory/kiss_icp                        PASS

audit/trajectory_timestamps                PASS
audit/trajectory_frames                    PASS
audit/runtime_provenance                   PASS
audit/trajectory_coverage                   PASS

scan_manifest                              PASS
common_map_manifest                        PASS
unified_map/fast_livo2                     PASS
unified_map/fast_lio2                      PASS
unified_map/kiss_icp                       PASS
relative_se3                               PASS
same_bag_summary                           PASS
────────────────────────────────────────────────────────
SUITE                                      PASS
```

The JSON view includes stage ID, state, reason code, dependencies, recovery policy, and artifact evidence references.

## 27. Overall suite-state derivation

Priority:

1. if any stage is terminal `FAIL`, overall `FAIL`;
2. else if another executor currently owns the lock, overall `RUNNING`;
3. else if every required stage is `PASS`, overall `PASS`;
4. else if any stage is recoverably `BLOCKED`, overall `BLOCKED`;
5. else if at least one stage is `READY`, overall `READY`;
6. otherwise overall `PENDING`.

`BLOCKED_DEPENDENCY` caused by a terminal failed dependency coexists with the upstream `FAIL`, so overall state remains `FAIL` by priority.

## 28. Delegation to existing commands

The orchestrator must delegate actual work to already-established benchmark capabilities rather than reimplementing them.

The profile maps stage IDs to the existing command surfaces equivalent to:

```text
snapshot
analyze-bag
preflight
run --algorithm <alg>
standardize trajectory-from-run --algorithm <alg>
audit trajectory-timestamps
audit trajectory-frames
audit runtime-provenance
audit trajectory-coverage
standardize scan-manifest
standardize common-map-manifest
standardize map --algorithm <alg>
compare relative-se3
summarize same-bag
```

The implementation may call existing Python handlers/libraries through a thin internal runner when doing so preserves exactly the same command contract and evidence outputs. It must not fork a second implementation of the evaluator logic.

Every delegated stage command is recorded in its `STAGE_STARTED` event.

## 29. Compatibility

Existing public commands remain valid and behavior-compatible.

P2 is additive:

```text
lio-benchmark suite run
lio-benchmark suite status
lio-benchmark suite resume
```

Historical non-suite runs remain readable by existing tools but are not automatically adopted by the orchestrator.

The accepted Same-Bag Mapping V1 full-bag run and MID360 Bag Intake V1 artifacts remain untouched.

## 30. Repository acceptance contract

Repository acceptance must be achievable without ROS estimator execution and must cover the orchestration logic with pure-Python fixtures/mocks where appropriate.

Required contracts include:

### 30.1. Plan

- plan stage graph is deterministic;
- selected algorithm order is preserved;
- plan is non-overwritable;
- manifest mutation after plan creation is detected;
- dataset SHA is required and frozen;
- unsupported suite profile fails closed.

### 30.2. Status derivation

- status is read-only;
- valid completed artifact -> PASS;
- absent output + satisfied dependencies -> READY;
- partial output -> FAIL_PARTIAL_ARTIFACT;
- invalid/stale output -> FAIL;
- dependency failure -> BLOCKED_DEPENDENCY;
- raw frame audit `AVAILABLE` is accepted as evidence while runtime provenance must provide semantic `MATCH`;
- descriptive coverage values never become hidden pass/fail quality thresholds.

### 30.3. Runtime safety

- existing runtime identity always prevents estimator relaunch;
- PASS estimator is skipped on resume;
- FAIL_ALGORITHM is terminal and never rerun;
- BLOCKED_ENVIRONMENT without runtime identity is recheckable;
- one runtime failure does not stop later independently ready estimators in the same invocation;
- failed algorithm is never removed from the frozen selected set;
- global comparison stages block when the selected set is incomplete.

### 30.4. Dataset identity

- pre identity mismatch prevents all estimator starts;
- post identity mismatch blocks all downstream stages and makes the suite FAIL;
- pre/post identity artifacts are write-once;
- expected identity comes from frozen dataset contract.

### 30.5. Resume

- completed `REUSABLE_IF_VALID` stage executes zero commands;
- missing safe post-processing stage is executed on resume;
- completed estimator executes zero estimator commands on resume;
- terminal failed suite executes zero new commands on later resume;
- partial artifact is never auto-overwritten.

### 30.6. Events and lock

- event filenames are monotonic and append-only;
- event overwrite is refused;
- event PASS cannot override invalid artifact evidence;
- second executor is blocked by `flock`;
- stale unmatched start event without lock ownership does not produce RUNNING;
- status performs no writes.

### 30.7. Graceful interruption

- first SIGINT/SIGTERM requests stop-after-current-stage;
- no subsequent stage begins;
- completed current-stage evidence remains valid;
- resume starts from the next safe stage;
- already-completed estimator is not re-executed.

### 30.8. Compatibility

- existing Core Contracts remain green;
- legacy CLI parser and existing subcommands remain compatible;
- no estimator, map, or scientific threshold is silently changed by P2.

Repository completion marker:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_REPOSITORY_ACCEPTANCE=PASS
```

## 31. Target-machine acceptance strategy

P2 target acceptance should prove orchestration and recovery before spending another full 623-second three-estimator run.

Use one new target-local smoke config derived from the already accepted MID360 Bag Intake V1 dataset contract.

Frozen smoke replay:

```text
rate = 1.0
start_offset_s = 0.0
duration_s = 45.0
algorithms = fast_livo2, fast_lio2, kiss_icp
execution = sequential
```

The target config must use the accepted `dataset.json` through `dataset_file`, so the suite has a real non-null bag content SHA.

Target acceptance is split into three checks on one new smoke run.

### 31.1. Fresh-run orchestration + controlled interruption

Start:

```bash
lio-benchmark suite run \
  --config <smoke-config> \
  --run-id <unique-run-id>
```

During the first estimator runtime, request SIGINT after its `STAGE_STARTED` event is visible.

Expected behavior:

- the active estimator is allowed to finish normally;
- its runtime identity and run status freeze normally;
- `SUITE_STOP_REQUESTED` is appended;
- no next stage starts after the current stage finishes;
- executor exits `130`;
- run remains cleanly resumable;
- the completed estimator runtime identity SHA is recorded for the next check.

### 31.2. Resume to full smoke PASS

Run:

```bash
lio-benchmark suite resume --run <run>
```

Expected behavior:

- the completed estimator is skipped;
- its runtime identity remains byte-for-byte unchanged;
- remaining estimator runtimes execute sequentially exactly once;
- dataset post-identity matches pre-identity and accepted P1 bag hash;
- all formal downstream stages execute;
- strict common-map and Unified Map contracts pass;
- Relative SE(3) remains descriptive;
- canonical Same-Bag summary passes its existing readiness gate;
- suite reaches PASS.

Machine marker:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_CONTRACT=PASS
```

### 31.3. Resume an already-complete suite

Run `suite resume` again.

Expected behavior:

```text
ESTIMATOR_EXECUTED=0
STAGE_REEXECUTED=0
SUITE_ALREADY_COMPLETE=PASS
```

No scientific artifact is rewritten. The only permitted new evidence is invocation-level append-only suite event lineage documenting that the already-complete run was inspected and no stage execution was needed.

## 32. Full-bag promotion after P2 acceptance

A new automated 622.99-second full-bag run is deliberately not required for the first P2 target acceptance.

After P2 smoke acceptance is frozen, the next promotion step may run the accepted full-bag Same-Bag Mapping V1 configuration through `suite run` using the same frozen MID360 dataset contract.

That promotion is evidence that orchestration scales to the full accepted baseline; it is not part of the code-completion gate for P2 V1.

## 33. Stop condition

Implementation work for this spec stops when:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_REPOSITORY_ACCEPTANCE = PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_MACHINE_ACCEPTANCE = PENDING
```

At that point the repository must contain a target-machine verification runbook and a Codex handoff prompt for the 45-second controlled-interruption/resume acceptance.

No P3 visualization/README work and no new algorithm adapter work begins as part of P2.

## 34. Final V1 invariant

The defining invariant of P2 is:

> Given one frozen benchmark configuration and one frozen bag content identity, Benchmark Suite Orchestrator V1 can execute the Same-Bag Mapping V1 stage graph, survive a stage-boundary interruption, and resume using only validated artifact-derived state, while never launching an estimator again after that estimator has established a runtime identity in the run.
