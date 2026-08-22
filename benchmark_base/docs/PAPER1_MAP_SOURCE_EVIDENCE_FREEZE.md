# Paper I Map-Source Evidence Freeze

## Goal

Freeze the existing LIO/global-map comparison work into a compact, auditable evidence package that Paper I can cite without moving navigation or semantic-map logic into this repository.

## Candidate sources

The first paper-facing comparison should include the methods that have actually produced usable global greenhouse maps in the existing experiments:

- FAST-LIVO2 LIO-only
- Kilo-Map
- handheld 3D scanner pipeline using FAST-LIO

Additional LIO algorithms may remain in the generic benchmark repository, but they are not required for the Paper I map-source evidence snapshot unless a complete comparable run already exists.

## Repository boundary

This repository owns:

- dataset/run identity
- algorithm/config identity
- trajectory metrics such as APE/RPE where available
- map reconstruction output identity
- runtime / resource metrics where already measured
- reproducible comparison reports

This repository does **not** own:

- greenhouse row/aisle semantics
- traversability recovery
- Nav2 maps used as Paper I formal authority
- route planning
- RPP tracking
- coverage planning

Those remain in `agt_navigation_v2`.

## Required Paper I evidence snapshot

Create one immutable output directory per frozen comparison:

```text
paper1_evidence/<snapshot_id>/
├── evidence_manifest.yaml
├── summary.csv
├── summary.md
├── figures/
│   ├── trajectories.png
│   ├── map_overview.png
│   └── map_source_comparison.png
└── maps/
    ├── fastlivo2_lio_only.yaml
    ├── kilo_map.yaml
    └── handheld_fastlio.yaml
```

Large PCD files should not be committed to Git. `maps/*.yaml` records their external path or artifact id, SHA256, frame, scale, and relevant generation configuration.

## `evidence_manifest.yaml` minimum fields

```yaml
schema: agt_lio_paper1_evidence/v1
snapshot_id: greenhouse_map_sources_v01
repository_commit: <sha>
dataset:
  id: <dataset-id>
  source_bag_sha256: <sha-if-applicable>
methods:
  - id: fastlivo2_lio_only
    run_id: <run>
    config_sha256: <sha>
    map_sha256: <sha>
  - id: kilo_map
    run_id: <run>
    config_sha256: <sha>
    map_sha256: <sha>
  - id: handheld_fastlio
    run_id: <run>
    config_sha256: <sha>
    map_sha256: <sha>
```

Do not invent missing hashes or metrics; explicitly mark unavailable fields.

## First-pass metrics

Keep the existing LIO benchmark metrics, but add only the minimum map-source fields needed for Paper I:

- trajectory APE / RPE where a common reference exists
- loop / final-position consistency where meaningful
- map completeness / usable global extent
- map point count and physical bounds
- gross scale consistency
- run time / resource metrics if already measured

Paper I downstream structural consistency (row direction, aisle centerline, traversable-area agreement) is computed in `agt_navigation_v2` after each frozen source map passes through the same semantic-map pipeline.

## Execution order

1. On the development machine, preserve all current local additions before switching branches.
2. Move or commit those additions onto `feat/paper1-map-source-benchmark-freeze`.
3. Identify the exact historical runs that generated the usable FAST-LIVO2 LIO-only, Kilo-Map, and handheld FAST-LIO maps.
4. Hash the maps/configs/datasets; do not copy multi-GB data into Git.
5. Produce the evidence manifest and one comparison summary.
6. Tag the frozen evidence commit or record its SHA in Paper I site evidence.
7. Stop adding algorithms for this Paper I snapshot.

## Acceptance gate

The evidence snapshot is ready for Paper I when:

- all three selected sources have unambiguous run/config/map identity, or unavailable sources are explicitly excluded with reason;
- every reported metric has a common definition and coordinate/scale assumptions are documented;
- representative maps can be regenerated or located by recorded hash;
- no navigation/semantic-map code was introduced here;
- `agt_navigation_v2` can import the evidence snapshot by repository commit + manifest hash.
