# Diagnostic Bundle Design

## 1. Goal

Add a small, reproducible export tool for benchmark troubleshooting so a user can package the run-level evidence needed for review into one archive instead of manually collecting many files.

Primary command:

```bash
lio-benchmark bundle --run <RUN_DIR>
```

Default output:

```text
<RUN_DIR>/reports/bundles/<run_id>_diagnostic_bundle.tar.gz
```

The default bundle must stay small enough to upload easily. It must not include raw rosbag data, PLY/PCD maps, or other large binary artifacts.

## 2. CLI Contract

### 2.1. Default mode

```bash
lio-benchmark bundle --run "$RUN"
```

Creates a minimal diagnostic archive.

### 2.2. Include reports and figures

```bash
lio-benchmark bundle --run "$RUN" --include-reports
```

Adds generated report files and diagnostic PNG figures to the archive.

### 2.3. Output override

Optional:

```bash
lio-benchmark bundle --run "$RUN" --output /path/to/custom.tar.gz
```

If omitted, output is derived from `run_id` in `manifest.json` and written under `reports/bundles/`.

## 3. Default Bundle Contents

The minimal bundle includes only existing small diagnostic files plus generated bundle metadata.

Expected archive members:

```text
manifest.json
RUN_STATUS.md

metrics/
├── runtime_provenance.csv
├── trajectory_frame_audit.csv
├── smoke_diagnostics.csv
├── smoke_diagnostics_warmup_*.csv
├── pairwise_disagreement.csv
└── pairwise_disagreement_warmup_*.csv

metadata/
├── frame_audit/
├── runtime_provenance/
└── bundle/
    ├── SUMMARY.txt
    ├── bundle_manifest.json
    ├── benchmark_git_status.txt
    ├── benchmark_git_head.txt
    └── benchmark_local.patch

standardized/map_sampling/
├── metadata.json
└── selected_scans.csv

standardized/maps/<algorithm>/unified/metadata.json
```

The tool must discover selected algorithms from the frozen run manifest rather than hard-code FAST-LIVO2, FAST-LIO2, and KISS-ICP.

Missing optional files are allowed. They are recorded in `bundle_manifest.json` and are not converted into empty placeholder science artifacts.

`metadata/bundle/*` are generated directly as archive members. They are not written back into the run directory before packaging.

## 4. Optional Report Contents

With `--include-reports`, add existing files under:

```text
reports/*.md
reports/*.html
figures/*.png
```

Do not regenerate reports or figures during bundling. The bundle command is read-only with respect to existing run artifacts.

## 5. Repository Provenance Capture

The tool captures the benchmark repository state at bundle time as archive-only metadata:

```text
metadata/bundle/benchmark_git_head.txt
metadata/bundle/benchmark_git_status.txt
metadata/bundle/benchmark_local.patch
```

`benchmark_local.patch` contains `git diff` output for tracked modifications so machine-specific runner adjustments are recoverable.

The tool must not modify, stash, reset, or commit the user's local changes.

If the benchmark repository cannot be identified as a Git repository, bundling still succeeds and records the provenance capture as unavailable.

## 6. Bundle Manifest

Each archive contains `metadata/bundle/bundle_manifest.json` with at least:

```json
{
  "schema": "lio_benchmark_diagnostic_bundle/v1",
  "run_id": "...",
  "created_at": "...",
  "include_reports": false,
  "archive_name": "...",
  "included": [],
  "missing": [],
  "excluded_large_artifacts": [
    "raw/**",
    "**/*.db3",
    "**/*.mcap",
    "**/*.ply",
    "**/*.pcd"
  ]
}
```

`included` and `missing` contain run-relative archive paths so the bundle remains interpretable after the run directory is moved. Generated `metadata/bundle/*` members are also listed in `included`.

## 7. Summary File

`metadata/bundle/SUMMARY.txt` provides a human-readable quick view containing:

- run ID
- dataset ID and bag path
- benchmark Git HEAD and dirty status
- selected algorithms
- runtime provenance status per algorithm when available
- trajectory frame audit status per algorithm when available
- common scan manifest summary when available
- Unified Map tracked-frame/world-gauge metadata per algorithm when available

The summary is descriptive only. It must not invent PASS/FAIL states when source artifacts are absent.

## 8. Safety and Size Rules

The default command must never package:

- `raw/`
- original dataset bags
- `.db3` / `.mcap`
- `.ply` / `.pcd`
- algorithm build/install trees
- source repositories

The archive creator must not recursively include its own output file.

The archive uses deterministic run-relative member names without embedding the user's absolute filesystem paths as archive paths. File contents such as `manifest.json` may still legitimately contain the original dataset/source paths because preserving provenance is the point of the bundle.

The only filesystem mutation performed by the default command is creation/replacement of the requested output archive. Existing run artifacts and source repositories are not modified.

## 9. Error Handling

Hard failures:

- run directory does not exist
- missing or invalid `manifest.json`
- output archive cannot be created
- archive creation fails

Non-fatal missing evidence:

- provenance audit not run yet
- frame audit not run yet
- map metadata missing for some algorithms
- reports/figures absent when `--include-reports` is requested
- Git provenance unavailable

These conditions are written into archive-local `bundle_manifest.json` and `SUMMARY.txt`.

## 10. Architecture

Keep packaging logic separate from CLI parsing.

Recommended modules:

```text
benchmark_base/lib/diagnostic_bundle.py
    collect candidate run-relative files
    enforce exclusion rules
    build summary data
    build bundle manifest
    create tar.gz archive and generated in-memory members

benchmark_base/bin/lio-benchmark
    parse `bundle`
    resolve run
    call diagnostic bundle library
```

The library must operate on filesystem paths and plain dictionaries/bytes so it can be unit-tested without ROS.

## 11. Tests

TDD coverage should include:

1. default bundle excludes raw bags and point-cloud map binaries
2. default bundle includes available audit/map metadata files
3. algorithm map metadata is discovered from the frozen manifest, not hard-coded IDs
4. missing optional artifacts are listed in `missing` without failing
5. `--include-reports` adds report/PNG files while default mode does not
6. archive members use run-relative paths
7. local Git diff is captured without changing the working tree
8. main CLI exposes `bundle --run`, `--include-reports`, and `--output`
9. invalid run manifest fails closed
10. generated archive can be opened and its `bundle_manifest.json` matches actual included members
11. bundling does not create staging files inside the run except the final archive
12. the output archive never includes itself recursively

## 12. Non-Goals

This feature does not:

- upload files automatically
- rerun algorithms
- rerun standardization
- regenerate reports
- alter benchmark results
- compress raw bags
- replace the normal run artifact structure

It is only a portable diagnostic packaging layer over existing benchmark artifacts.
