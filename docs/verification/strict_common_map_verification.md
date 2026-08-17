# Strict Common Map Verification

Date: 2026-08-17
Branch: `feat/lio-baseline-suite`

## Status

- Repository-side implementation: **VERIFIED BY CORE CONTRACTS**
- Verified implementation HEAD: `d3d41b12aca0cf8b86a64a7a29ad515f5b54cf0d`
- Core Contracts run: `31980973687`
- Target-machine one-bag P2 acceptance: **PENDING**
- Scientific claim: **scan-population fairness only**

The repository-side verification establishes that the strict common matched-scan contract, strict Unified Map consumption contract, CLI contract, immutable provenance fingerprints, and diagnostic bundle inclusion are internally consistent under the automated contract suite. It does not establish target-machine ROS execution, map accuracy, trajectory accuracy, calibration correctness, or ground-truth ranking.

## Repository Contract

P2 adds the run-level pipeline:

```text
selected_scans.csv
        |
        v
all selected standardized trajectories
        |
        v
STRICT_ALL_ALGORITHM_TRAJECTORY_INTERSECTION
        |
        v
common_matched_scans.csv
        |
        +--> FAST-LIVO2 Unified Map
        +--> FAST-LIO2 Unified Map
        `--> KISS-ICP Unified Map
```

The command is:

```bash
benchmark_base/bin/lio-benchmark standardize common-map-manifest \
  --run <run>
```

V1 exposes no algorithm-subset, tolerance, or overwrite option. The selected algorithms and `trajectory_time_tolerance_s` come only from the frozen run manifest.

## Common Manifest Evidence

The builder produces:

```text
standardized/map_sampling/common_matched_scans.csv
standardized/map_sampling/common_matched_metadata.json
```

The metadata fingerprints:

- the frozen `selected_scans.csv`
- every selected standardized trajectory
- the strict common manifest itself
- the frozen trajectory matching tolerance
- the frozen selected-algorithm population

Per algorithm it records:

- trajectory path and SHA256
- trajectory sample count
- individually matched scan count
- individually rejected scan count
- mandatory sorted original `rejected_scan_indices`

Original LiDAR `scan_index` values are preserved. Common rows are never renumbered.

Re-running against identical fingerprints returns the existing artifacts without rewriting them. Partial common artifacts or changed input fingerprints fail closed and require a new run.

## Strict Unified Map Contract

Formal `standardize map` reconstruction now requires a valid strict common manifest. There is no silent fallback to independent per-algorithm matching.

Every common row is re-matched against the requested algorithm trajectory. A mismatch raises `COMMON INTERSECTION CONTRACT VIOLATION`; it is not counted as an ordinary unmatched row and skipped.

Strict map metadata records:

```text
scan_set_policy = STRICT_COMMON_INTERSECTION
common_manifest = <path>
common_manifest_sha256 = <sha256>
selected_scan_count = common_matched_scan_count
matched_scan_count = common_matched_scan_count
unmatched_scan_count = 0
```

Final point counts are allowed to differ because estimated poses, physical tracked-frame transforms, voxel collisions, and geometry may differ even when the input scan indices are identical.

## Automated Verification Evidence

The implementation HEAD `d3d41b12aca0cf8b86a64a7a29ad515f5b54cf0d` passed Core Contracts run `31980973687`.

That run completed successfully through:

```text
Baseline suite registry contract  PASS
Unit contracts                    PASS
Compile Python sources            PASS
Shell adapter syntax              PASS
Registry smoke                    PASS
```

The P2 TDD sequence also included deliberate RED heads before the corresponding implementation:

- common-manifest module missing -> RED
- strict map still using independent matching -> RED
- CLI command and bundle evidence absent -> RED

The subsequent production heads closed those contracts without changing Relative SE(3), trajectory coverage, estimator execution, replay timing, calibration semantics, or trajectory matching tolerance.

## Target-Machine P2 Acceptance Gate

Target acceptance remains pending until one fresh real ROS2 bag run proves all of the following:

```text
COMMON_MAP_MANIFEST=PASS
COMMON_SCAN_COUNT>0
COMMON_MANIFEST_SHA_EQUAL=true
MAP_SELECTED_SCAN_COUNT_EQUAL=true
MAP_MATCHED_SCAN_COUNT_EQUAL=true
MAP_UNMATCHED_SCAN_COUNT_ZERO=true
UNIFIED_MAPS_NONEMPTY=true
SCAN_INDEX_EQUALITY=true
```

The acceptance must additionally print, for every selected algorithm:

```text
individually_matched_scan_count
individually_rejected_scan_count
rejected_scan_indices
strict_common_matched_scan_count
strict_unified_map_point_count
common_manifest_sha256
```

`SCAN_INDEX_EQUALITY=true` must be established by checking the actual original scan-index population consumed by the strict pipeline, not merely by comparing equal counts.

## Scientific Boundary

A successful P2 target acceptance will establish:

> Every compared Unified Map in the accepted run is reconstructed from the same original LiDAR scan-index population.

It will not establish:

- ground-truth map accuracy
- trajectory accuracy
- map-to-map ICP score
- Chamfer/completeness metrics
- calibration correctness
- estimator ranking

Existing calibration and `DIAGNOSTIC_ONLY` boundaries remain unchanged.

## Next Step

Stop after repository verification. Do not begin P3 calibration or accuracy work until a fresh one-bag P2 target-machine acceptance passes the gate above.
