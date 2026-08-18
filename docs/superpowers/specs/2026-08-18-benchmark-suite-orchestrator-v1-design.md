# Benchmark Suite Orchestrator V1 Design

Date: 2026-08-18
Branch: `feat/lio-baseline-suite`

## 1. Purpose

`Benchmark Suite Orchestrator V1` turns the already-validated Same-Bag Mapping Benchmark V1 command chain into one auditable, resumable execution surface without changing the scientific meaning of any existing evaluator.

The orchestrator is a coordination layer, not a new benchmark algorithm. It must:

1. freeze one immutable suite plan from one frozen experiment manifest;
2. derive stage state from run artifacts and validators rather than a mutable status database;
3. execute only dependency-ready stages that are safe to execute;
4. never re-execute an estimator after that estimator has established a run-local runtime identity;
5. continue independent estimator attempts when another estimator fails during the same invocation;
6. never silently remove a failed/blocked algorithm from the frozen comparison set;
7. block comparison-wide downstream stages when the frozen selected set cannot be completed;
8. preserve append-only operational lineage;
9. support stage-boundary interruption and safe resume;
10. keep estimator and post-processing execution sequential in V1.

Public flow:

```bash
lio-benchmark suite run \
  --config /absolute/path/to/experiment.json \
  --run-id greenhouse_suite_20260818_01

lio-benchmark suite status \
  --run /absolute/path/to/run

lio-benchmark suite resume \
  --run /absolute/path/to/run
```

`run` creates one new benchmark run and executes the suite. `status` is read-only. `resume` re-derives every stage from artifacts and executes only work that is both missing and safe.

## 2. Scope

V1 supports exactly one profile:

```text
SAME_BAG_MAPPING_V1
```

Initial repository and target-machine acceptance use exactly the algorithms frozen in the accepted three-algorithm profile:

```text
fast_livo2
fast_lio2
kiss_icp
```

The profile reuses the existing Same-Bag Mapping V1 stages. It does not add algorithm-specific behavior.

## 3. Non-goals

V1 does not implement:

- Point-LIO, DLIO, Leg-KILO, LIO-SAM, GLIM, Faster-LIO, SLICT, or any new adapter acceptance;
- Representative Window selection/gating inside the suite;
- Failure-Mode Audit automation;
- estimator or post-processing parallelism;
- `--force`, `--overwrite`, `--skip`, `--jobs`, `--parallel`, `--ignore-failure`, or `--rerun-algorithm`;
- invocation-time algorithm selection;
- invocation-time replay/calibration/topic/map/tolerance overrides;
- automatic deletion, repair, replacement, or overwriting of partial scientific artifacts;
- retrying `FAIL_ALGORITHM` inside the same run;
- GT metrics, algorithm ranking, report/demo/README generation, multi-bag orchestration, or repeated-trial statistics;
- a generic workflow engine for arbitrary user DAGs.

## 4. Scientific boundary

The orchestrator preserves the accepted Same-Bag labels:

```text
benchmark_profile = DEFAULT_ADAPTED
scientific_status = DESCRIPTIVE_NO_GROUND_TRUTH
performance_status = SINGLE_RUN_DESCRIPTIVE
Unified Map policy = STRICT_COMMON_INTERSECTION
Relative SE(3) = PAIRWISE_DISAGREEMENT
```

KISS-ICP remains a LiDAR-only control; FAST-LIVO2 and FAST-LIO2 remain LiDAR+IMU methods. Suite `PASS` means the frozen workflow and evidence contracts completed. It does not mean an estimator is accurate or superior.

Trajectory coverage remains descriptive. Coverage stage `PASS` means the audit produced valid evidence; no new hidden thresholds are introduced for output rate, gap count, first lag, end delta, or count ratio.

Raw frame evidence and semantic frame compatibility remain distinct:

```text
trajectory_frame_audit.csv status = AVAILABLE
runtime_provenance.csv status = MATCH
runtime_provenance.csv frame_contract_status = MATCH
```

The orchestrator must never require raw frame-audit `status == MATCH`.

## 5. Architectural principle: artifact-derived state

There is no mutable authoritative `state.json`.

```text
run artifact(s)
    +
validator
    ↓
derived stage state
    ↓
scheduler decision
```

Append-only events record attempts and lineage but never override artifact truth. A `STAGE_FINISHED` event with return code `0` does not itself make a stage `PASS`.

## 6. Modules and responsibilities

Create four focused modules:

```text
benchmark_base/lib/
├── suite_plan.py
├── suite_status.py
├── suite_events.py
└── suite_orchestrator.py
```

### 6.1. `suite_plan.py`

- defines the fixed V1 stage IDs, dependencies, recovery policies, and deterministic scheduling priority;
- builds and validates immutable `plan.json`;
- validates the current run manifest fingerprint against the plan;
- contains no ROS/evaluator execution.

### 6.2. `suite_status.py`

- reads plan/manifest/artifacts;
- invokes pure validators where available;
- classifies every stage as `PENDING`, `READY`, `RUNNING`, `PASS`, `BLOCKED`, or `FAIL`;
- attaches stable reason codes and artifact references;
- derives overall suite state;
- is strictly read-only.

### 6.3. `suite_events.py`

- creates one immutable JSON event per event;
- allocates monotonically increasing event filenames while the executor owns the lock;
- validates event schema;
- reads lineage for diagnostics/active-stage display;
- never treats events as scientific truth.

### 6.4. `suite_orchestrator.py`

- acquires/releases suite lock;
- creates/validates plan;
- derives state;
- selects the next safe stage by fixed priority;
- delegates to existing benchmark commands/handlers;
- records events;
- applies failure/recovery policy;
- implements stage-boundary graceful stop;
- never reimplements estimator, trajectory, map, Relative SE(3), audit, or summary algorithms.

## 7. Run-local suite layout

Suite-managed runs add:

```text
metadata/suite/
├── plan.json
├── suite.lock
├── dataset_identity_pre.json
├── dataset_identity_post.json
└── events/
    ├── 000001.json
    ├── 000002.json
    └── ...
```

`plan.json`, both dataset-identity records, and every event file are write-once. `suite.lock` contents are never authoritative.

## 8. Immutable plan contract

Schema:

```text
lio_benchmark_suite_plan/v1
```

Required shape includes:

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
  "selected_algorithms": ["fast_livo2", "fast_lio2", "kiss_icp"],
  "execution_policy": "SEQUENTIAL_ESTIMATORS",
  "failure_policy": "CONTINUE_INDEPENDENT_BLOCK_DEPENDENTS",
  "state_policy": "ARTIFACT_DERIVED",
  "event_policy": "APPEND_ONLY",
  "lock_policy": "PROCESS_EXCLUSIVE_FLOCK",
  "stages": []
}
```

Selected-algorithm order is copied from the frozen resolved run manifest and never reordered. Stage graph and scheduling priority are materialized in `stages`.

Plan overwrite is refused. On resume, current `manifest.json` must fingerprint exactly to `manifest_sha256`. Mismatch is terminal:

```text
FAIL / FAIL_MANIFEST_MUTATION
```

A new run is required rather than editing the plan.

## 9. Dataset identity precondition

The resolved dataset must carry a non-empty 64-hex SHA-256 at:

```text
dataset.sha256
```

For MID360 Bag Intake V1 this is the aggregate `bag_content_sha256` over `metadata.yaml` plus ordered ROS 2 storage files.

P2 does not require `dataset_file` specifically; a registry dataset is allowed only if it provides the same valid frozen content identity contract.

Missing/malformed identity blocks suite execution before estimator startup:

```text
BLOCKED / BLOCKED_INPUT_IDENTITY_UNAVAILABLE
```

## 10. Dataset identity gates

### 10.1. Pre-execution gate

After setup/preflight observations and before any estimator starts, recompute bag identity with the P1 content-identity helper and write once:

```text
metadata/suite/dataset_identity_pre.json
```

Required evidence includes expected/observed aggregate SHA, metadata SHA, ordered storage-file fingerprints, capture time, and status.

Mismatch is terminal:

```text
FAIL / FAIL_INPUT_MUTATION
```

No estimator starts.

### 10.2. Post-execution gate

Post identity is computed only after every selected runtime is in a non-recheckable runtime terminal outcome:

```text
PASS
or
FAIL_ALGORITHM
```

If any selected runtime remains `BLOCKED_ENVIRONMENT`, post identity remains `PENDING`/`BLOCKED_DEPENDENCY`; no trajectory/map/comparison stage starts.

Write once:

```text
metadata/suite/dataset_identity_post.json
```

Observed post SHA must equal both plan expectation and pre-execution observed SHA. Mismatch is terminal `FAIL_INPUT_MUTATION` and all downstream stages become `BLOCKED_DEPENDENCY`.

V1 intentionally hashes the multi-gigabyte bag once before the estimator group and once after it, not before every sequential estimator.

## 11. Stage states

Exactly:

```text
PENDING
READY
RUNNING
PASS
BLOCKED
FAIL
```

- `PENDING`: required PASS dependencies are not complete and none has failed/blocked the stage;
- `READY`: required PASS dependencies are satisfied, required operational gates allow execution, and no conflicting owned artifact exists;
- `RUNNING`: an executor currently owns the lock and its active invocation identifies this stage as started without a terminal stage event;
- `PASS`: owned authoritative artifacts exist and validate;
- `BLOCKED`: stage itself is not terminal-failed, but execution is currently disallowed;
- `FAIL`: terminal contract violation or non-retryable failed attempt.

Every BLOCKED/FAIL includes a stable reason code.

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

Human-readable detail may accompany a code but machine acceptance keys off the code.

## 13. Recovery policies

### 13.1. `REUSABLE_IF_VALID`

For deterministic post-processing/scientific outputs:

```text
complete + valid       -> PASS, never rerun
all owned absent       -> READY when dependencies permit
partial                -> FAIL_PARTIAL_ARTIFACT
complete but invalid   -> FAIL_ARTIFACT_INVALID
complete but stale     -> FAIL_ARTIFACT_STALE
```

No automatic deletion or overwrite.

### 13.2. `RECHECKABLE_BEFORE_RUNTIME`

Only for per-algorithm preflight/environment observations. `BLOCKED_ENVIRONMENT` may be re-evaluated on `resume` only while that algorithm has no runtime identity.

The existing preflight JSON may be refreshed because it is an operational environment observation, not scientific output. Every attempt is preserved in append-only suite events.

### 13.3. `SINGLE_RUNTIME_ATTEMPT`

For estimator runtime stages. Once:

```text
metadata/algorithms/<alg>/runtime_identity.json
```

exists, that estimator is never launched again in that run.

```text
identity absent + runnable environment       -> READY
identity absent + BLOCKED_ENVIRONMENT        -> BLOCKED, recheckable
identity exists + run status PASS            -> PASS
identity exists + run status FAIL_ALGORITHM  -> FAIL
identity exists + missing/inconsistent status-> FAIL_ARTIFACT_INVALID
```

Retrying `FAIL_ALGORITHM` requires a new run ID.

## 14. Fixed stage IDs

```text
snapshot
analyze_bag
preflight/<algorithm_id>
dataset_identity/pre
runtime/<algorithm_id>
dataset_identity/post
trajectory/<algorithm_id>
audit/trajectory_timestamps
audit/trajectory_frames
audit/runtime_provenance
audit/trajectory_coverage
scan_manifest
common_map_manifest
unified_map/<algorithm_id>
relative_se3
same_bag_summary
```

Overall suite state is derived and is not a stored stage artifact.

## 15. Dependencies and operational gates

### 15.1. Setup and preflight

```text
snapshot                <- plan
analyze_bag             <- plan
preflight/<alg>         <- snapshot + analyze_bag

dataset_identity/pre    <- snapshot + analyze_bag
```

The pre-identity stage is logically safe once snapshot/analyze-bag pass, but fixed scheduling priority (Section 16) attempts every selected preflight first. This avoids an ambiguous dependency on a recoverably blocked preflight while still ensuring the operator sees the full preflight set before runtime execution.

Preflight-group operational rule before runtimes:

- every selected preflight must have been attempted in the current/latest usable environment;
- an individual runtime is eligible only if its own preflight is PASS;
- `BLOCKED_ENVIRONMENT` on one algorithm does not invalidate pre-identity and does not prevent other PASS-preflight algorithms from being attempted in the same invocation;
- a terminal preflight contract failure is a suite terminal failure.

### 15.2. Runtime group

```text
runtime/<alg> <- dataset_identity/pre PASS + preflight/<alg> PASS
```

Runtime stages are independent in outcome but execute sequentially in frozen algorithm order. A `FAIL_ALGORITHM` does not stop later independently READY estimator runtimes in the same invocation.

### 15.3. Post-runtime identity

```text
dataset_identity/post
  operational gate: every selected runtime is PASS or FAIL_ALGORITHM
```

It may run even if one runtime failed, to preserve evidence that the source bag remained immutable during the attempted estimator group. It must not run while any runtime remains recoverably `BLOCKED_ENVIRONMENT`.

### 15.4. Trajectories

```text
trajectory/<alg> <- dataset_identity/post PASS + runtime/<alg> PASS
```

A failed selected runtime therefore prevents a complete all-algorithm trajectory set.

### 15.5. Global audits

```text
audit/trajectory_timestamps <- all trajectory/<alg> PASS
audit/trajectory_frames     <- all trajectory/<alg> PASS
audit/trajectory_coverage   <- all trajectory/<alg> PASS

audit/runtime_provenance    <- all runtime/<alg> PASS
                              + all trajectory/<alg> PASS
                              + audit/trajectory_frames PASS
```

### 15.6. Map/comparison

```text
scan_manifest       <- all trajectory/<alg> PASS
                       + dataset_identity/post PASS

common_map_manifest <- scan_manifest PASS
                       + all trajectory/<alg> PASS

unified_map/<alg>   <- common_map_manifest PASS
                       + trajectory/<alg> PASS
```

### 15.7. Relative SE(3)

Logical dependencies:

```text
relative_se3 <- all trajectory/<alg> PASS
                + audit/trajectory_timestamps PASS
                + audit/trajectory_frames PASS
                + audit/runtime_provenance PASS
```

It is logically independent of Unified Maps, but V1 scheduler executes it after all Unified Maps to preserve accepted clean-run ordering.

### 15.8. Summary

```text
same_bag_summary <- all runtime/<alg> PASS
                    + all trajectory/<alg> PASS
                    + all unified_map/<alg> PASS
                    + relative_se3 PASS
                    + all four global audits PASS
```

The existing Same-Bag summary readiness gate remains authoritative for runtime identity, performance evidence, trajectory availability, strict-map policy/counts, and point count. P2 does not duplicate or weaken it.

## 16. Deterministic scheduling priority

When multiple stages are executable, V1 selects exactly in this order:

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

There is no concurrent execution in V1.

## 17. Stage artifact ownership and validators

The orchestrator must know which outputs belong to each stage before deciding that a missing/partial/valid state exists. Compatibility aliases/symlinks may be validated additionally but are not allowed to replace the canonical owned artifacts below.

### 17.1. Setup/runtime/trajectory

| Stage | Canonical owned artifacts | Minimum PASS contract |
|---|---|---|
| `snapshot` | `metadata/environment_snapshot.json` | valid JSON object produced for this run; do not rewrite on resume |
| `analyze_bag` | `metrics/bag_analysis.json` | valid existing bag-analysis schema/evidence |
| `preflight/<alg>` | `metadata/algorithms/<alg>/preflight.json` | current preflight says runnable/PASS; `BLOCKED_ENVIRONMENT` is recheckable only without runtime identity |
| `dataset_identity/pre` | `metadata/suite/dataset_identity_pre.json` | expected SHA == observed SHA and storage/metadata fingerprints validate |
| `runtime/<alg>` | `metadata/algorithms/<alg>/runtime_identity.json`, `metadata/run_<alg>.json`, `metrics/runtime/<alg>.json` | identity `FROZEN`, run status `PASS`, performance evidence valid; raw output remains available to trajectory stage |
| `dataset_identity/post` | `metadata/suite/dataset_identity_post.json` | observed SHA == plan expected SHA == pre observed SHA |
| `trajectory/<alg>` | `standardized/trajectories/<alg>.csv`, `metadata/algorithms/<alg>/trajectory_standardization.json` | trajectory parses under existing strict trajectory contract; metadata matches alg/output/sample semantics |

For runtime, the presence of runtime identity plus a missing/inconsistent run-status or performance artifact is not `READY`; it is terminal invalid evidence because estimator relaunch is forbidden.

### 17.2. Audit artifacts

| Stage | Canonical owned artifacts | Minimum PASS contract |
|---|---|---|
| `audit/trajectory_timestamps` | `metrics/trajectory_timestamp_audit/<alg>.csv` + `metadata/trajectory_timestamp_audit/<alg>.json` for every selected algorithm | complete selected set, valid audit schema, no timestamp-regression contract violation; do not turn descriptive cadence into a quality threshold |
| `audit/trajectory_frames` | `metadata/frame_audit/<alg>.json` for every selected algorithm + `metrics/trajectory_frame_audit.csv` | raw evidence available for complete selected set; evidence-layer `AVAILABLE` is valid |
| `audit/runtime_provenance` | `metadata/runtime_provenance/<alg>.json` for every selected algorithm + `metrics/runtime_provenance.csv` | complete selected set; each formal row `status=MATCH`, `frame_contract_status=MATCH`, runtime identity evidence frozen/matched |
| `audit/trajectory_coverage` | `metadata/trajectory_coverage/<alg>.json` for every selected algorithm + `metrics/trajectory_coverage.csv` | complete selected set and valid descriptive evidence; no hidden gap/rate threshold |

If a global audit command creates only part of its owned selected-algorithm set, the stage is `FAIL_PARTIAL_ARTIFACT`; V1 does not rerun it over the partial outputs.

### 17.3. Scan/map/comparison/summary artifacts

| Stage | Canonical owned artifacts | Minimum PASS contract |
|---|---|---|
| `scan_manifest` | `standardized/map_sampling/selected_scans.csv`, `standardized/map_sampling/metadata.json` | non-empty deterministic selection; metadata agrees with frozen replay/topic/scan step |
| `common_map_manifest` | `standardized/map_sampling/common_matched_scans.csv`, `standardized/map_sampling/common_matched_metadata.json` | existing strict common-map validator passes all selected-trajectory and selected-scan fingerprints |
| `unified_map/<alg>` | `standardized/maps/<alg>/unified/map.ply`, `standardized/maps/<alg>/unified/metadata.json` | strict common-manifest SHA matches; policy `STRICT_COMMON_INTERSECTION`; selected>0; matched=selected; unmatched=0; point_count>0 |
| `relative_se3` | `metrics/relative_se3/metadata.json`, `normalized_motion.csv`, `pairwise_samples.csv`, `pairwise_summary.csv`, `onset_thresholds.csv` | output dir complete; requested/eligible algorithms equal frozen selected set; blocked set empty; terminology remains `PAIRWISE_DISAGREEMENT`; ground truth `NONE` |
| `same_bag_summary` | `reports/algorithm_io_matrix.csv`, `reports/algorithm_io_matrix.md`, `metrics/runtime_performance.csv`, `reports/same_bag_mapping_v1.json` | complete canonical package and existing readiness contract PASS |

`same-bag-finalize` is not a normal P2 stage. It remains a specific append-only recovery tool for the already-documented historical premature-summary incident.

## 18. Failure policy

Frozen policy:

```text
CONTINUE_INDEPENDENT_BLOCK_DEPENDENTS
```

### 18.1. Runtime failure

If:

```text
fast_livo2 PASS
fast_lio2  FAIL_ALGORITHM
kiss_icp   not yet attempted
```

then the same invocation still attempts KISS-ICP if it is READY. The frozen selected set remains all three algorithms.

After terminal outcomes such as:

```text
fast_livo2 PASS
fast_lio2  FAIL
kiss_icp   PASS
```

comparison-wide downstream stages are `BLOCKED_DEPENDENCY`, and overall suite is `FAIL`.

### 18.2. Recoverable environment block

`BLOCKED_ENVIRONMENT` without runtime identity may be rechecked later. Other independently READY estimator runtimes may execute in the same invocation, but no post-runtime processing begins until every runtime is PASS or FAIL_ALGORITHM.

If there is no terminal failure, overall suite is `BLOCKED` and may be resumed after the environment is repaired.

### 18.3. Later resume after terminal failure

Once a previous invocation has closed with a terminal `FAIL_ALGORITHM`, `FAIL_INPUT_MUTATION`, `FAIL_MANIFEST_MUTATION`, partial/stale/invalid artifact failure, or another terminal contract failure, later `suite resume` executes zero new stages and requires a new run.

The continue-independent policy applies during the invocation that first observes the failure; it does not authorize new experimental execution after a failed run has already been revisited later.

## 19. No-overwrite rule

For every `REUSABLE_IF_VALID` stage, status is determined from the complete owned-artifact set in Section 17.

```text
complete + valid     -> PASS / skip
all owned absent     -> READY when dependencies/gates allow
some owned exist     -> FAIL_PARTIAL_ARTIFACT
complete but invalid -> FAIL_ARTIFACT_INVALID
complete but stale   -> FAIL_ARTIFACT_STALE
```

The orchestrator never invokes a stage command if any canonical artifact owned by that stage already exists but the validator cannot prove a complete accepted contract.

This rule is especially important for current evaluators that can otherwise write directly to fixed output paths.

## 20. Runtime identity invariant

> Once an estimator runtime identity exists in a run, P2 never launches that estimator again in that run.

If identity exists but associated status/evidence is inconsistent, the runtime stage fails closed. It is never repaired by estimator re-execution.

## 21. Append-only event ledger

Directory:

```text
metadata/suite/events/
```

Filenames:

```text
000001.json
000002.json
...
```

Schema:

```text
lio_benchmark_suite_event/v1
```

Required fields include:

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

Files use exclusive-create semantics and are never overwritten. Events are lineage only.

## 22. Exclusive executor lock

Path:

```text
metadata/suite/suite.lock
```

Executor commands acquire:

```text
fcntl.flock(LOCK_EX | LOCK_NB)
```

A second executor performs no work and reports:

```text
BLOCKED / BLOCKED_EXECUTOR_LOCKED
```

Kernel lock ownership, not lock-file existence, defines active execution. Process crash releases the lock automatically.

`status` never acquires the exclusive executor lock and never creates a lock file. It may open an already-existing lock file without creation and perform a non-mutating/nonblocking probe to detect another owner.

## 23. RUNNING derivation

A historical unmatched `STAGE_STARTED` event is not enough.

A stage is RUNNING only if:

1. another executor currently owns the suite lock; and
2. the latest active invocation identifies that stage as started without terminal stage event.

After executor crash/lock release, status falls back to artifact-derived state; unmatched events remain lineage only.

## 24. Graceful interruption

First SIGINT/SIGTERM requests stage-boundary stop:

1. set a stop-request flag and preserve a `SUITE_STOP_REQUESTED` event (the handler may defer file I/O until safe Python control returns);
2. do not start another stage;
3. allow currently active child stage to finish normally;
4. validate/record that stage result;
5. append `SUITE_INVOCATION_FINISHED` with `INTERRUPTED_AT_STAGE_BOUNDARY`;
6. release lock;
7. exit `130` for SIGINT or `143` for SIGTERM.

V1 prioritizes artifact integrity over immediate termination. Ctrl-C during a long estimator means “finish this estimator attempt, then stop,” not “kill it halfway and leave ambiguous execution evidence.”

`SIGKILL`, power loss, and kernel crash cannot be stage-boundary safe. Next `status/resume` validates whatever artifacts remain; partial/inconsistent evidence fails closed under Section 19.

## 25. CLI contract

### 25.1. `suite run`

```bash
lio-benchmark suite run \
  --config <schema-v2-config> \
  --run-id <new-run-id>
```

It must:

- validate config through existing manifest validation;
- require frozen dataset SHA;
- refuse an existing run directory;
- initialize using existing run-manifest semantics;
- create plan once;
- acquire lock;
- execute until PASS, recoverable BLOCKED, terminal FAIL, or graceful interruption;
- print run path and derived final state.

No algorithm/replay/calibration overrides are accepted.

If run initialization succeeds but plan creation fails before any stage starts, V1 does not adopt/repair that run; use a new run ID.

### 25.2. `suite status`

```bash
lio-benchmark suite status --run <run>
lio-benchmark suite status --run <run> --json
```

It is strictly read-only: no directories/events/preflight refresh/repair/ROS/subprocess stages. A run without `metadata/suite/plan.json` fails as “not a suite-managed run”; V1 does not adopt historical runs.

JSON status exposes stage ID, state, reason code, dependencies, recovery policy, and artifact references.

### 25.3. `suite resume`

```bash
lio-benchmark suite resume --run <run>
```

It must:

- require/validate immutable plan and manifest SHA;
- acquire lock;
- re-derive all stages;
- execute zero stages when suite already PASS;
- execute zero stages when a previous invocation already left terminal FAIL;
- otherwise execute only READY stages by Section 16;
- never rerun an estimator with runtime identity;
- preserve all prior artifacts/events.

## 26. Exit codes

Executor commands:

```text
0   PASS, including already-complete PASS with zero stage execution
1   terminal FAIL
2   recoverable BLOCKED
130 SIGINT stage-boundary interruption
143 SIGTERM stage-boundary interruption
```

`status` returns `0` if inspection itself succeeds regardless of derived suite state; machine consumers use `--json`.

## 27. Overall suite-state priority

1. any terminal stage FAIL -> overall `FAIL`;
2. else active external executor lock -> `RUNNING`;
3. else all required stages PASS -> `PASS`;
4. else any recoverable blocking condition -> `BLOCKED`;
5. else at least one stage READY -> `READY`;
6. else `PENDING`.

`BLOCKED_DEPENDENCY` caused by an upstream terminal failure coexists with that upstream FAIL, so overall remains FAIL.

## 28. Human-readable status example

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
preflight/fast_livo2                       PASS
preflight/fast_lio2                        PASS
preflight/kiss_icp                         PASS
dataset_identity/pre                       PASS
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
audit/trajectory_coverage                  PASS
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

## 29. Delegation to existing capabilities

P2 schedules existing capabilities equivalent to:

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

Implementation may use existing Python handlers/libraries through a thin internal runner when it preserves identical command/evidence semantics. It must not fork a second evaluator implementation. Each delegated command is recorded in `STAGE_STARTED` lineage.

## 30. Compatibility

P2 is additive. Existing CLI behavior remains valid. Historical non-suite runs remain usable by existing tools but are not automatically adopted. The accepted Same-Bag full-bag run and P1 MID360 intake artifacts are untouched.

## 31. Repository acceptance

Repository acceptance is ROS-estimator-independent and must cover:

### Plan

- deterministic stage graph/order;
- algorithm order preserved;
- plan non-overwritable;
- manifest mutation detected;
- dataset SHA required/frozen;
- unsupported profile fails closed.

### Status/artifact validation

- status is read-only;
- complete valid artifacts -> PASS;
- absent owned outputs + ready dependencies -> READY;
- partial -> FAIL_PARTIAL_ARTIFACT;
- invalid/stale -> FAIL;
- dependency failure -> BLOCKED_DEPENDENCY;
- frame evidence `AVAILABLE` accepted while runtime provenance semantic status must be MATCH;
- coverage values remain descriptive rather than threshold gates;
- Relative SE(3) requires complete frozen selected set for formal suite PASS.

### Runtime safety/failure policy

- any existing runtime identity prevents relaunch;
- PASS estimator skipped on resume;
- FAIL_ALGORITHM terminal and never rerun;
- BLOCKED_ENVIRONMENT without identity recheckable;
- one runtime failure does not stop later independently READY runtimes in same invocation;
- selected algorithm set never shrinks;
- global stages block on incomplete selected set;
- later resume after terminal failed invocation executes zero work.

### Dataset identity

- missing dataset SHA blocks suite before estimator;
- pre mismatch prevents all estimator starts;
- post mismatch blocks downstream and fails suite;
- pre/post records write-once;
- post does not run while any runtime is recoverably blocked.

### Resume/no-overwrite

- completed stage executes zero command;
- missing safe post-processing stage executes on resume;
- completed estimator executes zero estimator commands;
- partial output never auto-overwritten;
- canonical summary never generated prematurely.

### Events/lock/RUNNING

- event names monotonic and append-only;
- overwrite refused;
- event success cannot override invalid artifact;
- second executor blocked by flock;
- stale unmatched event without lock is not RUNNING;
- status performs zero writes.

### Graceful interruption

- first signal requests stop-after-current-stage;
- no later stage begins;
- current stage completes/validates;
- resume begins from next safe stage;
- completed estimator is not re-executed.

### Compatibility

- all existing Core Contracts remain green;
- legacy CLI remains compatible;
- no estimator/map/scientific threshold changes.

Repository marker:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_REPOSITORY_ACCEPTANCE=PASS
```

## 32. Target-machine acceptance

Use a new target-local 45-second smoke config derived from the already accepted MID360 Bag Intake V1 `dataset.json` through `dataset_file`.

Frozen target profile:

```text
rate = 1.0
start_offset_s = 0.0
duration_s = 45.0
algorithms = fast_livo2, fast_lio2, kiss_icp
execution = sequential
```

### 32.1. Controlled interruption

Start `suite run`. Once the first estimator has a `STAGE_STARTED` event, send SIGINT to the suite executor.

Required behavior:

- active estimator finishes normally;
- runtime identity/status freeze normally;
- stop-request event is appended;
- no next stage starts after current stage;
- executor exits 130;
- run is resumable;
- record SHA of completed estimator runtime identity.

### 32.2. Resume to smoke PASS

Run `suite resume`.

Required behavior:

- completed estimator skipped and runtime-identity SHA unchanged;
- remaining estimators execute sequentially exactly once;
- dataset post identity equals pre identity and accepted frozen bag SHA;
- all formal audits/maps/Relative SE(3)/summary complete;
- strict common-map contract passes;
- Relative SE(3) remains descriptive;
- canonical summary readiness passes;
- suite reaches PASS.

Machine marker:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_CONTRACT=PASS
```

### 32.3. Resume already-complete suite

Run `suite resume` again.

Required evidence:

```text
ESTIMATOR_EXECUTED=0
STAGE_REEXECUTED=0
SUITE_ALREADY_COMPLETE=PASS
```

No scientific artifact is rewritten. Only invocation-level append-only lineage may be added to record the no-op resume; it must not create new scientific stage outputs.

## 33. Full-bag promotion

A new 622.99-second × three-estimator automated run is deliberately not required for initial P2 code acceptance. After 45-second target acceptance is frozen, a later promotion may execute the already accepted full-bag Same-Bag profile through `suite run` using the same frozen MID360 dataset contract.

## 34. Stop condition

Implementation stops at:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_REPOSITORY_ACCEPTANCE = PASS
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_MACHINE_ACCEPTANCE = PENDING
```

At that point the repository contains a target-machine verification runbook and Codex handoff for Section 32. No P3 visualization/README work and no new algorithm adapter work begins in P2.

## 35. Final invariant

> Given one frozen benchmark configuration and one frozen bag content identity, Benchmark Suite Orchestrator V1 can execute the Same-Bag Mapping V1 stage graph, survive a stage-boundary interruption, and resume using validated artifact-derived state, while never launching an estimator again after that estimator has established a runtime identity in the run.
