# Native Viewer + Freeze + Export Design

Date: 2026-08-30
Status: Awaiting user review
Branch: `feat/phase-aware-benchmark`
Supersedes: `docs/superpowers/specs/2026-08-29-lio-diagnostic-viewer-freeze-design.md` where it treated WebViewer as the formal interactive diagnosis path.

## 1. Decision

The formal delivery path for `lio_benchmark_tools` is now:

```text
benchmark/evaluate
      |
      +--> diagnose --------> Native Rerun viewer
      |
      +--> freeze ----------> immutable frozen experiment bundle
                                  |
                                  +--> diagnostic.rrd
                                  +--> report_data.json
                                  +--> evidence images
                                  +--> HTML report
                                  +--> PDF report
                                  +--> provenance + hashes

frozen bundle
      +--> open   ----------> Native Rerun
      +--> export ----------> human-readable / machine-readable deliverables
```

Rerun WebViewer is retained only as an experimental capability. It is not a release gate, not the default viewer, and not required for experiment acceptance.

## 2. Why this supersedes the previous design

The existing Native Rerun path already provides the interactions needed for algorithm diagnosis: trajectories, current poses, resource curves, anomaly events, maps, raw LiDAR, world-projected LiDAR, LODs, and synchronized `bag_time` inspection.

The browser path adds Node/Vite/TypeScript/WebAssembly/gRPC/browser compatibility without adding benchmark semantics. The current Web-safe recording is small, while connecting the browser has still caused machine-wide memory exhaustion in local testing. Therefore browser rendering is treated as a display-layer experiment rather than a benchmark-core dependency.

No benchmark metric, health policy, alignment policy, map-comparison meaning, phase semantics, or ground-truth status changes because of this decision.

## 3. Goals

1. Keep Native Rerun as the stable interactive diagnosis tool.
2. Freeze a completed run into a non-overwriting, provenance-complete experiment snapshot.
3. Make the frozen snapshot directly reopenable without replaying ROS bags or rerunning algorithms.
4. Generate offline HTML and PDF reports from one shared report-data model.
5. Export figures and machine-readable summaries for paper writing, reviews, and acceptance records.
6. Preserve explicit `relative-to-baseline/diagnostic/non-ground-truth` semantics when independent GT is absent.
7. Avoid duplicating multi-gigabyte source bags or large PLY files by default.

## 4. Non-goals

This design does not:

- add independent ground truth;
- redefine ATE/RPE or introduce absolute-accuracy claims;
- change trajectory standardization, resource alignment, anomaly thresholds, or map-health calculations;
- replace Rerun native rendering with a custom desktop UI;
- require WebViewer to work before a release can ship;
- make the frozen bundle a remote database or cloud service;
- duplicate the complete source rosbag or all large map assets by default;
- distribute font binaries;
- overwrite an existing frozen snapshot.

## 5. Stable interactive path: Native Rerun

The existing command remains the formal inspection path:

```text
lio-benchmark viewer --run <RUN> --mode native
```

Native defaults stay suitable for diagnosis and may expose existing options for algorithm selection, baseline selection, reconstructed map visibility, raw/world LiDAR mode and LOD, `.rrd` save, and synchronized resource/anomaly timelines.

The native viewer is for interactive analysis. Static paper/report evidence must be generated deterministically by repository-owned plotting/report code rather than screenshots of the application.

## 6. WebViewer status

`--mode web` remains available only as `experimental` while the current branch still contains the implementation.

Rules:

- native remains the default;
- Web-specific failures do not fail benchmark acceptance or freeze/export acceptance;
- no new release-critical feature depends on WebViewer;
- current Web OOM investigation is paused;
- Web code is not deleted in this change, preserving prior work and allowing future re-evaluation;
- documentation must label Web mode experimental and recommend Native Rerun for normal use.

The unfinished `--web-profile` diagnostic work is not part of the new P0 delivery path and does not need to be completed before freeze/export implementation.

## 7. Freeze command

### 7.1 CLI contract

```text
lio-benchmark freeze --run <RUN> [--baseline fast_livo2] [--lang zh-CN|en]
```

Default output location:

```text
<RUN>/frozen/<run_id>_<utc_timestamp>_<benchmark_git_short_sha>/
```

Each invocation creates a new directory. Existing snapshots are never replaced.

### 7.2 Freeze lifecycle

A freeze begins as `freeze_state = INCOMPLETE` and is promoted atomically to `freeze_state = COMPLETE` only after every required artifact and hash has been generated successfully. A failed run leaves auditable incomplete state rather than pretending to be complete.

### 7.3 Frozen bundle layout

```text
<frozen-run>/
  freeze_manifest.json
  report_data.json
  source/
    manifest.json
    metrics/
    configs/
  evidence/
    overview/
    trajectories/
    maps/
    resources/
    anomalies/
  viewer/
    diagnostic.rrd
  report/
    index.html
    report.pdf
```

Small report-critical JSON/CSV/config files are copied into the bundle. Large source assets are referenced by provenance path, byte size, and SHA-256 unless explicitly selected for copying later.

## 8. Freeze manifest

`freeze_manifest.json` is provenance, not narrative analysis. Required fields include schema version, freeze state/timestamp, source run ID/path/state, benchmark branch/commit, baseline, metric class, report language, source bag/config hashes, algorithm provenance, calibration disclosure, copied/referenced/generated artifact hashes, selected anomaly window IDs, and the Rerun SDK version used to generate the recording.

All paths inside the bundle are relative where possible. External source paths remain explicit provenance references.

## 9. Frozen Rerun recording

Freeze generates `viewer/diagnostic.rrd` using the stable Native recording builder, not the Web-specific recorder.

The recording should contain bounded evidence sufficient to reopen the experiment meaningfully without replaying the bag: selected trajectories, current poses, CPU/RSS/thread series, anomaly events, reconstructed comparison maps when reasonable, and bounded raw/world LiDAR evidence using existing point-cloud modes and LODs.

Freeze must not silently enable an unbounded full-bag point-cloud recording. Default LiDAR evidence stays anomaly-near or explicitly sampled.

## 10. `open` command

```text
lio-benchmark open <frozen-run>
```

Behavior:

1. require `freeze_manifest.json`;
2. require `freeze_state == COMPLETE`;
3. require `viewer/diagnostic.rrd`;
4. launch Native Rerun with that recording;
5. do not rerun algorithms or read the original rosbag for normal opening.

## 11. Shared report-data model

`report_data.json` is the only semantic input for both HTML and PDF rendering. It reuses existing current-run report/diagnostic semantics rather than recomputing an independent interpretation.

Required sections include experiment metadata, dataset/timing evidence, calibration disclosure, algorithm provenance, runtime health, trajectory summary, baseline-relative diagnostics, map health, resource summary, phase summary when available, anomaly summary, representative cases, evidence-based conclusions, reproducibility checklist, and the explicit no-GT disclaimer.

When `ground_truth_available=false`, all accuracy-style conclusions remain baseline-relative diagnostic language.

## 12. Static evidence

Report evidence is generated deterministically from run/frozen data rather than captured from Rerun UI. Reuse existing valid trajectory, map, fixed-rate discontinuity, CPU/RSS, comparison-dashboard, and phase figures where possible.

Representative anomaly cases are deterministic, maximum six by default: highest severity first, ensure position/yaw jump coverage when available, include failed/crashed-algorithm evidence when present, and deduplicate windows.

Point-cloud case figures reuse the same projection helper as Native viewer/map reconstruction.

## 13. HTML and PDF

`report/index.html` is an offline archive using only local assets. Jinja2 is used in a report-specific dependency set.

`report/report.pdf` is generated directly from `report_data.json` and evidence images using ReportLab. It supports locally installed CJK fonts, fails clearly when glyph support is unavailable, embeds evidence/tables, records provenance, includes the no-GT disclaimer, and distributes no font binaries.

## 14. `export` command

```text
lio-benchmark export <frozen-run> [--output <DIR>]
```

It materializes a shareable delivery directory from immutable frozen data without modifying the bundle:

```text
<output>/
  report.html
  report.pdf
  figures/
  metrics/
    summary.json
    summary.csv
  provenance/
    freeze_manifest.json
```

`export` uses frozen data only. If frozen HTML/PDF exist and their hashes are valid, export reuses them rather than generating different content.

## 15. Command surface after convergence

```text
lio-benchmark run ...
lio-benchmark evaluate --run <RUN>
lio-benchmark diagnostics --run <RUN>
lio-benchmark viewer --run <RUN>              # Native default
lio-benchmark freeze --run <RUN>
lio-benchmark open <frozen-run>
lio-benchmark export <frozen-run>
```

Legacy commands remain compatible unless separately deprecated.

## 16. Component boundaries

```text
evaluators/rerun_diagnostic_viewer.py
  stable Native Rerun recording/viewer behavior

evaluators/freeze_experiment.py
  snapshot identity, lifecycle, copying, hashing, manifest

evaluators/report_data.py
  shared semantic report model

evaluators/report_evidence.py
  deterministic evidence generation

evaluators/report_html.py
  offline HTML renderer

evaluators/report_pdf.py
  PDF renderer

benchmark_base/lio_benchmark/entry.py
benchmark_base/lio_benchmark/postprocess.py
  CLI/orchestration only
```

Do not continue growing the Web server or Web recorder as part of P0.

## 17. Error handling

Freeze fails clearly when required run artifacts are missing, never overwrites a snapshot, and never marks partial output complete. Hashing/report/RRD failures preserve `INCOMPLETE` state and identify the failed artifact.

`open` fails on incomplete/missing frozen RRD. `export` fails on missing/invalid frozen artifacts rather than falling back to mutable live-run state.

## 18. Testing strategy

Implementation follows TDD. Required coverage includes freeze naming/no-overwrite, INCOMPLETE-to-COMPLETE lifecycle, SHA-256/provenance correctness, large-asset reference policy, Native `.rrd` generation, `open` behavior without replay, no-GT report semantics, deterministic anomaly selection, offline HTML, PDF/CJK failure path, export-from-frozen-only behavior, Native viewer regression, and unchanged benchmark metric/diagnostic tests.

WebViewer tests may remain, but are not P0 acceptance gates.

## 19. P0 acceptance criteria

Using one existing completed benchmark run, P0 must be able to:

1. open the normal Native viewer;
2. run `lio-benchmark freeze --run <RUN>` without modifying source results;
3. produce a new immutable `COMPLETE` frozen directory;
4. verify provenance/hashes for generated/captured artifacts;
5. reopen `viewer/diagnostic.rrd` with `lio-benchmark open <frozen-run>` without bag replay;
6. read offline HTML and PDF reports;
7. run `lio-benchmark export <frozen-run>` to a separate delivery directory;
8. preserve explicit non-ground-truth diagnostic wording;
9. pass existing benchmark and Native viewer regressions.

## 20. Implementation order

1. freeze core: identity, lifecycle, hashing, manifest, small-artifact copy;
2. frozen Native `.rrd` generation;
3. shared `report_data.json` and deterministic evidence;
4. HTML renderer;
5. PDF renderer;
6. `open` command;
7. `export` command;
8. documentation and release acceptance regression.

WebViewer receives no P0 implementation work beyond documentation/status cleanup needed to prevent it from being presented as default/recommended.
