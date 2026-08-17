# Failure-Mode Audit V1 Design

Date: 2026-08-17

## Goal

Use the already accepted Representative Window V1 child runs as immutable evidence to determine the temporal ordering between trajectory temporal-coverage degradation and existing Relative SE(3) descriptive disagreement onsets. V1 focuses interpretation on:

- `high_angular_motion` / `kiss_icp`
- `steady_translation_candidate` / `fast_livo2`

The audit must stop at target-machine acceptance. It must not rerun estimators, replay the 623 s bag, reselect windows, recompute Relative SE(3), or mutate child runs.

## Scientific boundary

There is no ground truth. The audit therefore reports temporal association only.

Allowed terms:

- temporal coverage degradation
- Relative SE(3) pairwise disagreement
- sustained descriptive onset
- temporal ordering / lead / lag

Forbidden interpretations:

- estimator failure time
- drift onset as ground truth
- accuracy-loss time
- causal attribution
- objective algorithm ranking

All outputs retain `DESCRIPTIVE_NO_GROUND_TRUTH` semantics.

## Immutable inputs

For each of the four child runs, V1 reads only:

- `manifest.json`
- `metrics/trajectory_coverage.csv`
- `standardized/trajectories/<algorithm>.csv`
- `metrics/relative_se3/metadata.json`
- `metrics/relative_se3/onset_thresholds.csv`

The source ROS bag is not opened. Existing coverage and Relative SE(3) artifacts are evidence, not regenerated products.

## Batch contract

The CLI accepts:

```text
lio-benchmark audit failure-mode --run-root <root> --batch-id <representative-window-batch-id>
```

It resolves exactly these child run names:

```text
<batch-id>_initialization
<batch-id>_high_angular_motion
<batch-id>_geometric_degeneracy_candidate
<batch-id>_steady_translation_candidate
```

The audit writes a new sibling directory:

```text
<run-root>/<batch-id>_failure_mode_audit_v1/
```

An existing output directory is a hard error. Child runs are never modified.

## Coverage-degradation event definition

The existing coverage layer defines a large interval as greater than `1.5 x median period`. V1 reuses that frozen multiplier rather than introducing a new tuning parameter.

For each standardized trajectory interval `(t_prev, t_curr)`, the audit uses the already recorded input-LiDAR median period from `trajectory_coverage.csv` and identifies an input-relative coverage-degradation event when:

```text
t_curr - t_prev > 1.5 * input_lidar_median_period_s
```

The event onset is the first instant at which that interval crosses the existing large-gap criterion:

```text
t_degradation = t_prev + 1.5 * input_lidar_median_period_s
```

Each event records interval duration, threshold, previous/current trajectory timestamps, and an estimated number of skipped input cadence slots for descriptive context. No timestamps are sorted, repaired, filled, or retimed.

## Relative SE(3) onset definition

V1 does not recompute pairwise motion. It reads the existing `onset_thresholds.csv`, whose thresholds, 0.1 s common sampling and three-sample sustained-onset rule are already frozen by Relative SE(3) V1.

For a target algorithm, every crossed onset from a pair containing that algorithm is retained. The earliest crossed onset is used only as a compact summary. It is not labeled as a failure onset.

## Temporal relation

For each crossed Relative SE(3) onset involving a target algorithm, V1 records:

- first coverage-degradation onset in that algorithm/window
- nearest degradation event at or before the disagreement onset
- nearest degradation event after the disagreement onset
- signed `divergence_onset - first_coverage_degradation_onset`
- signed lead from nearest preceding degradation event
- lag to nearest following degradation event

The summary relation is one of:

```text
COVERAGE_DEGRADATION_FIRST
DESCRIPTIVE_DIVERGENCE_FIRST
SAME_TIMESTAMP
NO_COVERAGE_DEGRADATION_EVENT
NO_CROSSED_RELATIVE_SE3_ONSET
```

No tolerance is added for the classification. Raw signed deltas remain the primary evidence.

## Outputs

The immutable audit directory contains:

```text
metadata.json
coverage_context.csv
coverage_events.csv
onset_relations.csv
target_summary.csv
FAILURE_MODE_AUDIT_V1.md
```

`coverage_context.csv` contains all four windows x three algorithms so the two focus cases retain batch context. `coverage_events.csv` contains all input-relative degradation events. `onset_relations.csv` contains all crossed Relative SE(3) onsets involving the two target algorithms. `target_summary.csv` contains one compact row per focus case.

`metadata.json` fingerprints every consumed evidence file with SHA-256 and freezes schema/version/definitions. The Markdown report restates the descriptive-only scientific boundary and the measured temporal ordering.

## Validation and failure behavior

V1 fails closed when:

- any of the four expected child runs is missing
- a required coverage/trajectory/Relative SE(3) artifact is missing or malformed
- coverage rows do not contain all three expected algorithms
- standardized trajectory timestamps are not strictly increasing
- Relative SE(3) metadata does not declare `ground_truth = NONE`
- required target algorithms are not present in their focus windows
- output directory already exists

## Acceptance boundary

Repository CI proves pure logic, CLI contract, deterministic output, immutability guards, compileability, and existing suite compatibility.

Target-machine acceptance then runs exactly one audit command against the already accepted four child runs and verifies:

- no estimator process or ROS bag replay is started
- all four child runs are consumed
- output fingerprints resolve to existing fresh evidence
- both focus cases produce a target summary
- generated lead/lag values can be traced to trajectory timestamps and existing Relative SE(3) onset rows

At that point Failure-Mode Audit V1 stops for interpretation/review; it does not start a new benchmark phase.
