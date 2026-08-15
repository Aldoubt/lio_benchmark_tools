# LIO Benchmark Tools V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `lio_benchmark_tools` into a reproducible agricultural LIO benchmark with fixed baseline registries, timestamp-based standardization, interactive 3D inspection, paper/demo reporting, and manually inspectable live-debug sessions.

**Architecture:** Keep the standard-library CLI core independent from visualization and ROS-heavy evaluators. Dataset and algorithm registries define immutable contracts; adapters produce raw outputs; standardizers normalize trajectories/maps; inspector/report/demo/live-debug consumers read only standardized artifacts or registry metadata.

**Tech Stack:** Python 3 standard library for core orchestration, ROS 2 Humble/`rosbag2_py` for bag access, NumPy/SciPy for offline map reconstruction, optional Open3D for interactive inspection, Matplotlib for figures, optional ffmpeg for GIF/MP4 assembly, shell scripts for upstream algorithm adapters.

## Global Constraints

- Work only on `feat/lio-benchmark-v2`; do not modify `main` directly.
- Preserve schema-v1 historical experiment compatibility.
- Fixed baselines: FAST-LIVO2, Point-LIO, Leg-KILO 2.0 LiDAR-IMU mode, GLIM Odometry, GLIM Full SLAM, DLIO.
- Formal performance benchmarks run algorithms individually; multi-algorithm simultaneous execution is live-debug only.
- Dataset bags are immutable and remain outside the repository.
- Topic/frame/unit adaptation belongs to explicit adapters and provenance, not silent bag/source modification.
- Standardized scan-to-pose association is timestamp based; normalized index matching is legacy exploratory behavior only.
- Native algorithm maps and unified reconstructed maps are distinct artifacts with explicit provenance.
- Missing optional Open3D/ffmpeg dependencies fail with clear feature-specific guidance and never break core benchmark commands.
- Failure runs and missing artifacts remain explicit evidence; never convert them into zero scores.

---

### Task 1: Registry Core and Fixed Baseline Records

**Files:**
- Create: `benchmark_base/lib/registry.py`
- Create: `benchmark_base/lib/__init__.py`
- Create: `benchmark_base/registry/algorithms/*.json`
- Create: `benchmark_base/registry/datasets/example_mid360.json`
- Create: `benchmark_base/tests/test_registry.py`

**Interfaces:**
- Produces `Registry(root: Path)`, `load_dataset(dataset_id)`, `load_algorithm(algorithm_id)`, `list_algorithms()`, `list_datasets()`.
- Registry records validate exact IDs, schema version 2, required modalities, runner path, topic contracts, and algorithm mode.

- [ ] Write `unittest` coverage for valid records, missing IDs, malformed records, and all six fixed baselines.
- [ ] Implement the standard-library registry loader and validation helpers.
- [ ] Add six algorithm JSON records and one portable example dataset record with placeholder local bag path explicitly marked as example-only.
- [ ] Verify all JSON records parse and IDs match filenames.
- [ ] Commit as `feat: add v2 benchmark registries`.

### Task 2: Manifest V2 and CLI Backward Compatibility

**Files:**
- Modify: `benchmark_base/bin/lio-benchmark`
- Create: `benchmark_base/tests/test_cli_manifest.py`
- Modify: `benchmark_base/config/experiment.template.json`

**Interfaces:**
- Schema v1 continues to validate exactly as before.
- Schema v2 resolves dataset/algorithm IDs through `Registry`.
- Adds CLI `list algorithms`, `list datasets`, `show algorithm`, `show dataset`.
- `init` freezes resolved dataset and algorithm registry snapshots into the run manifest.

- [ ] Add failing manifest-resolution tests for v1/v2 and invalid algorithm IDs.
- [ ] Refactor validation into schema-specific paths without changing v1 semantics.
- [ ] Make run-directory raw folders dynamic from selected algorithms while preserving standard directories.
- [ ] Add registry inspection CLI commands.
- [ ] Update experiment template to schema v2 while retaining `current_mid360.json` as historical schema v1.
- [ ] Commit as `feat: support v2 registry manifests`.

### Task 3: Timestamp-Based Trajectory Standardization

**Files:**
- Create: `benchmark_base/lib/trajectory.py`
- Create: `benchmark_base/tests/test_trajectory.py`
- Create: `evaluators/standardize_trajectory.py`

**Interfaces:**
- Standard trajectory columns: `timestamp_s,x_m,y_m,z_m,qx,qy,qz,qw,roll_rad,pitch_rad,yaw_rad,source_topic`.
- Produces `PoseSample`, `Trajectory`, `interpolate_pose(timestamp_s, tolerance_s)`.
- Quaternion interpolation uses shortest-arc SLERP implemented in the standard library core.

- [ ] Test exact sample, linear midpoint, quaternion midpoint, sign-flipped equivalent quaternions, out-of-range rejection, tolerance rejection.
- [ ] Implement CSV load/write and interpolation.
- [ ] Add a converter entry point for upstream trajectory CSVs already using benchmark columns or adapter-provided column maps.
- [ ] Commit as `feat: add timestamp trajectory standardization`.

### Task 4: Unified Map Reconstruction and Provenance

**Files:**
- Create: `evaluators/standardize_map.py`
- Create: `benchmark_base/lib/artifacts.py`
- Create: `benchmark_base/tests/test_artifacts.py`
- Deprecate-but-keep: `evaluators/visualize_frontend_comparison.py`

**Interfaces:**
- Consumes ROS 2 bag LiDAR timestamps plus standardized trajectories.
- Uses trajectory interpolation by timestamp; unmatched scans are excluded and counted.
- Writes `unified_map.ply`, `map_metadata.json`, and run-level `standardization_report.json`.
- `map_metadata.json` records `map_source`, `algorithm_id`, `dataset_id`, trajectory source, voxel, point count, generation command, and timestamp-match statistics.

- [ ] Add pure metadata/provenance tests.
- [ ] Implement timestamp extraction from message/header and MID360 absolute point-time fallback with explicit source labeling.
- [ ] Implement LiDAR-to-body transform from frozen dataset calibration.
- [ ] Implement voxel downsampling and binary PLY output.
- [ ] Keep the old visualizer callable for historical runs but label it legacy index-aligned in its docstring/report.
- [ ] Commit as `feat: standardize maps by timestamp`.

### Task 5: Leg-KILO Adapter and Unified Runner Commands

**Files:**
- Create: `evaluators/run_leg_kilo_test.sh`
- Modify: `benchmark_base/bin/lio-benchmark`
- Modify: existing runner documentation

**Interfaces:**
- Adds `run --run <run> --algorithm <id>` and `run-all --run <run>`.
- Runner invocation is registry-driven; adapter receives bag path and output directory.
- Leg-KILO baseline metadata is frozen as `mode=lidar_imu`, `leg_kinematics=false` for ordinary MID360 datasets.

- [ ] Implement registry-driven command generation and execution.
- [ ] Add Leg-KILO shell adapter without modifying upstream source automatically.
- [ ] Preserve logs and non-zero failure state under the run directory.
- [ ] Commit as `feat: add registry driven runners and leg-kilo`.

### Task 6: Live Debug Session and Failure Markers

**Files:**
- Create: `benchmark_base/lib/live_debug.py`
- Create: `benchmark_base/tests/test_live_debug.py`
- Modify: `benchmark_base/bin/lio-benchmark`

**Interfaces:**
- `lio-benchmark live prepare --dataset <id> --algorithms ...`
- Produces `session.json`, `env.sh`, ordered bag/algorithm shell scripts, `commands.md`, `rviz/`, `markers/`, `logs/`.
- `lio-benchmark mark --session ... --algorithm ... --event ... --bag-time ... --note ...` writes append-only JSON marker records.

- [ ] Test deterministic session generation, namespace isolation, remap rendering, and marker persistence.
- [ ] Generate one script per process rather than hiding processes in a supervisor.
- [ ] Generate RViz/topic/TF inspection command hints from registry records.
- [ ] Commit as `feat: add manual live debug sessions`.

### Task 7: Interactive Open3D Inspector

**Files:**
- Create: `visualization/map_inspector.py`
- Create: `visualization/presets.py`
- Create: `benchmark_base/tests/test_visualization_presets.py`
- Modify: `benchmark_base/bin/lio-benchmark`

**Interfaces:**
- `lio-benchmark inspect --run <run>` lazily imports Open3D.
- Supports algorithm visibility, native/unified selection, trajectory overlay, height/intensity/algorithm coloring, XY/XZ/YZ/perspective views, ROI presets, camera presets, Apply Camera to All, screenshot export.
- Camera/ROI presets serialize to JSON independent of Open3D runtime.

- [ ] Test preset serialization without requiring Open3D.
- [ ] Implement lazy dependency check and clear installation message.
- [ ] Implement shared-camera state across loaded algorithm maps.
- [ ] Commit as `feat: add interactive map inspector`.

### Task 8: Paper Report and README Demo Generator

**Files:**
- Create: `reporting/generate_report.py`
- Create: `reporting/generate_demo.py`
- Create: `benchmark_base/tests/test_reporting_contract.py`
- Modify: `benchmark_base/bin/lio-benchmark`
- Create: `assets/demo/README.md`

**Interfaces:**
- `lio-benchmark report --run <run>` writes comparison figures, `metrics/summary.csv`, `reports/report.md`, `reports/report.html`.
- `lio-benchmark demo --run <run> --preset <camera/roi>` renders identical-camera frames and calls ffmpeg when available.
- Demo metadata records same bag, ROI, camera path, viewport, voxel/display sampling, and selected algorithms.

- [ ] Test output naming and missing-artifact states.
- [ ] Implement paper-oriented static comparison figures using standardized artifacts.
- [ ] Implement deterministic demo frame sequence and ffmpeg command generation.
- [ ] Commit as `feat: add paper report and readme demo`.

### Task 9: Showcase README and Documentation

**Files:**
- Modify: `README.md`
- Modify: `benchmark_base/README.md`
- Modify: `benchmark_base/docs/USER_MANUAL_ZH.md`
- Create: `benchmark_base/docs/V2_WORKFLOW.md`

**Interfaces:**
- README references `assets/demo/same_bag_map_comparison.gif` relatively when the generated curated GIF is available; until then it uses a clearly marked placeholder section without inventing results.
- Documents four workflows and fixed-baseline modality table.

- [ ] Rewrite homepage around reproducibility, agricultural same-bag comparison, fixed baselines, inspector/report/live-debug workflows.
- [ ] Document exact V2 CLI flow and dependency boundaries.
- [ ] Keep historical baseline conclusions clearly labeled as exploratory/no-ground-truth.
- [ ] Commit as `docs: document lio benchmark v2`.

### Task 10: Verification and Branch Completion

**Files:** no production files unless verification exposes defects.

- [ ] Run `python3 -m unittest discover -s benchmark_base/tests -v`.
- [ ] Run `python3 -m compileall benchmark_base evaluators visualization reporting`.
- [ ] Run JSON parse/registry validation across every tracked registry record.
- [ ] On a ROS 2 Humble machine, run schema-v1 historical `validate`, then schema-v2 example validation with a locally resolved dataset copy.
- [ ] Smoke `live prepare` without launching algorithms.
- [ ] Smoke `report` against an existing standardized run or fixture.
- [ ] If Open3D/ffmpeg are installed, smoke inspector/demo; otherwise confirm clear optional-dependency errors.
- [ ] Review git diff for accidental datasets, PCD, bag, PLY, MP4, or generated run outputs.
- [ ] Complete branch only after verification evidence is recorded.