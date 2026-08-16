# Strict Common Matched Scan Intersection Design

Date: 2026-08-17
Branch: `feat/lio-baseline-suite`
Status: Approved design, implementation pending

## 1. Motivation

The current Unified Map pipeline freezes one run-level `selected_scans.csv`, but each algorithm independently matches those scan timestamps against its own standardized trajectory. A scan rejected for one algorithm may still be accepted for another. As a result, different Unified Maps can be reconstructed from different LiDAR scan subsets even though they originate from the same frozen selected-scan manifest.

That is acceptable for individual map reconstruction, but it is not a strict fairness contract for cross-algorithm map comparison.

P2 introduces a second, immutable run-level manifest containing only LiDAR scans that can be matched by every selected algorithm trajectory under the already-frozen trajectory matching tolerance.

## 2. Scope

P2 changes only Unified Map scan-set fairness.

It does not change:

- estimator execution
- replay timing
- trajectory standardization
- trajectory timestamp semantics
- Relative SE(3) V1
- calibration semantics
- tracked-frame semantics
- world-gauge semantics
- trajectory matching tolerance
- LiDAR point sampling
- voxel filtering
- map frame conversion

The existing `selected_scans.csv` remains the frozen first-stage scan-selection evidence. The new strict intersection manifest is derived from it and from standardized trajectories.

## 3. Selected approach

Use a two-stage immutable manifest pipeline.

```text
selected_scans.csv
        |
        v
for every frozen selected scan timestamp
check every selected algorithm trajectory
        |
        v
all algorithms match under frozen tolerance?
        |
        +-- no  -> reject from common comparison set
        |
        `-- yes -> common_matched_scans.csv
                        |
                        +--> FAST-LIVO2 Unified Map
                        +--> FAST-LIO2 Unified Map
                        `--> KISS-ICP Unified Map
```

This is preferred over post-hoc map intersection because post-hoc filtering cannot undo the fact that different maps were already accumulated from different input scans. It is also preferred over a monolithic multi-algorithm map command because the existing single-algorithm map standardizer remains a clean and useful boundary.

## 4. CLI contract

Add one new command:

```bash
lio-benchmark standardize common-map-manifest \
  --run <run>
```

V1 exposes no algorithm-subset option and no matching-tolerance override.

The algorithm set is always the frozen selected-algorithm set in `manifest.json`.

The timestamp tolerance is always the already-frozen `trajectory_time_tolerance_s` from the run standardization contract.

This prevents users from silently changing the map-comparison population between runs.

## 5. Inputs

The common-manifest builder requires:

- `<run>/manifest.json`
- `<run>/standardized/map_sampling/selected_scans.csv`
- one standardized trajectory for every selected algorithm:
  - `<run>/standardized/trajectories/<algorithm_id>.csv`

The builder must fail closed when:

- selected scan manifest is missing or empty
- any selected algorithm trajectory is missing or empty
- any selected algorithm is unknown to the frozen run
- matching tolerance is invalid
- input files change unexpectedly during the operation

## 6. Matching rule

For each row in `selected_scans.csv`, call the same trajectory interpolation/matching implementation used by Unified Map reconstruction:

```python
trajectory.interpolate_pose(timestamp_s, trajectory_time_tolerance_s)
```

A scan belongs to the strict common set only when every frozen selected algorithm returns a valid trajectory match.

No fitting, nearest-neighbor policy change, tolerance widening, frame relabeling, trajectory mutation, timestamp rewriting, or calibration adjustment is allowed.

## 7. Outputs

Add:

```text
standardized/map_sampling/
├── selected_scans.csv
├── metadata.json
├── common_matched_scans.csv
└── common_matched_metadata.json
```

`common_matched_scans.csv` reuses the selected-scan row schema and preserves original:

- `scan_index`
- `timestamp_s`
- `timestamp_source`
- `bag_record_time_s`
- `lidar_topic`

Rows remain sorted by original `scan_index` and are never renumbered.

The artifact is immutable by default. On re-run:

- if `common_matched_scans.csv` and `common_matched_metadata.json` both exist and all recorded source fingerprints still match the current `selected_scans.csv` and standardized trajectories, return the existing artifact without rewriting it
- if only one artifact exists, or any recorded source fingerprint differs, fail closed and require a new run rather than overwriting evidence

There is no `--overwrite` option in V1.

## 8. Common-manifest metadata

`common_matched_metadata.json` must record at minimum:

```text
schema_version
policy = STRICT_ALL_ALGORITHM_TRAJECTORY_INTERSECTION
source_selected_manifest
source_selected_manifest_sha256
original_selected_scan_count
common_matched_scan_count
trajectory_time_tolerance_s
algorithms
```

For every algorithm, record:

```text
trajectory_path
trajectory_sha256
trajectory_sample_count
individually_matched_scan_count
individually_rejected_scan_count
rejected_scan_indices
```

`rejected_scan_indices` is mandatory and contains the original frozen `scan_index` values rejected for that algorithm, sorted ascending.

The metadata must make it possible to prove that the common manifest was derived from a specific frozen selected-scan manifest and specific standardized trajectories.

## 9. Unified Map consumption contract

After P2, formal Unified Map reconstruction consumes `common_matched_scans.csv`, not `selected_scans.csv`.

`standardize map --run ... --algorithm ...` remains a single-algorithm command, but its scan population is the strict common set.

During reconstruction, trajectory interpolation is performed again for every common scan. This is an intentional second validation layer.

A scan listed in `common_matched_scans.csv` that no longer matches the algorithm trajectory is a contract violation and must fail closed. It must not be converted into an ordinary unmatched count and skipped.

This catches trajectory mutation or stale common-manifest evidence.

Before reading LiDAR data, map reconstruction must validate the common-manifest metadata fingerprints against the current selected-scan manifest and all standardized trajectories. A mismatch is a hard failure.

## 10. Unified Map metadata contract

For strict-comparison Unified Maps, map metadata must record:

```text
scan_set_policy = STRICT_COMMON_INTERSECTION
common_manifest = <path>
common_manifest_sha256 = <sha256>
selected_scan_count = common_matched_scan_count
matched_scan_count = common_matched_scan_count
unmatched_scan_count = 0
```

All selected algorithms in the same run must therefore report the same:

- `scan_set_policy`
- `common_manifest_sha256`
- `selected_scan_count`
- `matched_scan_count`

Different algorithms may still produce different final map point counts because tracked-frame transforms, estimated poses, voxel collisions, and geometry differ. Equal scan-set membership does not imply equal point clouds.

## 11. Backward compatibility

Historical runs may not contain `common_matched_scans.csv`.

P2 must not retroactively reinterpret old map artifacts as strict-intersection maps.

For formal Unified Map reconstruction after P2, absence of the common manifest is a hard precondition failure with a clear instruction to run:

```bash
lio-benchmark standardize common-map-manifest --run <run>
```

V1 provides no silent fallback and no legacy map mode inside `standardize map`. Existing historical map artifacts remain readable as artifacts, but a new map reconstruction must satisfy the strict common-intersection contract.

## 12. Scientific interpretation

P2 establishes only scan-population fairness:

> every compared Unified Map is reconstructed from the same original LiDAR scan indices.

It does not establish map accuracy, pose accuracy, calibration correctness, ground truth, or estimator ranking.

Current calibration/scientific status remains unchanged. Results that are currently `DIAGNOSTIC_ONLY` remain `DIAGNOSTIC_ONLY`.

## 13. Required tests

Implementation follows TDD. At minimum lock these behaviors:

1. Three trajectories all match every selected timestamp -> common manifest equals selected manifest.
2. One algorithm rejects one scan -> that scan is absent for every algorithm's strict map population.
3. Different algorithms reject different scans -> common manifest is the mathematical intersection.
4. Original `scan_index` values are preserved and sorted; no renumbering.
5. Missing standardized trajectory -> fail closed.
6. Invalid or missing matching tolerance -> fail closed.
7. Existing selected-scan manifest and standardized trajectories are not modified.
8. Metadata fingerprints selected manifest and every trajectory and records mandatory rejected scan indices.
9. Identical re-run returns the existing common artifact byte-for-byte without rewriting it.
10. Partial common artifacts or changed input fingerprints -> fail closed and require a new run.
11. `standardize map` requires the common manifest for strict reconstruction.
12. A common-manifest scan that fails re-validation during map reconstruction -> hard failure, not `unmatched += 1`.
13. Three map metadata files point to the identical common-manifest SHA and have `unmatched_scan_count = 0`.
14. Point counts are allowed to differ despite identical scan counts.
15. Relative SE(3), trajectory coverage, runtime provenance, and existing CLI contracts remain unchanged.

## 14. Target-machine acceptance

After implementation and exact-head CI pass, stop before P3 and run one fresh real-bag acceptance.

The acceptance must prove:

```text
COMMON_MAP_MANIFEST=PASS
COMMON_SCAN_COUNT>0
COMMON_MANIFEST_SHA_EQUAL=true
MAP_SELECTED_SCAN_COUNT_EQUAL=true
MAP_MATCHED_SCAN_COUNT_EQUAL=true
MAP_UNMATCHED_SCAN_COUNT_ZERO=true
UNIFIED_MAPS_NONEMPTY=true
```

It must additionally print, for every algorithm:

```text
original individually matched scans
original individually rejected scans
strict common matched scans
strict unified-map point count
```

The test must verify actual scan-index equality, not only equal counts.

No P3 calibration/accuracy work begins until this one-bag P2 acceptance passes.

## 15. Non-goals

P2 does not implement:

- ground-truth map comparison
- map-to-map ICP scoring
- Chamfer distance
- completeness/accuracy metrics
- RTK/GNSS truth
- calibration refinement
- automatic tolerance tuning
- algorithm subset cherry-picking
- replay lifecycle changes
- estimator cadence fixes

Those remain later work.
