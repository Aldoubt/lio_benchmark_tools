# LIO Diagnostic Viewer + Frozen Experiment Report Design

Date: 2026-08-29
Status: Approved design, implementation not started
Branch: `feat/phase-aware-benchmark`

## 1. Goal

Extend the existing offline LIO benchmark viewer without changing benchmark metric definitions. The result must support:

1. Viewer-local Chinese/English presentation with `zh-CN` as the default UI language.
2. Clickable anomaly review that moves the active `bag_time` cursor to the selected anomaly window and highlights the relevant algorithm.
3. Raw LiDAR projection into the selected algorithm's world frame using the same trajectory projection convention already used by the benchmark's reconstructed map visualization.
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
- treat provisional `lidar_to_base` calibration as an independently verified greenhouse calibration;
- overwrite a previously frozen experiment snapshot.

## 3. Current invariants to preserve

The implementation must preserve these existing contracts:

- `diagnostic_timeline.json` uses one LiDAR-header-derived bag-relative origin.
- Complete greenhouse algorithms use `strict/clock-anchored` resource alignment.
- The primary cross-algorithm discontinuity comparison uses the shared fixed-rate diagnostic timeline; native-output discontinuities remain audit evidence.
- Point-cloud indexing stores rosbag message IDs/timestamps only. Raw point-cloud bytes remain in the source sqlite bag.
- Existing reconstructed map comparison is baseline-relative diagnostic visualization, not native-map or ground-truth accuracy evidence.
- The report metric class remains `relative-to-baseline/diagnostic/non-ground-truth` when no independent GT is present.

## 4. Architecture overview

The feature is split into four independent units:

```text
frozen benchmark artifacts
        |
        +--> viewer recording builder ---------> native Rerun viewer
        |            |
        |            +--------------------------> Rerun WebViewer data source
        |                                             |
        |                                             +--> thin local control shell
        |
        +--> experiment freezer
                     |
                     +--> freeze_manifest.json
                     +--> report_data.json
                     +--> evidence images
                     +--> experiment.rrd
                     +--> HTML report
                     +--> PDF report
```

The benchmark core remains upstream and immutable from the viewer/report perspective.

## 5. Viewer modes

The CLI keeps the existing native mode and adds a web mode.

```text
lio-benchmark viewer --mode native
lio-benchmark viewer --mode web
```

### 5.1 Native mode

Native mode remains the fast inspection path and continues to use the Rerun Python SDK directly. It supports the current algorithm entity tree, map/trajectory visibility, LiDAR LODs, synchronized resource curves, anomaly events, `.rrd` save, and language-aware labels where the label originates from this repository.

Native mode does not promise programmatic click-to-seek behavior because the Python-launched native viewer does not provide the same event-control surface as the embedded web viewer.

### 5.2 Web mode

Web mode is the formal interactive diagnosis path. Rerun remains responsible for 3D, timeline, scalar-series, and entity rendering. A small local control shell owns only controls that the benchmark needs:

- algorithm multi-select;
- selected world-projection algorithm;
- LiDAR LOD selection;
- anomaly-window list;
- language selector;
- selected anomaly summary;
- "freeze experiment" action only if the implementation later exposes it safely through the local process; otherwise the freeze remains a CLI operation.

The web shell communicates with the Rerun WebViewer through its supported event/time control interface rather than reimplementing visualization.

## 6. Localization design

### 6.1 CLI contract

Add:

```text
--lang zh-CN|en
```

Default: `zh-CN`.

The language option affects only repository-owned UI/report text. It never changes machine-readable schema keys.

### 6.2 Stable internal keys

Examples:

```text
position_jump
 yaw_jump
strict/clock-anchored
relative-to-baseline/diagnostic/non-ground-truth
```

remain unchanged in JSON/CSV.

Display mapping is resolved at presentation time, for example:

```text
position_jump -> 位置突变
 yaw_jump      -> 航向突变
```

### 6.3 Translation ownership

Use a small repository-owned translation module/table instead of scattered literal strings. At minimum it contains:

- view titles;
- anomaly type names;
- algorithm group descriptions if displayed;
- report section headings;
- health/status display text;
- warnings that originate from the viewer/report layer.

Algorithm canonical names such as `FAST-LIVO2`, `Point-LIO`, and `GLIM full SLAM` are not translated.

### 6.4 Font policy

No font file is committed to the repository. HTML uses a CJK-capable system-font fallback list. PDF generation performs a startup font capability check and fails with a clear installation instruction if no supported local CJK font is found.

## 7. Anomaly click-to-seek design

### 7.1 Source of truth

Anomaly cards are built only from `metrics/diagnostic_timeline.json` `anomaly_windows`. No new anomaly detector is introduced.

### 7.2 Window target time

For each anomaly window:

```text
seek_time = 0.5 * (start_bag_time_s + end_bag_time_s)
```

The UI may display start/end, peak step, event count, types, and severity, but clicking the window always seeks to the deterministic midpoint unless a later schema provides a separate canonical peak timestamp.

### 7.3 Interaction

Clicking one anomaly window must:

1. set the active timeline to `bag_time`;
2. set current time to `seek_time`;
3. pause playback;
4. select/highlight the window's algorithm in the control shell;
5. set that algorithm as the default world-LiDAR projection algorithm for the selected event;
6. keep other algorithms available for manual comparison.

### 7.4 No hidden mutation

Seeking does not change metric files, report data, algorithm selection persisted on disk, or benchmark state.

## 8. World-frame LiDAR design

### 8.1 Why this is diagnostic-only

The greenhouse config contains `lidar_to_base`, but its confidence is provisional and the overall calibration confidence is mixed. Therefore the world-point-cloud feature must not introduce a new claim that the provisional base transform has been independently validated for this dataset.

### 8.2 Projection convention

The world-point-cloud view must reuse the same standardized trajectory pose convention used by the existing reconstructed map comparison. The selected raw LiDAR frame at `bag_time=t` is transformed by the selected algorithm's interpolated standardized pose at `t`, using the same initial-yaw + translation alignment convention used for baseline-relative map/trajectory display.

This means the feature answers:

> What does this exact LiDAR scan look like when placed into the displayed world according to algorithm X?

It does not answer:

> What is the independently verified absolute world location of this scan?

### 8.3 Pose sampling

World projection uses the standardized trajectory and the same maximum interpolation-gap semantics already frozen by the benchmark. If no valid pose exists for a selected frame within the accepted interpolation contract, the world frame is omitted for that timestamp and the UI reports `pose unavailable` rather than extrapolating.

### 8.4 Raw view remains available

Keep two logically distinct entities:

```text
/sensor/raw_lidar/...              # sensor-local audit view
/world_lidar/<algorithm>/...       # selected algorithm projection
```

The raw entity is never replaced by the projected entity.

### 8.5 Point-cloud density

Retain three LODs derived from one deserialized dense selection. Default strides:

```text
dense=10
medium=20
sparse=80
```

The CLI remains configurable. The source bag message is deserialized once per selected frame; coarser LODs are derived from the dense selection in memory.

### 8.6 Logging policy

Default policy:

```text
raw LiDAR: sampled, 1 s period plus anomaly-near frames
world LiDAR: anomaly windows only
```

A separate explicit option may enable sampled world projection. This prevents `.rrd` growth from becoming the default.

## 9. Experiment freeze design

### 9.1 CLI

Add a new command:

```text
lio-benchmark freeze \
  --run <RUN> \
  --baseline fast_livo2 \
  --lang zh-CN \
  --html \
  --pdf
```

Default behavior when neither `--html` nor `--pdf` is supplied: generate both.

### 9.2 Snapshot identity

Each freeze creates a new directory and never overwrites an existing one:

```text
<RUN>/frozen/<run_id>_<utc_timestamp>_<benchmark_git_short_sha>/
```

If that exact path exists, creation fails instead of replacing it.

### 9.3 Snapshot contents

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

### 9.4 `freeze_manifest.json`

The manifest records provenance, not analysis prose. It must include:

- schema version;
- freeze timestamp;
- source run path and run ID;
- source run state;
- benchmark repository branch and commit SHA;
- baseline algorithm;
- metric class;
- dataset bag path, size, and content hash;
- benchmark config path and content hash;
- algorithm repositories/versions/commits already frozen in the run manifest;
- algorithm config paths and hashes when available;
- applied patch names/hashes when available;
- source artifact path + hash entries for report-critical metrics, trajectories, maps, diagnostic timeline, resource timelines, and point-cloud frame index;
- generated artifact path + hash entries for HTML, PDF, evidence images, report data, and RRD;
- report language.

Hashes use SHA-256.

### 9.5 Source artifacts are referenced, not rewritten

The freeze tool may copy small evidence/config/report-critical files into the freeze bundle when doing so materially improves portability, but it must not duplicate the full rosbag or large reconstructed PLY assets by default. Their source paths, sizes, and SHA-256 hashes are recorded in the manifest.

### 9.6 Failure policy

Freeze is all-or-error from the user's perspective. If PDF was requested and PDF generation fails, the command returns non-zero and marks the snapshot incomplete; it must not print a success message that implies both formats were created.

## 10. Report data contract

`report_data.json` is the single report source for both HTML and PDF. It is derived from frozen current-run artifacts and from the existing current-run report model; it does not recalculate benchmark semantics independently.

Required sections:

- experiment metadata;
- dataset and timing evidence;
- algorithm versions/config provenance;
- run lifecycle/health table;
- trajectory summary;
- baseline-relative diagnostic summary;
- map-health summary;
- resource summary;
- anomaly summary;
- selected anomaly case studies;
- conclusions generated from current-run evidence only;
- reproducibility checklist;
- explicit no-GT/diagnostic disclaimer.

## 11. Evidence image policy

### 11.1 Existing figures

Reuse existing current-run figures when valid and present, including:

- trajectory/comparison dashboard;
- XY/XZ map comparison;
- 10 Hz position-step plot;
- 10 Hz yaw-step plot;
- aligned CPU plot;
- aligned RSS plot.

### 11.2 Generated anomaly case-study images

Generate deterministic static figures for selected anomaly windows rather than relying on screenshots of the interactive viewer. Static evidence is more reproducible in reports.

Each case-study image set may include:

- local trajectory crop around the window;
- raw LiDAR frame;
- selected algorithm world-projected LiDAR frame;
- baseline world-projected LiDAR frame when the selected algorithm is not the baseline;
- local CPU/RSS crop;
- local delta-position/yaw crop.

### 11.3 Case selection

HTML includes the complete anomaly table and can include more case-study figures. PDF uses a bounded deterministic selection:

1. highest-severity windows first;
2. ensure at least one `position_jump` example if present;
3. ensure at least one `yaw_jump` example if present;
4. ensure at least one failed/crashed algorithm case if anomaly evidence exists;
5. avoid duplicate windows after those coverage rules;
6. default maximum: 6 detailed cases.

This selection is recorded in `report_data.json`.

## 12. HTML report

HTML is the browsable experiment archive.

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

The HTML report may link to local evidence files inside the freeze bundle. It must remain viewable offline.

## 13. PDF report

PDF is the immutable human-readable snapshot. It uses the same `report_data.json` and evidence images as HTML.

PDF generation is direct from Python rather than browser-printing HTML. The chosen PDF backend must support local image embedding, tables, page breaks, and local CJK font registration without committing font binaries into the repository.

The PDF contains the same semantic disclaimer as HTML and clearly labels baseline-relative metrics as diagnostic/non-ground-truth.

## 14. Conclusions policy

The report may say, for example:

- `Point-LIO is closest to FAST-LIVO2 under the current baseline-relative trajectory diagnostic.`
- `GLIM full SLAM shows a compact correction window around 353-354 s.`
- `KISS-ICP shows large yaw-discontinuity windows in this run.`
- `DLIO did not complete the full run and is excluded from healthy whole-run recommendation.`

It must not say:

- `Point-LIO has the best absolute accuracy`;
- `FAST-LIVO2 is ground truth`;
- `GLIM is objectively inaccurate because it differs from FAST-LIVO2`;
- `a reconstructed PLY is the algorithm's native map` unless the source artifact actually is a native map.

## 15. Proposed component boundaries

Implementation should keep responsibilities separated rather than enlarging `rerun_diagnostic_viewer.py` indefinitely.

Proposed files/modules:

```text
evaluators/viewer_i18n.py
  repository-owned translations only

evaluators/viewer_projection.py
  pose interpolation and raw/world LiDAR projection helpers

evaluators/rerun_diagnostic_viewer.py
  recording builder and native viewer entry

benchmark_base/web_viewer/
  thin local web shell and Rerun WebViewer integration

evaluators/freeze_experiment.py
  freeze orchestration, provenance, hashing, snapshot lifecycle

evaluators/report_data.py
  build one report-data model from current-run/frozen artifacts

evaluators/report_html.py
  offline HTML renderer

evaluators/report_pdf.py
  direct PDF renderer

tests/test_viewer_i18n.py
tests/test_viewer_projection.py
tests/test_rerun_diagnostic_viewer.py
tests/test_freeze_experiment.py
tests/test_report_data.py
tests/test_report_html.py
tests/test_report_pdf.py
```

Exact names may be adjusted during implementation planning only if required to match existing repository conventions; responsibilities must remain separated.

## 16. CLI surface

Target CLI surface:

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

The existing native viewer command behavior must remain backward compatible when the new flags are omitted, except that repository-owned labels default to Chinese according to the approved localization policy.

## 17. Validation and test strategy

### 17.1 Unit tests

Cover:

- translation lookup and fallback behavior;
- CLI language/mode parsing;
- deterministic anomaly midpoint calculation;
- algorithm entity selection logic;
- pose interpolation success/gap rejection;
- world projection on synthetic points/poses;
- LOD reuse without repeated source deserialization at the helper contract level;
- SHA-256 manifest creation;
- freeze directory no-overwrite policy;
- deterministic anomaly case selection;
- HTML contains expected headings/images/disclaimer;
- PDF generator reports missing CJK font clearly;
- PDF smoke generation when a supported font is available.

### 17.2 Repository gate

Extend `evaluators/check_phase_pipeline.sh` with new pure-Python tests. Tests that require a graphical Rerun process or browser are not part of the static gate; they receive a documented local integration command instead.

### 17.3 Real-run acceptance

Use `/home/yangxuan/lio_benchmark_runs/greenhouse_full623_round1_001` as the acceptance run.

Acceptance observations:

- all ten resource alignments remain `strict/clock-anchored`;
- GLIM full SLAM anomaly `353.00-354.00 s` is clickable and seeks to the deterministic midpoint;
- KISS-ICP `333.30-333.40 s` yaw case remains discoverable when that algorithm is loaded;
- raw and world-projected LiDAR can be visually compared without overwriting either entity;
- switching the selected projection algorithm changes only the projection view;
- HTML and PDF are generated from the same `report_data.json`;
- freeze manifest includes hashes for both reports and the source diagnostic artifacts;
- a second freeze creates a new snapshot and leaves the first untouched.

## 18. Dependency policy

- Keep `rerun-sdk==0.36.3` pinned for this branch until the integration is intentionally upgraded.
- Keep the viewer environment isolated from the benchmark's ROS/scientific Python environment, using the already validated `.venv-viewer --system-site-packages` approach.
- Do not require NumPy 2.x in the benchmark environment.
- Add report dependencies only when required by the chosen HTML/PDF implementation and pin them in a viewer/report-specific requirements file rather than the core benchmark dependency set.
- Do not vendor third-party fonts.

## 19. Delivery sequence

Implementation order is intentionally staged so each stage remains usable:

1. localization module + native-viewer labels;
2. world-projection helpers + native viewer projected entity;
3. web shell + anomaly click-to-seek + algorithm selection;
4. freeze manifest/provenance layer;
5. shared report-data model;
6. evidence image generator;
7. HTML report;
8. PDF report;
9. full real-run acceptance and documentation.

No later stage may silently redefine the benchmark outputs consumed by an earlier stage.

## 20. Definition of done

The feature is done when:

- native viewer still opens existing runs;
- web viewer offers Chinese-first controls and deterministic anomaly seeking;
- selected-algorithm world LiDAR is available with diagnostic semantics clearly labeled;
- `lio-benchmark freeze` produces a non-overwriting provenance snapshot;
- HTML and PDF use one frozen report-data model and include embedded evidence figures;
- generated reports retain the no-GT diagnostic disclaimer;
- all new static tests and the existing phase/comparison gate pass on the Ubuntu benchmark host;
- the greenhouse Round1 acceptance checklist is completed without rerunning the ten algorithms.
