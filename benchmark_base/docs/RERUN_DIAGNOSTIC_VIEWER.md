# Native Rerun diagnostic viewer and frozen delivery

The Native Rerun path is the formal interactive diagnosis and frozen-delivery path for the current P0 benchmark workflow. It is a display/inspection layer over benchmark artifacts and does not redefine trajectory health, map health, resource alignment, anomaly thresholds, or metric semantics.

Without independent ground truth, baseline-relative trajectory/map quantities remain `relative-to-baseline/diagnostic/non-ground-truth`. They are not ATE/RPE or absolute-accuracy rankings.

The WebViewer implementation remains available for experimentation and UI development, but it is **not** the P0 acceptance path and must not be used as a fallback when Native freeze/open/export fails.

## 1. Live-run prerequisites

Before interactive diagnosis or freeze, generate the normal benchmark diagnostics. Build the point-cloud index only when bounded raw/world LiDAR evidence is wanted:

```bash
RUN=/path/to/run

benchmark_base/bin/lio-benchmark diagnostics \
  --run "$RUN" \
  --baseline fast_livo2 \
  --hz 10 \
  --with-pointcloud-index
```

The core Freeze path requires the run manifest, run status, comparison metrics, trajectory-discontinuity diagnostics, unified diagnostic timeline, standardized trajectories, and per-algorithm diagnostic timeline CSVs. Maps, phase analysis, point-cloud index, resource curves, and static figures are optional evidence and are disclosed as such.

When indexed LiDAR evidence is enabled, source the ROS overlays that provide the exact message type used by the bag:

```bash
source /opt/ros/humble/setup.bash
source /home/yangxuan/agt_navigation_v2/install/setup.bash
source /home/yangxuan/lio_benchmark_algorithms/adapter_ws/install/setup.bash
```

## 2. Tested Native viewer environment

The tested Native Viewer SDK is pinned to:

```text
rerun-sdk==0.36.3
```

Keep the ROS/benchmark scientific Python stack separate from incompatible user-site packages. A viewer venv may inherit ROS/system packages:

```bash
python3 -m venv --system-site-packages .venv-viewer
source .venv-viewer/bin/activate
python -m pip install --no-deps rerun-sdk==0.36.3
```

Report dependencies are kept separate in `benchmark_base/requirements-report.txt`. Font binaries are never committed or distributed by this repository.

## 3. Native live viewer

Native mode is the normal inspection path before freezing:

```bash
benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --mode native \
  --baseline fast_livo2 \
  --lang auto \
  --algorithms fast_livo2,point_lio,lio_sam_no_loop,glim_full_slam
```

Language policy:

```text
--lang auto   recommended mode-aware default
--lang zh-CN  Chinese where the local Rerun font stack supports it
--lang en     English
```

For the tested Ubuntu/Rerun 0.36.3 path, Native labels default to English because some Rerun font stacks do not render CJK reliably. Machine-readable JSON/CSV keys always remain English.

## 4. Bounded raw LiDAR and point density

Raw LiDAR stays in sensor-local coordinates:

```text
sensor/raw_lidar/dense
sensor/raw_lidar/medium
sensor/raw_lidar/sparse
```

Default strides:

```text
dense=10
medium=20
sparse=80
```

Configure them with:

```bash
--point-lods 10,20,80
```

Each selected sqlite message is deserialized once at the dense stride. Medium/sparse LODs are derived from that dense cloud in memory.

Selection modes:

```text
none     no raw LiDAR
anomaly  anomaly-near indexed frames only
sampled  periodic frames plus anomaly-near frames
```

Freeze never silently enables unbounded full-bag point-cloud recording. Its default indexed LiDAR evidence is anomaly-near. If the index, sqlite source, ROS message runtime, or a valid pose is unavailable, the optional layer is omitted and the omission is recorded rather than invalidating the whole snapshot.

## 5. World LiDAR projection

World LiDAR uses:

```text
world_lidar/<algorithm>/dense
world_lidar/<algorithm>/medium
world_lidar/<algorithm>/sparse
```

The projection chain is shared by Native visualization and deterministic static point-cloud report evidence:

```text
LiDAR header + per-point offset_time
  -> point timestamp
  -> manifest lidar_to_imu extrinsic
  -> standardized trajectory XYZ interpolation + quaternion Slerp
  -> algorithm pose
  -> initial-yaw + translation alignment to baseline
  -> shared display origin
```

The result answers where the same measured scan would be placed in the displayed comparison world according to each algorithm. It is not independent ground truth.

Pose interpolation respects `evaluation.max_pose_interpolation_gap_s`; points without a valid pose are omitted instead of extrapolated.

## 6. Native `.rrd` output

A normal live-run recording can still be generated directly:

```bash
OUT="$RUN/viewer/diagnostic.rrd"
mkdir -p "$(dirname "$OUT")"

benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --mode native \
  --lang auto \
  --pointcloud-mode anomaly \
  --world-pointcloud-mode anomaly \
  --save "$OUT" \
  --no-spawn
```

For delivery, prefer `lio-benchmark freeze`; it creates the `.rrd` together with provenance, report data, static evidence, HTML, and PDF under one immutable snapshot lifecycle.

## 7. Immutable Freeze

Create a new snapshot without modifying the source run:

```bash
benchmark_base/bin/lio-benchmark freeze \
  --run "$RUN" \
  --baseline fast_livo2 \
  --lang zh-CN
```

Each invocation creates a new directory:

```text
<RUN>/frozen/<run_id>_<utc_timestamp>_<benchmark_git_short_sha>/
```

The lifecycle is:

```text
prepare INCOMPLETE snapshot
  -> copy/hash core source artifacts
  -> copy/hash declared algorithm configs
  -> record calibration and bag provenance
  -> build bounded Native diagnostic.rrd
  -> build shared report_data.json
  -> copy/generate deterministic evidence
  -> render offline HTML
  -> render PDF
  -> re-verify captured/generated SHA-256 + size
  -> atomically promote to COMPLETE
```

A failed stage leaves an auditable `INCOMPLETE` snapshot with `failure.stage`, `failure.type`, and `failure.message`. Existing snapshots are never overwritten.

The snapshot manifest records source-run identity, benchmark branch/commit, bag hash, algorithm provenance, calibration disclosure, copied config hashes, optional-evidence availability, selected anomaly windows, Rerun SDK metadata, and generated-artifact hashes.

## 8. Deterministic report evidence

`report_data.json` is the shared semantic input for HTML and PDF. It reuses current-run report/health semantics instead of recomputing an independent ranking.

Representative anomalies are selected deterministically, with a maximum of six by default: severity first, preserve position/yaw coverage when available, preserve failed/crashed-algorithm evidence when available, and deduplicate window IDs.

Static evidence is generated from benchmark/frozen data rather than screenshots of the Rerun UI. If indexed LiDAR is usable, the nearest indexed frame to each representative anomaly is rendered with raw XY plus baseline/target world projections using the shared projection helper. If that optional rendering cannot be produced, the evidence manifest records the omission.

## 9. Open a frozen experiment

Open only a completed frozen recording:

```bash
FROZEN=/path/to/run/frozen/<snapshot>
benchmark_base/bin/lio-benchmark open "$FROZEN"
```

`open` requires:

- `freeze_manifest.json`;
- `freeze_state == COMPLETE`;
- registered `viewer/diagnostic.rrd`;
- matching recorded SHA-256 and byte size.

Normal opening does **not** replay algorithms, read the original rosbag, or fall back to mutable live-run state.

## 10. Export a delivery directory

Materialize a shareable directory from frozen data only:

```bash
benchmark_base/bin/lio-benchmark export "$FROZEN" \
  --output /path/to/delivery
```

The delivery contains the frozen HTML/PDF, evidence figures, metric summary data, and freeze provenance. Export verifies registered hashes before copying and does not modify the immutable snapshot.

The HTML report is self-contained for report images via local data URIs, so copying `report/index.html` to delivery `report.html` does not create broken evidence links. Evidence files are still exported separately for audit and manual inspection.

## 11. Experimental WebViewer status

WebViewer code remains in the repository for UI experiments and compatibility investigation. It is not a P0 acceptance gate, and new freeze/export implementation must not depend on the Web recorder/server.

If explicitly testing the Web shell, keep the Rerun WebViewer package aligned with the Python SDK version and use the repository web tests. A Web failure must not trigger a silent replacement of the Native frozen-delivery path.

## 12. Verification gates

Focused frozen-delivery regression:

```bash
PYTHONPATH="$PWD/evaluators:$PWD/benchmark_base" python3 -m pytest -q \
  tests/test_freeze_experiment.py \
  tests/test_freeze_failure_audit.py \
  tests/test_freeze_provenance.py \
  tests/test_freeze_rerun.py \
  tests/test_report_data.py \
  tests/test_report_evidence.py \
  tests/test_report_pointcloud_evidence.py \
  tests/test_report_html.py \
  tests/test_report_pdf.py \
  tests/test_frozen_bundle.py \
  tests/test_entry_frozen_commands.py \
  tests/test_freeze_workflow.py
```

Existing Native/benchmark regressions remain required, especially:

```bash
python3 -m pytest -q \
  tests/test_viewer_projection.py \
  tests/test_rerun_diagnostic_viewer.py \
  tests/test_entry.py \
  tests/test_postprocess.py \
  tests/test_current_run_report.py \
  tests/test_diagnostic_timeline.py
```

Release acceptance must additionally use one real completed benchmark run to prove:

1. normal Native viewer opens;
2. `freeze` creates a new `COMPLETE` bundle without modifying the source run;
3. hashes/provenance verify;
4. failed/truncated algorithm evidence remains present but not ranked healthy;
5. `open` reopens the frozen `.rrd` without bag replay;
6. offline HTML/PDF are readable;
7. `export` works from frozen data only;
8. explicit no-ground-truth diagnostic wording is preserved.

Do not mark those real-run gates complete from mocked/unit tests alone.
