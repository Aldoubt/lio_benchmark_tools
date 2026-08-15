# LIO Benchmark Tools V2 Design

Date: 2026-08-15
Status: DESIGN APPROVED IN CHAT / IMPLEMENTATION NOT STARTED
Branch: `feat/lio-benchmark-v2`

## 1. Purpose

Upgrade `lio_benchmark_tools` from a small set of one-off ROS 2 LIO benchmark scripts into a reusable research toolkit with four explicitly separated workflows:

```text
lio_benchmark_tools
├─ Benchmark Mode
│  └─ reproducible offline dataset × algorithm runs
├─ Inspector Mode
│  └─ interactive 3D map and trajectory comparison
├─ Report / Demo Mode
│  └─ paper-ready figures, HTML/Markdown reports, README GIF
└─ Live Debug Mode
   └─ manually inspect replay + algorithm nodes + RViz/topic/TF behavior
```

The repository must remain independent from robot navigation/control code and must not vendor full upstream algorithm repositories or large datasets.

The V2 design serves three goals simultaneously:

1. provide a reproducible LIO/SLAM benchmark for real agricultural datasets;
2. provide a practical debugging tool for investigating algorithm failure onset;
3. make the repository suitable as a public portfolio/research showcase with clear same-bag visual comparisons.

## 2. Current repository baseline

The existing repository already provides:

- a JSON experiment manifest;
- `lio-benchmark validate/init/analyze-bag/snapshot/commands` orchestration;
- algorithm adapters for FAST-LIVO2, Point-LIO, GLIM odometry, GLIM full SLAM, and DLIO;
- trajectory analysis;
- a first `visualize_frontend_comparison.py` script that reconstructs and plots maps using common MID360 samples.

The current map-comparison script is useful exploratory tooling but is not considered a publication-grade standardizer because:

1. algorithms and output paths are hard-coded;
2. scan-to-pose association is based on normalized sample index rather than timestamp synchronization;
3. native algorithm maps and unified reconstructed maps are not represented by a common provenance contract;
4. visualization is static and does not expose reusable ROI/camera presets;
5. it is not integrated into the run-directory contract.

V2 replaces these assumptions without breaking the existing historical experiment records.

## 3. Fixed baseline algorithms

V2 defines the following fixed benchmark baselines:

```text
FAST-LIVO2
Point-LIO
Leg-KILO 2.0
GLIM Odometry
GLIM Full SLAM
DLIO
```

### 3.1 FAST-LIVO2

Primary multimodal-capable baseline and current preferred production-oriented front end.

For datasets without valid camera data, the manifest must explicitly record the effective modality set used by the run. A LiDAR-IMU-only run must not be mislabeled as a full LiDAR-IMU-visual comparison.

### 3.2 Point-LIO

Point-wise LiDAR-IMU estimator baseline.

### 3.3 Leg-KILO 2.0

Leg-KILO becomes a fixed baseline in V2.

For ordinary handheld MID360 + IMU benchmark datasets, the run contract must explicitly record:

```text
algorithm = Leg-KILO 2.0
mode = lidar_imu
leg_kinematics = disabled
```

If a future dataset contains valid leg kinematic inputs, that capability may be enabled as a separate benchmark mode. Results with and without kinematic observations must never be mixed under one label.

### 3.4 GLIM Odometry / Full SLAM

Odometry and globally optimized SLAM remain separate benchmark entries because they answer different questions and may produce different trajectories/maps.

### 3.5 DLIO

Retain the current ROS 2 adapter and patch provenance requirements. Input unit/time handling modifications remain explicit benchmark metadata rather than hidden source edits.

## 4. Architecture principle

The main architectural rule is:

```text
Dataset Registry
      +
Algorithm Registry
      ↓
Runner / Adapter
      ↓
Raw Algorithm Output
      ↓
Standardizer
      ↓
Standard Benchmark Artifacts
      ├─ Metrics
      ├─ 3D Inspector
      ├─ Paper Report
      ├─ README Demo
      └─ Live Debug references
```

Running algorithms, standardizing outputs, visualizing maps, generating paper figures, and interactively debugging ROS nodes are separate responsibilities.

No GUI or report generator may become an alternative truth owner for algorithm output.

## 5. Dataset Registry

V2 adds a registry directory:

```text
benchmark_base/registry/datasets/
```

Dataset registry files remain JSON to preserve the current standard-library-only core orchestration path.

Example:

```json
{
  "schema_version": 2,
  "dataset_id": "gaas_handheld_a",
  "bag_dir": "/absolute/local/path/to/bag",
  "sha256": "...",
  "environment": "greenhouse",
  "acquisition": {
    "platform": "handheld",
    "route_type": "historical_route_a"
  },
  "topics": {
    "lidar": "/livox/lidar",
    "imu": "/livox/imu",
    "camera": null
  },
  "types": {
    "lidar": "sensor_msgs/msg/PointCloud2",
    "imu": "sensor_msgs/msg/Imu"
  },
  "timestamp": {
    "point_time_field": "timestamp",
    "point_time_unit": "ns_absolute"
  },
  "calibration": {
    "rotation_lidar_to_imu_row_major": [1,0,0,0,1,0,0,0,1],
    "translation_lidar_to_imu_m": [0.011,0.02329,-0.04412],
    "source": "project-confirmed"
  }
}
```

Dataset registry requirements:

- bag files remain external and are never copied into the repository;
- paths may be machine-local, but the dataset ID, hash, sensor contract, calibration source, and acquisition description are version controlled;
- the original bag is immutable during benchmark runs;
- topic remapping belongs to algorithm adapters, not dataset mutation.

## 6. Algorithm Registry

V2 adds:

```text
benchmark_base/registry/algorithms/
```

One JSON record per algorithm/mode.

Each registry entry contains at minimum:

```text
algorithm_id
display_name
mode
family
required_modalities
optional_modalities
source path / repository identity
runner adapter
input topic contract
output trajectory topic
optional native map topic/path
namespace capability
known preprocessing requirements
```

The registry removes the need to hard-code algorithm lists in visualization or orchestration code.

Adding a future baseline such as FAST-LIO2, LIO-SAM, KILVO, or another paper implementation should require a registry record plus an adapter, not modifications throughout the benchmark core.

## 7. Experiment Manifest V2

The experiment manifest references datasets and algorithm registry entries instead of duplicating all algorithm definitions inline.

A V2 experiment can choose a subset of fixed baselines:

```json
{
  "schema_version": 2,
  "name": "gaas_a_fixed_baselines",
  "workspace": "/home/yangxuan/ros2_ws",
  "output_root": "/home/yangxuan/ros2_ws/runs",
  "dataset": "gaas_handheld_a",
  "algorithms": [
    "fast_livo2",
    "point_lio",
    "leg_kilo2_lidar_imu",
    "glim_odometry",
    "glim_full_slam",
    "dlio"
  ],
  "standardization": {
    "map_voxel_m": 0.12,
    "near_range_m": 0.5,
    "trajectory_time_tolerance_s": 0.05
  }
}
```

The tool must retain backward compatibility with schema version 1 long enough to preserve the current MID360 historical baseline.

## 8. Standard Benchmark Artifact contract

Every `dataset × algorithm` run is normalized into a common artifact tree:

```text
runs/<run_id>/
├─ manifest.json
├─ input/
├─ configs/
├─ raw/<algorithm>/
├─ standardized/
│  ├─ trajectories/<algorithm>.csv
│  ├─ maps/<algorithm>/
│  │  ├─ native_map.*              optional
│  │  ├─ unified_map.ply           optional
│  │  └─ map_metadata.json
│  └─ standardization_report.json
├─ metrics/
├─ figures/
├─ reports/
├─ logs/
└─ metadata/
```

### 8.1 Trajectory CSV contract

Required columns:

```text
timestamp_s
x_m
y_m
z_m
qx
qy
qz
qw
roll_rad
pitch_rad
yaw_rad
source_topic
```

All trajectories retain original timestamps.

### 8.2 Map provenance

Every map must carry:

```text
map_source = NATIVE | UNIFIED_RECONSTRUCTION
algorithm_id
dataset_id
trajectory_source
voxel_m
point_count
generation_command
generated_at
```

Native maps and unified reconstructed maps are never silently substituted for each other.

## 9. Timestamp-based standardization

This is a publication-critical V2 change.

The old exploratory method that maps scan index proportionally to trajectory index must not be used by the standardized map pipeline.

For every selected LiDAR scan with timestamp `t`, use the standardized trajectory to obtain pose `T(t)`.

Position interpolation:

```text
p(t) = linear interpolation between adjacent trajectory positions
```

Orientation interpolation:

```text
q(t) = quaternion SLERP between adjacent orientations
```

A scan outside the trajectory time range or beyond the configured tolerance fails closed and is excluded with a recorded reason.

The standardization report must contain:

```text
selected scan count
matched scan count
unmatched scan count
max interpolation gap
median interpolation gap
first/last common timestamp
```

This allows comparison of algorithms publishing odometry at different rates without index-based timing bias.

## 10. Offline Benchmark Mode

The CLI remains `lio-benchmark` and expands toward the following workflow:

```bash
lio-benchmark validate --config experiment.json
lio-benchmark init --config experiment.json
lio-benchmark snapshot --run <run>
lio-benchmark run --run <run> --algorithm fast_livo2
lio-benchmark run-all --run <run>
lio-benchmark standardize --run <run>
lio-benchmark evaluate --run <run>
lio-benchmark report --run <run>
```

Formal benchmark rules:

- algorithms run one at a time by default;
- a run freezes dataset identity, source commit, configuration, commands, environment snapshot, and patches;
- failure is preserved as benchmark evidence rather than discarded;
- reruns create new run identities unless explicitly designed as a resume of an incomplete run;
- benchmark execution never modifies upstream source repositories automatically.

## 11. Interactive 3D Inspector Mode

Use Open3D as an optional visualization dependency because the inspector is not required for headless benchmark execution.

Entry point:

```bash
lio-benchmark inspect --run <run>
```

The inspector provides:

```text
Dataset selector / active run
Algorithm visibility toggles
Native vs unified map selector
Trajectory overlay
Point size
Voxel/downsample preview
Height coloring
Intensity coloring when available
Algorithm coloring for overlay
Perspective / XY / XZ / YZ views
ROI box selection
ROI preset save/load
Camera preset save/load
Apply Camera to All
Screenshot export
```

### 11.1 Same Camera requirement

A camera state must be serializable and reusable across algorithms so visual comparison uses identical:

```text
look-at target
camera position/orientation
field of view / zoom
viewport size
ROI
```

This is required for paper figures and README demos.

### 11.2 ROI presets

A user may save named inspection regions such as:

```text
greenhouse_overview
repetitive_rows
headland_01
row_alias_case
map_doubling_case
```

ROI presets are small JSON metadata and may be version controlled when they describe publication/demo regions.

## 12. Automated Report Mode

Entry point:

```bash
lio-benchmark report --run <run>
```

The report generator consumes only standardized artifacts and metrics.

Expected outputs include:

```text
figures/trajectory_xy.png
figures/map_xy_comparison.png
figures/map_xz_comparison.png
figures/map_yz_comparison.png
figures/roi_<name>_comparison.png
figures/height_profile_comparison.png
figures/runtime_comparison.png
metrics/summary.csv
reports/report.md
reports/report.html
```

The report must distinguish:

- odometry failure;
- missing artifact;
- successful run with weak metric;
- native-map metric;
- unified-reconstruction metric.

No missing result may be silently converted into a zero score.

## 13. README Demo Generator

The repository homepage should show a same-bag animated comparison generated from benchmark artifacts.

Recommended tracked output:

```text
assets/demo/same_bag_map_comparison.gif
```

README uses a repository-relative reference:

```markdown
![Same-bag LIO map comparison](assets/demo/same_bag_map_comparison.gif)
```

The demo is generated automatically rather than recorded manually.

Entry point:

```bash
lio-benchmark demo --run <run> --preset greenhouse_overview
```

Demo requirements:

- same bag;
- same ROI;
- same camera path;
- same viewport size;
- same map display voxel/downsampling rule;
- algorithm name always visible;
- dataset/sensor identity visible;
- no per-algorithm camera adjustment;
- no manual cleanup of bad map sections.

The animation should cycle through the fixed baselines using an identical camera motion. `ffmpeg` may be used to assemble rendered PNG frames into MP4/GIF; failure to find ffmpeg must produce a clear dependency message rather than breaking offline benchmark functions.

Large demo source videos and intermediate frames remain ignored; only a curated small GIF and selected screenshots are intended for Git tracking.

## 14. Live Debug Mode

Live Debug is explicitly separate from formal benchmark execution.

Its purpose is to manually inspect when and why an algorithm begins to fail during rosbag replay.

Primary workflow:

```bash
lio-benchmark live prepare \
  --dataset gaas_handheld_a \
  --algorithms fast_livo2 point_lio leg_kilo2_lidar_imu
```

This creates a session directory:

```text
live_sessions/<session_id>/
├─ session.json
├─ commands.md
├─ env.sh
├─ 01_bag_play.sh
├─ 02_fast_livo2.sh
├─ 03_point_lio.sh
├─ 04_leg_kilo2.sh
├─ rviz/
├─ markers/
└─ logs/
```

The generated scripts are the primary mode because they let the operator open separate terminals, pause/replay bags, restart one estimator, inspect topics, and interactively alter RViz visibility.

A future convenience command may execute the generated session automatically:

```bash
lio-benchmark live run --session <session>
```

but manual session scripts remain the inspectable source of truth.

## 15. Topic and namespace adaptation

Dataset topics remain immutable.

If an algorithm expects a different topic, the adapter provides ROS remapping rather than changing the bag or editing algorithm source code.

Conceptually:

```text
Raw Bag
  ↓
Dataset topic contract
  ↓
Algorithm adapter
  ├─ topic remap
  ├─ namespace
  ├─ unit conversion when explicitly required
  └─ algorithm config
  ↓
Original algorithm node
```

When multiple algorithms are launched simultaneously for live visual comparison, outputs must be isolated under namespaces such as:

```text
/benchmark/fast_livo2/...
/benchmark/point_lio/...
/benchmark/leg_kilo2/...
```

Formal performance benchmarking still runs algorithms individually to avoid CPU/GPU contention contaminating timing and real-time behavior.

## 16. Live Debug RViz contract

The generated RViz configuration should support simultaneous visibility toggles for:

```text
input LiDAR
algorithm registered cloud/map
algorithm odometry trajectory
TF frames
selected diagnostic topics
```

Live Debug should also generate a short `commands.md` with useful inspection commands for the active session, including:

```text
ros2 topic list
ros2 topic hz <topic>
ros2 topic delay <topic>
ros2 topic echo <topic>
ros2 run tf2_ros tf2_echo <frame_a> <frame_b>
ros2 bag play ... --clock
```

The exact commands are generated from dataset/algorithm registry information rather than copied from one hard-coded MID360 setup.

## 17. Failure Event Markers

Live Debug supports operator-created failure markers.

Entry point:

```bash
lio-benchmark mark \
  --session <session> \
  --algorithm glim_odometry \
  --label repetitive_row_misregistration \
  --bag-time 84.32 \
  --note "parallel-row alias begins here"
```

Stored marker example:

```json
{
  "bag_time_s": 84.32,
  "algorithm": "glim_odometry",
  "event": "repetitive_row_misregistration",
  "note": "parallel-row alias begins here"
}
```

Initial marker labels may remain free-form, but the documentation should recommend reusable categories such as:

```text
local_map_distortion
parallel_row_misregistration
false_structural_alignment
trajectory_jump
vertical_drift
map_doubling
loop_misalignment
tracking_failure
```

Markers may later be consumed by the report generator to render failure timelines and ROI/event comparisons.

## 18. Dependency boundary

Core orchestration remains runnable with Python standard library plus ROS 2 tooling.

Existing evaluator dependencies such as NumPy/SciPy/Matplotlib remain acceptable for analysis.

New optional dependencies:

```text
Open3D  -> interactive 3D Inspector
ffmpeg  -> README demo/GIF assembly
```

The absence of optional visualization dependencies must not prevent:

```text
validate
init
snapshot
run
standardize trajectory metadata where possible
```

Dependency errors must name the missing feature and installation requirement.

## 19. Repository structure target

V2 should move toward:

```text
lio_benchmark_tools/
├─ README.md
├─ assets/
│  └─ demo/
├─ benchmark_base/
│  ├─ bin/lio-benchmark
│  ├─ config/
│  ├─ registry/
│  │  ├─ datasets/
│  │  └─ algorithms/
│  ├─ lio_benchmark/
│  │  ├─ manifest.py
│  │  ├─ registry.py
│  │  ├─ runs.py
│  │  ├─ standardize.py
│  │  ├─ report.py
│  │  ├─ demo.py
│  │  └─ live.py
│  └─ docs/
├─ evaluators/
│  ├─ adapters/
│  ├─ metrics/
│  └─ legacy exploratory scripts
├─ inspector/
│  ├─ app.py
│  ├─ data.py
│  ├─ camera.py
│  └─ roi.py
├─ tests/
├─ patches/
└─ docs/superpowers/
```

Do not perform unrelated refactoring. Existing adapters may be migrated incrementally behind stable registry interfaces.

## 20. README redesign

The repository homepage should lead with the scientific/engineering question rather than implementation details.

Recommended order:

```text
# LIO Benchmark Tools
short purpose statement
same-bag animated GIF

Why this repository exists
Benchmark pipeline
Fixed baselines
Interactive Map Inspector screenshot
Paper-ready report screenshot
Live Debug workflow
Reproducibility contract
Quick start
Algorithm adapter notes
```

The fixed baseline table should show at least:

```text
Algorithm
Estimator family
LiDAR
IMU
Vision capability
Kinematics capability
Benchmark mode
```

README claims must be limited to actually reproduced results stored in documented benchmark runs.

## 21. Backward compatibility

The historical `current_mid360.json`, previous `date/output/...` records, and existing exploratory comparison reports remain valid historical evidence.

V2 does not move or delete historical bags/results.

The current exploratory `visualize_frontend_comparison.py` may remain as legacy tooling until the standardized pipeline replaces its functionality. Documentation should clearly distinguish LEGACY/EXPLORATORY from STANDARDIZED/V2 outputs.

## 22. Safety and data integrity

The toolkit must never automatically:

```text
modify a rosbag
rewrite an upstream algorithm repository
change an upstream git branch
apply patches without explicit operator action
silently rescale IMU units
silently reinterpret point timestamps
silently substitute native maps with reconstructed maps
delete failed benchmark output
hide failed algorithms from reports
```

Every conversion/remap/preprocessing action must be visible in frozen run metadata.

## 23. Testing strategy

Most V2 correctness belongs in pure Python tests.

Required test classes:

### Registry

- valid dataset registry load;
- invalid/missing modality rejection;
- algorithm subset selection;
- Leg-KILO LiDAR-IMU mode records kinematics disabled;
- schema v1 compatibility.

### Timestamp standardization

- exact timestamp match;
- linear position interpolation;
- quaternion SLERP;
- out-of-range scan rejection;
- tolerance rejection;
- different trajectory frequencies yield equivalent common-time poses.

### Artifact provenance

- native map metadata cannot be mislabeled unified;
- unified map records generation settings;
- missing map remains unavailable rather than zero-sized success.

### Report

- successful + failed algorithms coexist in one summary;
- missing metric is rendered N/A;
- ROI/camera preset is reused consistently.

### Live Debug

- generated commands use dataset topics;
- remaps use algorithm expected topics;
- multi-algorithm namespaces do not collide;
- session generation does not execute algorithms;
- marker serialization round-trips.

### Demo

- deterministic frame ordering;
- identical camera preset applied to all algorithms;
- ffmpeg absence produces a feature-scoped dependency error.

## 24. Acceptance criteria

V2 is considered functionally complete when all of the following are true:

1. A new dataset can be registered without modifying Python source.
2. A new algorithm can be registered via one registry entry plus one adapter.
3. The six fixed baselines are represented in the registry.
4. A chosen subset of algorithms can be run against one bag using frozen run metadata.
5. Standardized trajectories retain timestamps and map reconstruction uses timestamp interpolation rather than index-proportional matching.
6. Native and unified maps are visibly distinguished by provenance.
7. `lio-benchmark inspect` can compare at least two standardized maps interactively with identical camera and ROI presets.
8. `lio-benchmark report` creates reusable comparison figures and an HTML/Markdown report from standardized artifacts.
9. `lio-benchmark demo` can create a same-bag same-camera animation suitable for README embedding.
10. `lio-benchmark live prepare` can generate a manual ROS debug session for a selected subset of algorithms without running them automatically.
11. Multi-algorithm live debug output namespaces do not collide.
12. Failure events can be recorded with bag time, algorithm, label, and note.
13. Existing schema-v1 MID360 history remains readable/documented.
14. README is upgraded to present the repository as a reproducible agricultural LIO research benchmark rather than a collection of local scripts.

## 25. Explicit non-goals for V2

V2 does not attempt to:

```text
invent a new LIO/SLAM estimator
modify algorithm mathematics
provide ground-truth ATE where no ground truth exists
rank algorithms by one visually subjective score
host rosbag/PCD/video data in Git
build a cloud benchmark service
build a browser-based 3D SaaS dashboard
replace RViz for ROS topic/TF debugging
train semantic or learning models
integrate directly into agt_navigation_v2 runtime
```

A later version may connect benchmark map-quality metrics to navigation-map derivation and P1 downstream vehicle-feasibility experiments, but that is outside this V2 implementation scope.