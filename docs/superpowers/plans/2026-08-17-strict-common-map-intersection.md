# Strict Common Map Intersection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every formal Unified Map in one frozen run is reconstructed from exactly the same original LiDAR scan indices: the strict intersection of scans matchable by every selected algorithm trajectory.

**Architecture:** Add a small run-level common-manifest builder that derives `common_matched_scans.csv` from the existing frozen `selected_scans.csv` and all standardized trajectories. The builder fingerprints every input and is immutable on re-run. `standardize map` then consumes only this strict common manifest, re-validates fingerprints and every trajectory match, and fails closed if evidence changed.

**Tech Stack:** Python 3.10, ROS 2 Humble, existing `Trajectory.interpolate_pose`, existing selected-scan CSV helpers, `hashlib.sha256`, `unittest`, existing `lio-benchmark` CLI and GitHub Actions `Core Contracts`.

## Global Constraints

- Branch stays `feat/lio-baseline-suite`; do not modify or merge `main`.
- Formal benchmark source/build/install/run/output must not use `/tmp`.
- Do not modify estimator execution, replay timing, trajectory standardization, Relative SE(3), calibration semantics, tracked-frame semantics, world-gauge semantics, trajectory matching tolerance, LiDAR point sampling, voxel filtering, or map frame conversion.
- Common-map algorithm population is always all selected algorithms frozen in `manifest.json`; V1 has no algorithm subset option.
- Matching uses exactly `Trajectory.interpolate_pose(timestamp_s, trajectory_time_tolerance_s)`.
- No tolerance widening, timestamp rewriting, trajectory mutation, alignment fitting, or calibration adjustment.
- `rejected_scan_indices` is mandatory metadata evidence.
- Common artifacts are immutable: identical fingerprints return existing bytes; partial artifacts or changed fingerprints fail closed and require a new run.
- Formal `standardize map` has no silent legacy fallback after P2.
- Existing scientific status remains unchanged; P2 establishes scan-population fairness only.

---

### Task 1: Strict Common Manifest Builder

**Files:**
- Create: `benchmark_base/lib/common_map_manifest.py`
- Create: `evaluators/build_common_map_manifest.py`
- Create: `benchmark_base/tests/test_common_map_manifest.py`

**Interfaces:**
- Consumes: `SelectedScan`, `read_scan_manifest`, `write_scan_manifest`, `Trajectory.from_csv`, `Trajectory.interpolate_pose(timestamp_s, tolerance_s)`, frozen `manifest.json`.
- Produces: `build_common_map_manifest(run: Path) -> Path`, `validate_common_map_manifest(run: Path) -> dict[str, Any]`, `common_matched_scans.csv`, `common_matched_metadata.json`.

- [ ] **Step 1: Write RED tests for mathematical intersection and preserved scan indices**

Create `benchmark_base/tests/test_common_map_manifest.py` with helpers that write a small frozen run, selected scan rows, and synthetic standardized trajectories. Lock at least:

```python
def test_different_algorithm_rejections_form_exact_intersection(self):
    # selected original indices: [0, 5, 10, 15]
    # alg_a rejects index 5; alg_b rejects index 10; alg_c accepts all
    # expected common indices: [0, 15]
    output = build_common_map_manifest(run)
    rows = read_scan_manifest(output)
    self.assertEqual([0, 15], [row.scan_index for row in rows])
```

Also assert original `selected_scans.csv` and each trajectory SHA are unchanged before/after.

- [ ] **Step 2: Write RED tests for fail-closed input validation and immutable re-run**

Lock:

```python
def test_missing_selected_algorithm_trajectory_fails_closed(self): ...
def test_missing_or_invalid_tolerance_fails_closed(self): ...
def test_metadata_records_rejected_scan_indices_and_input_sha256(self): ...
def test_identical_rerun_returns_existing_artifact_without_rewrite(self): ...
def test_partial_existing_common_artifacts_fail_closed(self): ...
def test_changed_trajectory_after_common_manifest_fails_closed(self): ...
```

The immutable re-run test records `st_mtime_ns` and bytes for both output files, invokes builder again, and requires both to remain unchanged.

- [ ] **Step 3: Run RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_common_map_manifest -v
```

Expected: FAIL because `benchmark_base.lib.common_map_manifest` does not exist.

- [ ] **Step 4: Implement the focused common-manifest library**

`benchmark_base/lib/common_map_manifest.py` should define constants:

```python
POLICY = "STRICT_ALL_ALGORITHM_TRAJECTORY_INTERSECTION"
COMMON_NAME = "common_matched_scans.csv"
METADATA_NAME = "common_matched_metadata.json"
```

Add deterministic SHA helper:

```python
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

Add frozen tolerance resolver that requires a finite non-negative `trajectory_time_tolerance_s` from `manifest.get("standardization", manifest.get("evaluation", {}))`.

For every selected algorithm:

```python
trajectory_path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
trajectory = Trajectory.from_csv(trajectory_path)
```

For every selected scan row, call `trajectory.interpolate_pose(row.timestamp_s, tolerance_s)`. Record per-algorithm rejected original indices on `TrajectoryMatchError`. Keep a row only when all selected algorithms match.

Write metadata with exact input paths, SHA256, sample counts, individual matched/rejected counts, mandatory sorted `rejected_scan_indices`, policy, original selected count, common count, tolerance, and output SHA256.

Before writing, snapshot input SHA256. Recompute all input SHA256 immediately before final write; if any changed, fail closed.

- [ ] **Step 5: Implement immutable re-run validation**

If both common artifacts already exist, parse metadata and call `validate_common_map_manifest(run)`. When current source fingerprints/policy/tolerance/algorithm set match recorded values and `common_matched_scans.csv` SHA matches metadata, return the existing path without writing anything.

If only one artifact exists or any validation differs, raise `ValueError` containing `create a new run`.

- [ ] **Step 6: Add evaluator wrapper**

Create `evaluators/build_common_map_manifest.py`:

```python
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    print(build_common_map_manifest(args.run.resolve()))
    return 0
```

No overwrite, tolerance, or algorithm arguments.

- [ ] **Step 7: Run GREEN**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_common_map_manifest -v
python3 -m unittest discover -s benchmark_base/tests -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add benchmark_base/lib/common_map_manifest.py \
        evaluators/build_common_map_manifest.py \
        benchmark_base/tests/test_common_map_manifest.py
git commit -m "feat: build strict common map scan manifest"
```

---

### Task 2: Make Unified Map Strictly Consume the Common Manifest

**Files:**
- Modify: `evaluators/standardize_map.py`
- Create: `benchmark_base/tests/test_strict_common_map.py`

**Interfaces:**
- Consumes: Task 1 `validate_common_map_manifest(run)` and `common_matched_scans.csv`.
- Produces: strict Unified Map metadata fields `scan_set_policy`, `common_manifest`, `common_manifest_sha256`, with `unmatched_scan_count == 0`.

- [ ] **Step 1: Write RED tests for strict precondition and metadata contract**

Create `benchmark_base/tests/test_strict_common_map.py` and lock source-level/isolated behavior without requiring a ROS bag in CI:

```python
def test_standardize_map_requires_common_manifest(self):
    with self.assertRaisesRegex(ValueError, "standardize common-map-manifest"):
        load_strict_common_scan_rows(run)


def test_strict_common_metadata_requires_zero_unmatched(self):
    timing = strict_timing_metadata(common_path, common_sha, matched=3, expected=3, ...)
    self.assertEqual("STRICT_COMMON_INTERSECTION", timing["scan_set_policy"])
    self.assertEqual(0, timing["unmatched_scan_count"])
```

Also lock that a selected common row which no longer matches a trajectory raises a hard contract violation rather than being converted into `unmatched += 1`.

- [ ] **Step 2: Run RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_strict_common_map -v
```

Expected: FAIL because strict helpers/behavior do not exist.

- [ ] **Step 3: Refactor `standardize_map.py` minimally around strict helpers**

Import:

```python
from benchmark_base.lib.common_map_manifest import (
    POLICY as COMMON_POLICY,
    sha256_file,
    validate_common_map_manifest,
)
```

Add a helper that validates Task 1 metadata and returns only `common_matched_scans.csv`. If missing, raise:

```text
strict common map manifest is required; run:
lio-benchmark standardize common-map-manifest --run <run>
```

Do not call `build_manifest(run)` from `standardize_map.py` anymore.

- [ ] **Step 4: Change trajectory mismatch semantics to hard failure**

For a row already admitted to the strict common manifest:

```python
try:
    match = trajectory.interpolate_pose(timestamp_s, tolerance_s)
except TrajectoryMatchError as exc:
    raise ValueError(
        "COMMON INTERSECTION CONTRACT VIOLATION: "
        f"algorithm={algorithm_id} scan_index={scan_index} timestamp_s={timestamp_s:.9f}"
    ) from exc
```

No `unmatched += 1; continue` path remains for common rows.

- [ ] **Step 5: Freeze strict map metadata**

Set:

```python
metadata["scan_set_policy"] = "STRICT_COMMON_INTERSECTION"
metadata["common_manifest"] = str(common_path)
metadata["common_manifest_sha256"] = sha256_file(common_path)
```

Timing metadata must use:

```python
selected_scan_count = len(common_rows)
matched_scan_count = len(common_rows)
unmatched_scan_count = 0
```

Assert at end that `matched == selected == encountered_selected`; otherwise hard fail.

- [ ] **Step 6: Run GREEN and regression suite**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_strict_common_map -v
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add evaluators/standardize_map.py benchmark_base/tests/test_strict_common_map.py
git commit -m "feat: enforce strict common scans for unified maps"
```

---

### Task 3: CLI, Bundle Evidence, Verification Docs, and Final CI Gate

**Files:**
- Modify: `benchmark_base/bin/lio-benchmark-core`
- Modify: `benchmark_base/lib/diagnostic_bundle.py`
- Create: `benchmark_base/tests/test_common_map_cli.py`
- Modify: `benchmark_base/tests/test_diagnostic_bundle.py`
- Create: `docs/verification/strict_common_map_verification.md`

**Interfaces:**
- Consumes: Task 1 evaluator `evaluators/build_common_map_manifest.py` and Task 2 strict map metadata.
- Produces: `lio-benchmark standardize common-map-manifest --run <run>` and bundled common-map evidence.

- [ ] **Step 1: Write RED CLI contract test**

Create `benchmark_base/tests/test_common_map_cli.py` loading the existing CLI exactly like other CLI tests. Require parsing:

```text
standardize common-map-manifest --run /persistent/run
```

and ensure there are no algorithm/tolerance/overwrite options. Mock `run_python_ros` and require it to call:

```python
("evaluators/build_common_map_manifest.py", ["--run", "/persistent/run"])
```

- [ ] **Step 2: Write RED bundle evidence test**

Extend `test_diagnostic_bundle.py` so, when present, the bundle contains:

```text
standardized/map_sampling/common_matched_scans.csv
standardized/map_sampling/common_matched_metadata.json
```

These remain optional for historical runs; absence must not make an old bundle fail.

- [ ] **Step 3: Run RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_common_map_cli -v
python3 -m unittest benchmark_base.tests.test_diagnostic_bundle -v
```

Expected: CLI/bundle assertions fail before production wiring.

- [ ] **Step 4: Wire CLI**

In `lio-benchmark-core` add:

```python
def cmd_standardize_common_map_manifest(args: argparse.Namespace) -> None:
    run, manifest = resolve_run(args.run)
    run_python_ros(
        run,
        manifest,
        "evaluators/build_common_map_manifest.py",
        ["--run", str(run)],
    )
```

Add parser:

```python
scm = standardize_sub.add_parser("common-map-manifest")
scm.add_argument("--run", type=Path, required=True)
scm.set_defaults(func=cmd_standardize_common_map_manifest)
```

No other arguments.

- [ ] **Step 5: Wire diagnostic bundle evidence**

Add both common-map files as optional small evidence entries. Do not classify them as required for historical runs.

- [ ] **Step 6: Add verification document with P2 target acceptance still PENDING**

Create `docs/verification/strict_common_map_verification.md` recording:

```text
Repository-side implementation: VERIFIED BY CORE CONTRACTS
Target-machine one-bag P2 acceptance: PENDING
Scientific claim: scan-population fairness only
```

Document the exact future gate names:

```text
COMMON_MAP_MANIFEST
COMMON_SCAN_COUNT
COMMON_MANIFEST_SHA_EQUAL
MAP_SELECTED_SCAN_COUNT_EQUAL
MAP_MATCHED_SCAN_COUNT_EQUAL
MAP_UNMATCHED_SCAN_COUNT_ZERO
UNIFIED_MAPS_NONEMPTY
SCAN_INDEX_EQUALITY
```

Do not claim target acceptance until a fresh real-bag run proves them.

- [ ] **Step 7: Run full repository verification**

Run:

```bash
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

Then require exact-head GitHub Actions `Core Contracts` success.

- [ ] **Step 8: Commit Task 3**

```bash
git add benchmark_base/bin/lio-benchmark-core \
        benchmark_base/lib/diagnostic_bundle.py \
        benchmark_base/tests/test_common_map_cli.py \
        benchmark_base/tests/test_diagnostic_bundle.py \
        docs/verification/strict_common_map_verification.md
git commit -m "feat: expose strict common map acceptance contract"
```

---

## Plan Self-Review

- Spec coverage: all strict intersection, fingerprint immutability, rejection evidence, strict map consumption, no fallback, metadata equality, bundle evidence, and target-machine stop gates are assigned to Tasks 1-3.
- Placeholder scan: no TBD/TODO or unspecified implementation step remains.
- Type consistency: Task 2 consumes the exact `validate_common_map_manifest(run)` and SHA helper introduced in Task 1; Task 3 invokes the evaluator created in Task 1.
- Scope: no cadence/replay fix, map scoring, calibration, GT, or P3 work is included.

## Execution Stop Condition

After Task 3 is GREEN on exact-head CI, stop. Do not start P3. The next action must be one fresh real-bag P2 acceptance that proves actual scan-index equality and strict-map metadata equality across FAST-LIVO2, FAST-LIO2, and KISS-ICP.
