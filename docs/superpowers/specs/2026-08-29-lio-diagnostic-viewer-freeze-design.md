# LIO Diagnostic Viewer + Frozen Experiment Report Design

Date: 2026-08-29
Status: Approved design, implementation not started
Branch: `feat/phase-aware-benchmark`

## 1. Goal

Extend the existing offline LIO benchmark viewer without changing benchmark metric definitions. The result must support:

1. Viewer-local Chinese/English presentation with `zh-CN` as the default UI language.
2. Clickable anomaly review that moves the active `bag_time` cursor to the selected anomaly window and highlights the relevant algorithm.
3. Raw LiDAR projection into the selected algorithm's displayed world frame using exactly the same point-time, extrinsic, trajectory-pose, and baseline-alignment convention as the existing reconstructed map comparison.
4. An immutable experiment freeze step that generates one provenance bundle plus both HTML and PDF reports with embedded figures.

The feature remains a display, review, and archival layer. It must not upgrade baseline-relative diagnostic quantities into absolute accuracy claims.

## 2. Non-goals

This change does not:

- add independent ground truth;
- rename existing metric schema keys into Chinese;
- redefine trajectory health, map health, anomaly thresholds, phase classification, or resource alignment;
- patch the Rerun native application UI itself;
- replace Rerun's 3D and time-series renderer with a custom WebGL stack;
- introduce a remote database, user accounts, or cloud service;
- treat provisional greenhouse calibration as independently verified calibration;
- overwrite a previously frozen experiment snapshot;
- expose experiment freezing as a web-button action in v1; freezing is a CLI operation in this design.

## 3. Current invariants to preserve

The implementation must preserve these existing contracts:

- `diagnostic_timeline.json` uses one LiDAR-header-derived bag-relative origin.
- Complete greenhouse algorithms use `strict/clock-anchored` resource alignment.
- The primary cross-algorithm discontinuity comparison uses the shared fixed-rate diagnostic timeline; native-output discontinuities remain audit evidence.
- Point-cloud indexing stores rosbag message IDs/timestamps only. Raw point-cloud bytes remain in the source sqlite bag.
- Existing reconstructed map comparison is baseline-relative diagnostic visualization, not native-map or ground-truth accuracy evidence.
- The report metric class remains `relative-to-baseline/diagnostic/non-ground-truth` when no independent GT is present.

## 4. Architecture overview

```text
frozen benchmark artifacts
        |
        +--> recording/projection layer --------> native Rerun viewer
        |            |
        |            +--------------------------> Rerun WebViewer
        |                                             |
        |                                             +--> thin Chinese-first control shell
        |
        +--> experiment freezer
                     |
                     +--> freeze_manifest.json
                     +--> report_data.json
                     +--> deterministic evidence images
                     +--> experiment.rrd
                     +--> offline HTML report
                     +--> direct PDF report
```

The benchmark core remains upstream and immutable from the viewer/report perspective.

## 5. Viewer modes and web technology

The CLI keeps native mode and adds web mode:

```text
lio-benchmark viewer --mode native
lio-benchmark viewer --mode web
```

### 5.1 Native mode

Native mode remains the fast inspection path using the Rerun Python SDK. It keeps algorithm entity visibility, maps/trajectories, LiDAR LODs, synchronized resource curves, anomaly events, and `.rrd` save.

Native mode does not promise programmatic click-to-seek behavior.

### 5.2 Web mode

Web mode is the formal interactive diagnosis path. It uses the framework-agnostic package:

```text
@rerun-io/web-viewer@0.36.3
```

The version must match the pinned Python `rerun-sdk==0.36.3` for this branch.

The local shell is a small TypeScript application built with Vite. It does not use React. If the selected Vite version requires explicit WebAssembly/top-level-await plugins for Rerun, those plugins are pinned in the viewer package manifest.

The shell owns only:

- algorithm multi-select;
- selected world-projection algorithm;
- LiDAR LOD selection;
- anomaly-window list;
- language selector;
- selected anomaly summary.

Rerun remains responsible for 3D, timeline, scalar-series, selection, and entity rendering.

### 5.3 Web data source

The Python viewer/recording process serves or exposes the generated Rerun stream/recording through a local Rerun-supported URL. The web shell connects to that URL; it does not parse `.rrd` itself.

The local shell must remain usable without internet access after dependencies have been installed/built.

## 6. Localization design

### 6.1 CLI contract

Add:

```text
--lang zh-CN|en
```

Default: `zh-CN`.

Only repository-owned presentation text is translated. JSON/CSV keys remain stable English identifiers.

### 6.2 Translation ownership

Use one repository-owned translation table/module for:

- view titles;
- anomaly type names;
- health/status labels;
- report section headings;
- viewer/report warnings;
- control labels.

Examples:

```text
position_jump -> 位置突变
 yaw_jump      -> 航向突变
Map + trajectories -> 地图与轨迹
Current raw LiDAR  -> 当前原始激光点云
World LiDAR        -> 世界坐标点云
```

Canonical algorithm names such as `FAST-LIVO2`, `Point-LIO`, and `GLIM full SLAM` are not translated.

### 6.3 Font policy

No font binaries are committed or bundled.

HTML uses a system-font fallback list containing common CJK fonts.

PDF generation searches a documented set of local CJK font paths/families. If none is available, PDF generation fails clearly with an installation instruction instead of silently producing missing glyphs.

## 7. Anomaly click-to-seek design

### 7.1 Source of truth

Anomaly cards come only from `metrics/diagnostic_timeline.json` `anomaly_windows`.

No new anomaly detector is introduced.

### 7.2 Deterministic target time

For each window:

```text
seek_time_s = 0.5 * (start_bag_time_s + end_bag_time_s)
seek_time_ns = round(seek_time_s * 1e9)
```

The conversion to nanoseconds is required because Rerun WebViewer time-timeline control uses nanoseconds.

### 7.3 Interaction contract

Clicking a window must:

1. obtain the active recording ID;
2. set the active timeline to `bag_time`;
3. call WebViewer time control with `seek_time_ns`;
4. set playback to paused;
5. select/highlight that algorithm in the shell;
6. set that algorithm as the world-LiDAR projection selection for the event;
7. leave other loaded algorithms available for manual comparison.

Seeking does not mutate benchmark artifacts.

## 8. World-frame LiDAR design

### 8.1 Diagnostic semantics

The world point cloud means:

> the selected raw LiDAR points placed into the benchmark's displayed baseline-relative world according to algorithm X.

It does not mean independently verified absolute world coordinates.

### 8.2 Exact projection math

The implementation must reuse/refactor the existing map-reconstruction math from `visualize_baseline_maps.py` rather than create a simplified transform path.

For Livox CustomMsg, each selected point uses:

```text
point_time_s = header_time_s + offset_time_ns * 1e-9
```

For each point time, the selected algorithm pose is obtained from the standardized trajectory using:

- linear XYZ interpolation;
- quaternion `Slerp` for the full 3D orientation.

The LiDAR point is then transformed using the run manifest's LiDAR extrinsic exactly as the existing reconstructed-map path does:

```text
lidar_point
  -> extrinsic_rotation / extrinsic_translation
  -> algorithm 3D rotation + position at point_time
  -> initial-yaw + translation baseline alignment
  -> subtract shared display origin
  -> displayed world point
```

This is the same mathematical chain as the existing `reconstruct_map(...)` comparison path.

### 8.3 Calibration disclosure

The source calibration confidence is carried into viewer/report metadata. The feature does not relabel provisional/mixed calibration as verified.

### 8.4 Pose coverage policy

No extrapolation is allowed.

Points whose timestamps fall outside the trajectory coverage are omitted. If the selected frame has no usable projected points after coverage/range checks, the UI reports `pose unavailable`/`无可用位姿` for that frame.

### 8.5 Raw and projected entities

Keep independent entities:

```text
/sensor/raw_lidar/<lod>
/world_lidar/<algorithm>/<lod>
```

The raw sensor-local frame is always available as audit context whenever that frame was logged.

### 8.6 LOD policy

Default point strides:

```text
dense=10
medium=20
sparse=80
```

One source message is deserialized once at the densest requested stride, then coarser LODs are derived in memory.

### 8.7 Logging defaults

```text
raw LiDAR: sampled every 1 s + anomaly-near frames
world LiDAR: anomaly-near frames only
```

An explicit `--world-pointcloud-mode sampled` enables periodic world projection.

## 9. Experiment freeze design

### 9.1 CLI

```text
lio-benchmark freeze \
  --run <RUN> \
  --baseline fast_livo2 \
  --lang zh-CN \
  --html \
  --pdf
```

If neither `--html` nor `--pdf` is supplied, both are generated.

### 9.2 Snapshot identity

Every freeze creates a new non-overwriting directory:

```text
<RUN>/frozen/<run_id>_<utc_timestamp>_<benchmark_git_short_sha>/
```

If the exact target already exists, the command fails rather than replacing it.

### 9.3 Snapshot structure

```text
freeze_manifest.json
report_data.json
evidence/
  overview/
  maps/
  trajectories/
  resources/
  anomalies/
report/
  index.html
  report.pdf
viewer/
  experiment.rrd
```

### 9.4 Freeze state

The snapshot is created first with:

```text
freeze_state = INCOMPLETE
```

Only after every requested report/artifact and its hash has been generated successfully is it atomically updated to:

```text
freeze_state = COMPLETE
```

A failed freeze is never reported as complete.

### 9.5 Provenance manifest

`freeze_manifest.json` records provenance, not analysis prose. It includes:

- schema version;
- freeze state and timestamp;
- source run path/run ID/run state;
- benchmark repository branch and commit SHA;
- baseline algorithm;
- metric class;
- report language;
- dataset bag path, byte size, and SHA-256;
- benchmark config path and SHA-256;
- algorithm repository/version/commit evidence from the run manifest;
- algorithm config path/hash when available;
- patch path/hash when available;
- source artifact path/size/hash entries for report-critical metrics, trajectories, maps, diagnostic timeline, resource timelines, and point-cloud frame index;
- generated artifact path/size/hash entries for report data, HTML, PDF, evidence images, and RRD.

### 9.6 Large asset policy

Do not duplicate the full rosbag or large PLY map assets by default. Record their path, size, and SHA-256. Small report-critical JSON/CSV/config/evidence files may be copied into the freeze bundle for portability.

## 10. Shared report data contract

`report_data.json` is the only semantic input to both HTML and PDF rendering.

It is built from the current-run/frozen artifact model and the existing `current_run_report.py` semantics. It must not independently reinterpret benchmark health or accuracy.

Required sections:

- experiment metadata;
- dataset and timing evidence;
- calibration source/confidence disclosure;
- algorithm versions/config provenance;
- run lifecycle/health table;
- trajectory summary;
- baseline-relative diagnostic summary;
- map-health summary;
- resource summary;
- anomaly summary;
- selected anomaly cases;
- current-run evidence-based conclusions;
- reproducibility checklist;
- explicit no-GT diagnostic disclaimer.

## 11. Evidence image policy

### 11.1 Existing figures

Reuse valid current-run figures when present, including:

- trajectory/comparison dashboard;
- XY/XZ map comparison;
- 10 Hz position-step plot;
- 10 Hz yaw-step plot;
- aligned CPU plot;
- aligned RSS plot.

### 11.2 Deterministic anomaly evidence

Reports use deterministic static figures rather than screenshots of the interactive viewer.

A selected anomaly case can include:

- local trajectory crop;
- raw LiDAR frame;
- selected algorithm world-projected LiDAR frame;
- baseline world-projected LiDAR frame when different;
- local CPU/RSS crop;
- local position-step/yaw-step crop.

The point-cloud images use the same projection helper as the Viewer.

### 11.3 Case selection

PDF detailed-case selection is deterministic:

1. highest severity first;
2. include at least one `position_jump` if present;
3. include at least one `yaw_jump` if present;
4. include at least one failed/crashed algorithm case when anomaly evidence exists;
5. deduplicate windows;
6. default maximum is 6 detailed cases.

HTML includes the complete anomaly table and may show all generated detailed cases.

The selected window IDs are stored in `report_data.json`.

## 12. HTML report

HTML is the browsable offline experiment archive.

Rendering uses Jinja2 templates owned by the repository. Jinja2 is pinned in a report-specific requirements file, not the core benchmark environment.

Required structure:

1. 实验摘要 / Experiment Summary
2. 数据集与实验条件 / Dataset and Conditions
3. 算法版本与配置 / Algorithm Versions and Configuration
4. 运行健康状态 / Runtime Health
5. 轨迹对比 / Trajectory Comparison
6. 地图一致性 / Map Consistency
7. 性能开销 / Resource Usage
8. 时间域异常分析 / Temporal Anomaly Analysis
9. 典型异常案例 / Representative Cases
10. 当前结论与下一步 / Conclusions and Next Steps
11. 可复现性清单 / Reproducibility Checklist

The HTML contains only local asset links and remains viewable offline.

## 13. PDF report

PDF is the immutable human-readable snapshot.

The v1 PDF backend is ReportLab, pinned in the report-specific requirements file.

It renders directly from `report_data.json` and the same evidence images used by HTML. It is not generated by browser-printing the HTML.

The PDF must support:

- CJK system-font registration;
- tables;
- embedded PNG/JPEG evidence;
- page breaks and headings;
- footer/header provenance fields;
- the no-GT diagnostic disclaimer.

No font file is distributed with the project.

## 14. Conclusions policy

Permitted examples:

- `Point-LIO is closest to FAST-LIVO2 under the current baseline-relative trajectory diagnostic.`
- `GLIM full SLAM shows a compact correction window around 353-354 s.`
- `KISS-ICP shows large yaw-discontinuity windows in this run.`
- `DLIO did not complete the full run and is excluded from healthy whole-run recommendation.`

Forbidden examples:

- `Point-LIO has the best absolute accuracy.`
- `FAST-LIVO2 is ground truth.`
- `GLIM is objectively inaccurate because it differs from FAST-LIVO2.`
- `The reconstructed comparison PLY is the algorithm's native map.`

## 15. Component boundaries

Implementation must keep focused modules instead of continuing to enlarge `rerun_diagnostic_viewer.py`.

Target responsibilities:

```text
evaluators/viewer_i18n.py
  translation keys and language lookup

evaluators/viewer_projection.py
  shared point-time extraction, pose interpolation, extrinsic/world projection
  implemented by refactoring/reusing reconstruct-map math

evaluators/rerun_diagnostic_viewer.py
  Rerun recording builder and native viewer entry

benchmark_base/web_viewer/
  package.json / Vite config / TypeScript shell / WebViewer integration

evaluators/freeze_experiment.py
  freeze lifecycle, provenance, hashing, non-overwrite policy

evaluators/report_data.py
  one report model from frozen/current-run artifacts

evaluators/report_evidence.py
  deterministic static evidence image generation

evaluators/report_html.py
  Jinja2 offline HTML renderer

evaluators/report_pdf.py
  ReportLab PDF renderer

tests/test_viewer_i18n.py
tests/test_viewer_projection.py
tests/test_rerun_diagnostic_viewer.py
tests/test_freeze_experiment.py
tests/test_report_data.py
tests/test_report_evidence.py
tests/test_report_html.py
tests/test_report_pdf.py
```

## 16. Target CLI surface

```text
lio-benchmark viewer \
  --run <RUN> \
  --mode native|web \
  --lang zh-CN|en \
  --baseline fast_livo2 \
  --algorithms <csv> \
  --pointcloud-mode none|anomaly|sampled \
  --pointcloud-period 1.0 \
  --point-lods 10,20,80 \
  --world-pointcloud-mode none|anomaly|sampled \
  --world-algorithm <algorithm>

lio-benchmark freeze \
  --run <RUN> \
  --baseline fast_livo2 \
  --lang zh-CN|en \
  --html \
  --pdf \
  --max-anomaly-cases 6
```

Backward compatibility: existing native Viewer usage remains valid when new flags are omitted, except repository-owned labels default to Chinese.

## 17. Validation strategy

### 17.1 Unit/static tests

Cover:

- translation lookup/fallback;
- CLI mode/language parsing;
- deterministic anomaly midpoint and seconds-to-nanoseconds conversion;
- algorithm selection state;
- full 3D trajectory pose interpolation with Slerp;
- point-level Livox offset-time handling;
- extrinsic + pose + baseline-alignment projection on synthetic points;
- trajectory-coverage rejection/no extrapolation;
- LOD reuse contract;
- SHA-256 manifest entries;
- non-overwrite freeze policy;
- INCOMPLETE -> COMPLETE freeze-state transition;
- deterministic anomaly case selection;
- HTML headings/assets/disclaimer;
- PDF missing-CJK-font failure;
- PDF smoke generation when a supported local font exists.

Extend `evaluators/check_phase_pipeline.sh` with pure/static tests. Browser/native GUI tests are documented local integration checks, not headless static-gate requirements.

### 17.2 Real-run acceptance

Use:

```text
/home/yangxuan/lio_benchmark_runs/greenhouse_full623_round1_001
```

Acceptance requirements:

- existing benchmark algorithms are not rerun;
- resource alignment remains `strict/clock-anchored`;
- GLIM full SLAM `353.00-354.00 s` window seeks to its deterministic midpoint;
- KISS-ICP `333.30-333.40 s` yaw window is discoverable when KISS is loaded;
- raw and world LiDAR coexist;
- world projection visibly changes when the selected algorithm changes;
- projection uses per-point time/full orientation rather than frame-time/yaw-only shortcuts;
- HTML and PDF both originate from the same `report_data.json`;
- freeze manifest hashes source diagnostics and generated reports;
- a second freeze creates a new snapshot and leaves the first unchanged.

## 18. Dependency/environment policy

- Python Rerun: `rerun-sdk==0.36.3`.
- Web Rerun: `@rerun-io/web-viewer@0.36.3`.
- Web shell: TypeScript + Vite, no React.
- HTML templates: Jinja2, exact version pinned during implementation.
- PDF: ReportLab, exact version pinned during implementation.
- Viewer/report dependencies stay outside the core benchmark dependency set.
- Use the already validated `.venv-viewer --system-site-packages` pattern so the viewer can access ROS message types without replacing Ubuntu's compatible NumPy/SciPy pair.
- Do not require NumPy 2.x in the benchmark environment.
- Do not vendor fonts.

## 19. Delivery decomposition

Because this design contains two substantial but connected subsystems, implementation planning will be split into two plans sharing this spec.

### Plan A — Viewer interaction and projection

1. localization module + native labels;
2. shared projection helper refactored from current map reconstruction;
3. native world-LiDAR entity;
4. web shell with algorithm selection and anomaly click-to-seek;
5. real-run Viewer acceptance.

### Plan B — Experiment freeze and reports

1. freeze lifecycle/provenance/hash model;
2. shared report-data model;
3. deterministic evidence-image generator;
4. offline HTML report;
5. ReportLab PDF report;
6. frozen Round1 acceptance.

Plan B consumes the shared projection helper from Plan A for anomaly point-cloud evidence.

## 20. Definition of done

The complete feature is done when:

- the existing native Viewer still opens current runs;
- repository-owned Viewer/report UI defaults to Chinese and can switch to English;
- web mode can click an anomaly window and deterministically move `bag_time`;
- selected-algorithm world LiDAR uses the same point-time/extrinsic/full-pose/alignment math as map reconstruction;
- `lio-benchmark freeze` produces a non-overwriting provenance snapshot with explicit completion state;
- HTML and PDF share one report-data model and include deterministic evidence figures;
- reports preserve no-GT/baseline-relative diagnostic semantics;
- all new static tests and the existing phase/comparison gate pass on the Ubuntu benchmark host;
- greenhouse Round1 acceptance completes without rerunning the ten algorithms.
