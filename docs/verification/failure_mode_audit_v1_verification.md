# Failure-Mode Audit V1 Verification

Date: 2026-08-17

Branch:

```text
feat/lio-baseline-suite
```

## Scope

Failure-Mode Audit V1 is a read-only post-processing phase over the already accepted Representative Window V1 child runs. It does not replay the 623 s greenhouse bag, rerun an estimator, reselect a window, standardize a trajectory, or regenerate Relative SE(3).

Focus cases:

```text
high_angular_motion / kiss_icp
steady_translation_candidate / fast_livo2
```

All four representative windows and all three algorithms remain present in the coverage context so the two focus cases are not interpreted without batch context.

Scientific status remains:

```text
DESCRIPTIVE_NO_GROUND_TRUTH
```

Temporal ordering is an association only. It is not an estimator failure time, causal drift diagnosis, accuracy-loss time, or objective ranking.

## Frozen V1 definitions

Coverage degradation reuses the existing coverage layer's large-gap multiplier:

```text
GAP_MULTIPLIER = 1.5
```

For a standardized trajectory interval `(t_prev, t_curr)` and the already recorded input-LiDAR median period:

```text
t_curr - t_prev > 1.5 * input_lidar_median_period_s
```

is an input-relative coverage-degradation event. Its descriptive onset is:

```text
t_prev + 1.5 * input_lidar_median_period_s
```

No timestamp sorting, filling, interpolation, repair, or retiming is performed by this audit.

Relative SE(3) divergence timing is not recomputed. V1 consumes the existing:

```text
metrics/relative_se3/onset_thresholds.csv
```

and therefore preserves the already-frozen Relative SE(3) thresholds, 0.1 s common sampling, and three-sample sustained-onset rule recorded by each child run.

## Immutable evidence boundary

For each child run the audit reads only:

```text
manifest.json
metrics/trajectory_coverage.csv
standardized/trajectories/fast_livo2.csv
standardized/trajectories/fast_lio2.csv
standardized/trajectories/kiss_icp.csv
metrics/relative_se3/metadata.json
metrics/relative_se3/onset_thresholds.csv
```

Every consumed file is SHA-256 fingerprinted into the new audit metadata. Child runs are never written.

The output is a new sibling directory:

```text
<run-root>/<batch-id>_failure_mode_audit_v1/
```

An existing output directory is a hard refusal rather than an overwrite.

## TDD evidence

### Pure audit core RED

RED commit:

```text
b50e180a078b8f0176cef2bb408492092b26a8d5
```

Core Contracts run:

```text
32004505987 = completed / failure
```

The old suite remained green and the new test failed for the intended missing production module:

```text
ModuleNotFoundError: No module named 'benchmark_base.lib.failure_mode_audit'
```

### Pure audit core GREEN

Implementation commit:

```text
dd0da639709d0345311171b1027fa69d3df006c4
```

Core Contracts run:

```text
32004649679 = completed / success
```

This run completed successfully through Unit Contracts, Python compilation, shell adapter syntax, and registry smoke.

### CLI RED

RED commit:

```text
1c3a5fb227b5a1837328cebebff545683c685e40
```

Core Contracts run:

```text
32004723996 = completed / failure
```

The eight pure Failure-Mode Audit tests remained PASS. The three new CLI contracts failed only because the `failure-mode` parser, handler, and evaluator did not yet exist.

### CLI GREEN / repository verification

Implementation HEAD before this verification record:

```text
1f4d6cbecaf346147d5df2735c530b28c192e5b2
```

Core Contracts run:

```text
32004818875 = completed / success
```

Successful gates:

```text
Baseline suite registry contract
Unit Contracts
Compile Python sources
Shell adapter syntax
Registry smoke
```

## Public command

V1 exposes exactly the batch location and batch identity:

```bash
python3 benchmark_base/bin/lio-benchmark audit failure-mode \
  --run-root /home/yangxuan/lio_benchmark_runs/green_house \
  --batch-id repv1_final_20260817_133745
```

V1 intentionally exposes no flags for gap multiplier, window duration, algorithm selection, timestamp repair, threshold tuning, or overwrite.

The handler directly invokes the pure Python evaluator. It does not call `resolve_run`, `run_python_ros`, `rclpy`, `rosbag2_py`, a bag reader, or an estimator runner.

## Expected output contract

A successful target-machine audit creates exactly:

```text
metadata.json
coverage_context.csv
coverage_events.csv
onset_relations.csv
target_summary.csv
FAILURE_MODE_AUDIT_V1.md
```

`coverage_context.csv` must contain 12 rows:

```text
4 windows x 3 algorithms
```

`target_summary.csv` must contain exactly these two focus rows:

```text
high_angular_motion,kiss_icp
steady_translation_candidate,fast_livo2
```

For every crossed existing Relative SE(3) onset involving a target algorithm, `onset_relations.csv` records:

```text
first coverage-degradation onset
nearest coverage-degradation onset at/before the disagreement onset
nearest coverage-degradation onset after the disagreement onset
signed disagreement onset - first coverage onset
lead from the nearest preceding coverage event
lag to the nearest following coverage event
temporal order label
```

The compact temporal-order labels are:

```text
COVERAGE_DEGRADATION_FIRST
DESCRIPTIVE_DIVERGENCE_FIRST
SAME_TIMESTAMP
NO_COVERAGE_DEGRADATION_EVENT
NO_CROSSED_RELATIVE_SE3_ONSET
```

Raw signed timing deltas remain the primary evidence.

## Codex target-machine acceptance — PENDING

Repository CI does not have the real `/home/yangxuan/lio_benchmark_runs/green_house` child-run directories. Do not claim the measured ordering until the following target-machine acceptance completes.

### 1. Update only the repository

```bash
cd ~/lio_benchmark_tools
git switch feat/lio-baseline-suite
git pull --ff-only
```

Do not start any ROS bag replay or estimator process.

### 2. Confirm the four accepted fresh child runs still exist

```bash
RUN_ROOT=/home/yangxuan/lio_benchmark_runs/green_house
BATCH=repv1_final_20260817_133745

for window in \
  initialization \
  high_angular_motion \
  geometric_degeneracy_candidate \
  steady_translation_candidate
do
  test -d "$RUN_ROOT/${BATCH}_${window}" || exit 1
done
```

### 3. Run only Failure-Mode Audit V1

```bash
python3 benchmark_base/bin/lio-benchmark audit failure-mode \
  --run-root "$RUN_ROOT" \
  --batch-id "$BATCH"
```

Expected new directory:

```text
/home/yangxuan/lio_benchmark_runs/green_house/repv1_final_20260817_133745_failure_mode_audit_v1
```

If that directory already exists from a previous attempt, preserve it and inspect it; V1 intentionally refuses overwrite. Do not delete an accepted audit merely to force a rerun.

### 4. Machine-check the output contract

```bash
AUDIT="$RUN_ROOT/${BATCH}_failure_mode_audit_v1"

python3 - "$AUDIT" <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
expected = {
    "metadata.json",
    "coverage_context.csv",
    "coverage_events.csv",
    "onset_relations.csv",
    "target_summary.csv",
    "FAILURE_MODE_AUDIT_V1.md",
}
actual = {path.name for path in root.iterdir()}
assert actual == expected, (actual, expected)

with (root / "coverage_context.csv").open(newline="", encoding="utf-8") as stream:
    context = list(csv.DictReader(stream))
assert len(context) == 12, len(context)
assert {row["window_label"] for row in context} == {
    "initialization",
    "high_angular_motion",
    "geometric_degeneracy_candidate",
    "steady_translation_candidate",
}
assert {row["algorithm_id"] for row in context} == {
    "fast_livo2",
    "fast_lio2",
    "kiss_icp",
}

with (root / "target_summary.csv").open(newline="", encoding="utf-8") as stream:
    target = list(csv.DictReader(stream))
assert {(row["window_label"], row["algorithm_id"]) for row in target} == {
    ("high_angular_motion", "kiss_icp"),
    ("steady_translation_candidate", "fast_livo2"),
}

metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
assert metadata["schema"] == "lio_benchmark_failure_mode_audit/v1"
assert metadata["scientific_status"] == "DESCRIPTIVE_NO_GROUND_TRUTH"
assert metadata["ground_truth"] == "NONE"
assert len(metadata["child_runs"]) == 4
for evidence in metadata["evidence_files"]:
    path = Path(evidence["path"])
    assert path.is_file(), path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"], path

print("FAILURE_MODE_AUDIT_V1_TARGET_CONTRACT=PASS")
for row in target:
    print(
        row["window_label"],
        row["algorithm_id"],
        "coverage_first_s=", row["first_coverage_degradation_onset_s"],
        "relative_se3_first_s=", row["earliest_relative_se3_onset_timestamp_s"],
        "delta_s=", row["earliest_divergence_minus_first_coverage_s"],
        "order=", row["temporal_order"],
    )
PY
```

### 5. Acceptance stop point

Codex should return only the contract PASS line, the two printed target-summary rows, and the contents of:

```text
FAILURE_MODE_AUDIT_V1.md
```

At that point stop. Do not launch another benchmark, do not rerun the 623 s bag, and do not alter any child-run artifact.

Acceptance state before the target-machine command:

```text
FAILURE_MODE_AUDIT_V1_REPOSITORY_ACCEPTANCE = PASS
FAILURE_MODE_AUDIT_V1_TARGET_MACHINE_ACCEPTANCE = PENDING
```
