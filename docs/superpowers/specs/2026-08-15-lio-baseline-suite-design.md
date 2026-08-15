# LIO Benchmark Baseline Suite Design

Date: 2026-08-15
Status: DESIGN FROZEN FROM APPROVED CHAT DIRECTION
Parent design: `docs/superpowers/specs/2026-08-15-lio-benchmark-v2-design.md`
Design branch: `design/lio-baseline-suite`

## 1. Purpose

Extend LIO Benchmark Tools V2 from a six-entry experimental baseline set into a reusable cross-scene benchmark suite that can answer:

> Given one frozen sensor dataset, which odometry / LIO / SLAM front end behaves best for this environment, and why?

The repository must support repeated use across greenhouse, orchard, open-field, campus, industrial, and similar scenes without rewriting benchmark logic for each dataset.

The design keeps four V2 workflows unchanged:

```text
Benchmark
Inspector
Report / Demo
Live Debug
```

This extension adds five project-wide contracts:

1. `Core Baselines + Research Baselines` instead of targeting an arbitrary algorithm count;
2. explicit algorithm-family and evaluation-role metadata;
3. two-map output semantics: `Native Map` and `Unified Map`;
4. `Display Alignment` as a non-scientific visualization transform;
5. a richer per-algorithm artifact/provenance contract and adapter interface.

## 2. Baseline tiers

### 2.1 Core Baselines

The long-term core suite contains eight representative algorithm families.

| Canonical ID | Algorithm | Family | Main benchmark role |
|---|---|---|---|
| `fast_livo2` | FAST-LIVO2 | direct ESKF LIO / multimodal-capable | primary reference |
| `fast_lio2` | FAST-LIO2 | frame-level direct IESKF scan-to-map | classical filter baseline |
| `point_lio` | Point-LIO | point-wise ESKF | point-wise filter baseline |
| `dlio` | DLIO | direct continuous-time LIO | continuous-time baseline |
| `lio_sam` | LIO-SAM | feature / factor-graph LIO | factor-graph baseline |
| `glim` | GLIM | direct multi-scan + factor graph | modern global mapping baseline |
| `leg_kilo` | current `ouguangjun/Leg-KILO` master | two-stage ESKF + hybrid Gaussian voxel + backend | modern hybrid baseline |
| `kiss_icp` | KISS-ICP | LiDAR-only ICP odometry | LiDAR-only control |

The core suite is stable across datasets. A dataset may mark a core algorithm as `BLOCKED_INPUT`, `BLOCKED_DEPENDENCY`, or `UNSUPPORTED_PLATFORM`; the benchmark must not silently remove it from reports.

### 2.2 Research Baselines

The default research tier contains:

| Canonical ID | Algorithm | Family | Purpose |
|---|---|---|---|
| `faster_lio` | Faster-LIO | FAST-LIO2-style filter + sparse voxel map | efficiency / map-structure research |
| `slict` | SLICT | surfel-based continuous-time optimization | continuous-time optimization research |

Research baselines are optional per machine and dataset. Their absence does not make a core-suite run invalid.

### 2.3 Existing ID compatibility

Existing V2 IDs must remain readable so historical manifests do not break.

Specifically:

```text
fast_livo2
point_lio
dlio
glim_odometry
glim_full_slam
leg_kilo2_lidar_imu
```

remain valid registry records or aliases.

New canonical organization is:

```text
glim
  outputs:
    odometry
    full_slam

leg_kilo
  source branch: master
  outputs:
    frontend
    backend
```

`leg_kilo2_lidar_imu` remains a historical implementation identity and must never be silently reinterpreted as the current `master` implementation.

## 3. Algorithm families and evaluation roles

Registry records gain explicit metadata:

```text
tier = CORE | RESEARCH | LEGACY
family
sensor_profile
algorithm_generation
evaluation_roles
outputs
```

A single upstream algorithm may expose multiple evaluation outputs.

Examples:

```text
GLIM
  odometry trajectory -> ODOMETRY
  globally optimized trajectory -> SYSTEM_MAPPING

Leg-KILO master
  frontend trajectory -> ODOMETRY
  backend trajectory -> SYSTEM_MAPPING

LIO-SAM
  IMU/preintegration or front-end output -> ODOMETRY when available
  mapOptimization output -> SYSTEM_MAPPING
```

Reports must compare outputs by role instead of treating every topic as an independent algorithm.

## 4. Sensor profiles

Every algorithm run records the modalities actually used.

Allowed modality keys:

```text
lidar
imu
camera
kinematics
gnss
wheel_odometry
```

A run is identified by both algorithm and effective sensor profile.

Examples:

```text
FAST-LIVO2 + LiDAR + IMU
FAST-LIVO2 + LiDAR + IMU + Camera
Leg-KILO + LiDAR + IMU
Leg-KILO + LiDAR + IMU + Kinematics
KISS-ICP + LiDAR
```

Results with different effective sensor profiles must not be merged into one common score.

## 5. Canonical calibration contract

Dataset Registry owns one canonical LiDAR/IMU extrinsic definition:

```text
LIDAR_TO_IMU
p_imu = R_li * p_lidar + t_li
```

Dataset registry stores:

```text
rotation_lidar_to_imu_row_major
translation_lidar_to_imu_m
source
status = CONFIRMED | UNCONFIRMED
```

A formal benchmark requiring LiDAR + IMU may run with `UNCONFIRMED` calibration only as `DIAGNOSTIC_ONLY`.

Each algorithm registry declares its required convention:

```text
LIDAR_TO_IMU
IMU_TO_LIDAR
NONE
```

The benchmark core converts canonical calibration mathematically. For inverse conversion:

```text
R_il = R_li^T
t_il = -R_li^T * t_li
```

Adapters must not copy arrays unchanged when upstream convention differs.

Generated algorithm-specific calibration belongs in the frozen run directory; upstream repositories remain unmodified.

## 6. Adapter contract

Each benchmark adapter has one purpose: convert a frozen Dataset + Algorithm registry record into an inspectable execution command without modifying the dataset or upstream source tree.

### 6.1 Required adapter lifecycle

Every adapter supports these logical stages:

```text
preflight
prepare
run
collect
```

`preflight` checks:

```text
source repository path
expected commit/branch information
build/install availability
ROS distribution compatibility
required executable/package
required dataset topics/types
required point-time fields
required calibration status
required optional conversion tools
```

`prepare` creates only run-local generated configuration/remapping files.

`run` launches the upstream algorithm and bag replay using the formal benchmark rate.

`collect` records raw output locations and maps upstream outputs to declared benchmark roles.

### 6.2 Adapter execution interface

Existing shell adapters remain supported during migration.

Formal runner arguments stay:

```text
<BAG_DIR> <OUTPUT_DIR>
```

Formal environment variables include:

```text
WORKSPACE
BAG_PLAY_RATE
BENCHMARK_RUN_DIR
BENCHMARK_DATASET_ID
BENCHMARK_ALGORITHM_ID
```

Default formal benchmark replay rate is:

```text
BAG_PLAY_RATE=1.0
```

Adapters may use ROS remapping, generated YAML, or explicit message conversion. They must not:

```text
edit the bag
edit upstream source automatically
hide source patches
silently change calibration
silently change IMU units
delete failed outputs
```

### 6.3 Adapter status

Every algorithm produces an adapter status record with one of:

```text
PASS
FAIL_IMPLEMENTATION
FAIL_ALGORITHM
BLOCKED_ENVIRONMENT
BLOCKED_DEPENDENCY
BLOCKED_INPUT
BLOCKED_CALIBRATION
NOT_TESTED
```

## 7. Two-map artifact contract

Every algorithm has two logically distinct map outputs.

### 7.1 Native Map

`Native Map` is produced by the upstream algorithm's own mapping system.

It may include upstream-specific behavior such as:

```text
voxel map management
keyframes
submaps
loop closure
outlier filtering
backend optimization
map pruning
```

Native map metadata uses:

```text
map_source = NATIVE
status = AVAILABLE | NOT_PROVIDED | FAILED
source_output
source_role
point_count when measurable
coordinate_frame
```

If an algorithm does not expose a true native global map, use:

```text
status = NOT_PROVIDED
```

The benchmark must never relabel its own accumulated cloud as a native map.

### 7.2 Unified Map

`Unified Map` is generated by the benchmark from:

```text
same frozen raw LiDAR bag
same frozen selected scan timestamps
same canonical calibration
algorithm standardized trajectory
same near-range filter
same point sampling
same voxel size
same map reconstruction implementation
```

It answers:

> How geometrically consistent is the trajectory estimate under a common map reconstruction pipeline?

Unified map metadata uses:

```text
map_source = UNIFIED_RECONSTRUCTION
algorithm_id
dataset_id
trajectory_role
trajectory_source
selected_scan_manifest
matched_scan_count
unmatched_scan_count
matched_ratio
voxel_m
near_range_m
point_sampling
point_count
timestamp_sources
```

## 8. Common scan manifest

V2 currently selects scans using a deterministic scan step while reconstructing each algorithm map.

The baseline-suite extension freezes the actual selected scans once per run:

```text
standardized/map_sampling/selected_scans.csv
```

Required columns:

```text
scan_index
timestamp_s
timestamp_source
bag_record_time_s
lidar_topic
selected
```

All Unified Maps consume this same manifest.

This prevents a future algorithm-specific code path from accidentally reconstructing a different subset of the bag.

If one algorithm cannot match a selected scan, the scan remains in the manifest and is counted as unmatched for that algorithm.

## 9. Standard trajectory contract

The existing timestamp-based trajectory standardization remains mandatory.

Required common trajectory columns remain:

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

Algorithms may also preserve richer native trajectories.

Examples:

```text
Point-LIO high-rate state trajectory
GLIM odometry trajectory
GLIM globally optimized trajectory
Leg-KILO frontend trajectory
Leg-KILO backend trajectory
LIO-SAM mapOptimization trajectory
```

The common trajectory used for a scoreboard must identify its `evaluation_role`.

## 10. Display Alignment

Display Alignment is added as a first-class visualization contract.

It is explicitly not a scientific artifact transformation.

### 10.1 Default mode

Default cross-algorithm visual alignment is:

```text
START_XY_YAW
```

For each trajectory/map, compute a display-only transform using that algorithm's initial pose:

```text
x/y translation -> initial x/y becomes 0
rotation about Z -> initial yaw becomes 0
```

Do not remove:

```text
initial z
roll
pitch
subsequent drift
scale error
non-rigid distortion
```

This preserves visible vertical drift and attitude errors while removing arbitrary horizontal start-frame choice.

### 10.2 Supported modes

Initial supported modes are only:

```text
NONE
START_XY_YAW
```

No ICP, Umeyama, trajectory registration, or full SE(3) best-fit alignment is allowed in the default benchmark display path because such methods can hide estimator errors.

Future research alignment tools may be added only under a clearly separate diagnostic label.

### 10.3 Storage

Display alignment is stored separately:

```text
figures/display_alignment/<algorithm>.json
```

Required fields:

```text
schema_version
mode
algorithm_id
trajectory_role
source_initial_pose
transform_matrix_4x4
generated_at
```

The following files must never be modified by display alignment:

```text
raw output
standardized trajectory
native map
unified map
map metadata
scientific metrics
```

### 10.4 Inspector / report / demo labeling

Inspector, report, screenshots, and README GIF must expose alignment status.

Examples:

```text
Display alignment: NONE
Display alignment: START_XY_YAW
```

Publication figures generated with alignment must record the alignment mode in figure metadata/caption support.

## 11. Artifact layout

The existing V2 top-level run layout remains compatible.

It is extended rather than replaced:

```text
runs/<run_id>/
├─ manifest.json
├─ input/
├─ configs/
│  └─ generated/<algorithm>/
├─ raw/<algorithm>/
├─ standardized/
│  ├─ trajectories/
│  │  ├─ <algorithm>__<role>.csv
│  │  └─ native/<algorithm>/
│  ├─ map_sampling/
│  │  └─ selected_scans.csv
│  ├─ maps/<algorithm>/
│  │  ├─ native/
│  │  │  ├─ map.*
│  │  │  └─ metadata.json
│  │  └─ unified/
│  │     ├─ map.ply
│  │     └─ metadata.json
│  └─ standardization_report.json
├─ metrics/
│  ├─ algorithms/<algorithm>/trajectory.json
│  ├─ algorithms/<algorithm>/maps.json
│  ├─ algorithms/<algorithm>/runtime.json
│  ├─ algorithms/<algorithm>/resources.csv
│  └─ summary.csv
├─ figures/
│  ├─ display_alignment/
│  ├─ comparisons/
│  └─ roi/
├─ reports/
├─ logs/
└─ metadata/
   ├─ environment_snapshot.json
   └─ algorithms/<algorithm>/provenance.json
```

Large maps remain outside Git according to existing repository policy.

## 12. Per-algorithm provenance

Each algorithm run must freeze:

```text
algorithm_id
display_name
tier
family
source repository
source branch
source commit
source dirty status when known
algorithm generation/version label
ROS distribution
build/install path
compiler/build type when available
effective sensor modalities
dataset_id
dataset hash when available
canonical calibration source
canonical calibration status
algorithm extrinsic convention
generated algorithm calibration
parameter source
parameter SHA-256
adapter path
adapter repository commit
bag replay rate
launch/run command
```

Unknown values are represented as `UNKNOWN`, not guessed.

## 13. Algorithm-specific retained outputs

Common standardization must not discard useful upstream diagnostics.

### 13.1 FAST-LIVO2

Retain when available:

```text
native odometry
registered cloud
native map / voxel-map export
effective-point diagnostics
visual tracking diagnostics when camera mode is active
```

### 13.2 FAST-LIO2

Retain when available:

```text
native odometry
cloud_registered
effective points
native PCD export
```

### 13.3 Point-LIO

Retain:

```text
high-rate native state trajectory
scan-rate standardized trajectory
registered cloud/native map when available
```

### 13.4 DLIO

Retain:

```text
native odometry
native map
deskew/motion-compensation diagnostics when exposed
```

### 13.5 LIO-SAM

Retain when available:

```text
front-end / preintegration trajectory
mapOptimization trajectory
keyframe poses
loop events
native map
GPS factor diagnostics when enabled
```

### 13.6 GLIM

Retain separately:

```text
odometry trajectory
globally optimized trajectory
submaps/dump references
native exported map
backend/loop information when available
```

### 13.7 Leg-KILO current master

The canonical core adapter targets current `ouguangjun/Leg-KILO` `master`, not the historical `legkilo-v2` branch.

Retain when available:

```text
frontend trajectory
backend trajectory
native global map
native tiled-map reference
loop candidates / verified loops when exposed
viewer/export logs
```

Custom datasets use the upstream LIO sensor mode when no kinematics are present.

The adapter records the upstream-required extrinsic convention and converts from benchmark canonical calibration.

### 13.8 KISS-ICP

Retain:

```text
native LiDAR odometry trajectory
upstream diagnostics when available
```

Native global map may legitimately be `NOT_PROVIDED`.

Unified Map remains available from the standardized trajectory.

### 13.9 Faster-LIO / SLICT

Retain the same common artifacts plus upstream diagnostics that can be collected without source modification.

## 14. Scoreboards

Reports produce separate benchmark views rather than one global rank.

### 14.1 Common LiDAR + IMU Odometry

Includes compatible `ODOMETRY` outputs using the common LiDAR + IMU sensor profile.

Typical entries:

```text
FAST-LIVO2 in LiDAR+IMU mode
FAST-LIO2
Point-LIO
DLIO
GLIM odometry
Leg-KILO frontend
Faster-LIO when enabled
```

LIO-SAM may be included only when the selected output is explicitly classified as an odometry-role output.

### 14.2 System Mapping

Compares full mapping systems and Native Maps.

Typical entries:

```text
LIO-SAM mapOptimization
GLIM full SLAM
Leg-KILO backend
other algorithms with an explicit global mapping/backend output
```

### 14.3 Control / Extension

Contains intentionally non-equivalent sensor or system configurations:

```text
KISS-ICP LiDAR-only
FAST-LIVO2 LiDAR+IMU+Vision
future LiDAR+IMU+kinematics Leg-KILO
```

These results remain useful but must not be ranked as if they were identical-input Common LIO runs.

## 15. Inspector changes

`lio-benchmark inspect` gains explicit controls for:

```text
algorithm
trajectory role
Native vs Unified Map
Display Alignment: NONE / START_XY_YAW
shared camera
shared ROI
shared height color range
```

Same-camera behavior remains mandatory.

Changing Display Alignment updates only visualization geometry in memory.

## 16. Report and README demo changes

Report and demo generators must consume the same:

```text
ROI preset
camera preset
display alignment mode
height/intensity color range
map kind
trajectory role
```

A comparison figure/GIF must not independently fit each algorithm to its own viewport.

README demo defaults to:

```text
map kind: UNIFIED
alignment: START_XY_YAW
shared camera path
shared ROI
shared height range
```

The rendered overlay includes dataset identity, algorithm identity, sensor profile, map kind, and alignment mode.

## 17. Preflight and portability

Before a full benchmark, the suite supports an environment audit for all selected algorithms.

The audit records:

```text
registry valid
source located
build/install located
ROS compatibility
required topic/type compatibility
calibration requirement satisfied
adapter executable/syntax valid
launch discoverable
status
reason
```

This allows one machine to run a subset without pretending the remaining core baselines passed.

## 18. Testing strategy

Core tests remain runnable without ROS algorithm repositories.

Required unit/contract coverage includes:

```text
registry family/tier validation
legacy ID compatibility
canonical extrinsic inversion
adapter preflight status semantics
Native Map AVAILABLE/NOT_PROVIDED/FAILED semantics
common selected-scan manifest determinism
Unified Map consumes common scan manifest
multiple trajectory-role naming
Display Alignment NONE identity
Display Alignment START_XY_YAW removes only x/y/yaw
Display Alignment preserves z/roll/pitch information
Display Alignment never overwrites scientific artifacts
scoreboard role/sensor-profile filtering
report preserves missing/blocked states
```

CI continues to run:

```text
Python unit tests
compileall
shell adapter bash -n
registry smoke
```

ROS/Open3D/upstream-algorithm execution remains real-machine integration testing.

## 19. Adapter implementation order

Implementation order is intentionally incremental:

```text
1. core registry/schema + provenance extensions
2. calibration conversion module
3. common scan manifest
4. two-map artifact metadata
5. Display Alignment module
6. Inspector / Report / Demo integration
7. adapter preflight framework
8. FAST-LIO2 adapter
9. KISS-ICP adapter
10. current master Leg-KILO adapter
11. LIO-SAM adapter
12. GLIM canonical family/role migration
13. Faster-LIO research adapter
14. SLICT research adapter
15. documentation / scoreboard / end-to-end smoke
```

Existing working FAST-LIVO2, Point-LIO, DLIO, and GLIM adapters are migrated to the richer contract without unnecessary rewrites.

## 20. Non-goals

This extension does not:

```text
vendor upstream repositories
install every upstream algorithm automatically
modify upstream algorithms to expose unavailable internal metrics
provide a single misleading global score
perform automatic ICP/SE3 alignment before scientific metrics
store large bags/maps in Git
train learned navigation models
change navigation/runtime code in agt_navigation_v2
```

## 21. Acceptance criteria

The baseline-suite extension is complete when:

1. Core/Research/Legacy tiers and algorithm families validate through Registry;
2. all eight Core Baselines have registry records and inspectable adapters or explicit environment blockers;
3. both Research Baselines have registry records and adapters with platform requirements recorded;
4. current `ouguangjun/Leg-KILO` master is represented separately from historical Leg-KILO 2.0;
5. a dataset has one canonical calibration with adapter-side convention conversion;
6. Unified Maps consume one frozen selected-scan manifest per run;
7. Native and Unified maps have separate metadata and cannot be silently substituted;
8. Display Alignment supports `NONE` and `START_XY_YAW` and never modifies scientific artifacts;
9. Inspector, Report, and Demo use the same alignment/camera/ROI/map-kind semantics;
10. reports generate separate Common LIO, System Mapping, and Control/Extension views;
11. preflight can audit selected algorithms before a full bag run;
12. CI passes unit contracts, Python compilation, shell syntax, and registry smoke;
13. at least one real MID360 bag completes the extended path for two or more algorithms before merging to `main`.

## 22. Integration note for the current local verification branch

At design time, GitHub `feat/lio-benchmark-v2` points to remote commit:

```text
582e8fc21a6d4c8ead5f5c01830d77cf6b9efe67
```

The user's local machine also contains later verification commits reported as:

```text
3807a03 fix: support green-house custom rosbag contract
33e32b3 docs: record green-house v2 verification
```

Those commits are not present on GitHub at the time this design is written.

Implementation of this design must start from a branch that contains those local verification fixes (or equivalent rebased/cherry-picked changes). Do not implement the baseline-suite code on top of the older remote commit and then overwrite the verified local work.
