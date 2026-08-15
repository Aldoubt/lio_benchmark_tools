# LIO Benchmark Baseline Suite Design

Date: 2026-08-15
Status: DESIGN FROZEN FROM APPROVED CHAT DIRECTION
Parent design: `docs/superpowers/specs/2026-08-15-lio-benchmark-v2-design.md`
Design branch: `design/lio-baseline-suite`

## 1. Purpose

Extend LIO Benchmark Tools V2 from a six-entry experimental baseline set into a reusable cross-scene benchmark suite that can answer:

> Given one frozen sensor dataset, which odometry / LIO / SLAM front end behaves best for this environment, and why?

The repository must support repeated use across greenhouse, orchard, open-field, campus, industrial, and similar scenes without rewriting benchmark logic for each dataset.

The four V2 workflows remain unchanged:

```text
Benchmark
Inspector
Report / Demo
Live Debug
```

This extension adds five project-wide contracts:

1. `Core Baselines + Research Baselines` instead of targeting an arbitrary algorithm count;
2. explicit algorithm-family, sensor-profile, and evaluation-role metadata;
3. two-map output semantics: `Native Map` and `Unified Map`;
4. `Display Alignment` as a display-only transform;
5. a richer per-algorithm artifact/provenance contract and adapter interface.

## 2. Baseline tiers

### 2.1 Core algorithm families

The long-term core suite contains eight representative algorithm families.

| Family ID | Algorithm | Family | Main role |
|---|---|---|---|
| `fast_livo2` | FAST-LIVO2 | direct ESKF LIO / multimodal-capable | primary reference |
| `fast_lio2` | FAST-LIO2 | frame-level direct IESKF scan-to-map | classical filter baseline |
| `point_lio` | Point-LIO | point-wise ESKF | point-wise filter baseline |
| `dlio` | DLIO | direct continuous-time LIO | continuous-time baseline |
| `lio_sam` | LIO-SAM | feature / factor-graph LIO | factor-graph baseline |
| `glim` | GLIM | direct multi-scan + factor graph | modern global mapping baseline |
| `leg_kilo` | current `ouguangjun/Leg-KILO` master | two-stage ESKF + hybrid Gaussian voxel + backend | modern hybrid baseline |
| `kiss_icp` | KISS-ICP | LiDAR-only ICP odometry | LiDAR-only control |

GLIM remains two runnable V2 records because its odometry and global-SLAM modes answer different questions:

```text
glim_odometry      family_id=glim, evaluation_role=ODOMETRY
glim_full_slam     family_id=glim, evaluation_role=SYSTEM_MAPPING
```

The core suite is stable across datasets. A core algorithm may be reported as `BLOCKED_INPUT`, `BLOCKED_DEPENDENCY`, `BLOCKED_ENVIRONMENT`, or `BLOCKED_CALIBRATION`; it must not silently disappear from reports.

### 2.2 Research Baselines

The default research tier contains:

| Runnable ID | Algorithm | Family | Purpose |
|---|---|---|---|
| `faster_lio` | Faster-LIO | FAST-LIO2-style filter + sparse voxel map | efficiency / map-structure research |
| `slict` | SLICT | surfel-based continuous-time optimization | continuous-time optimization research |

Research baselines are optional per machine and dataset. Their absence does not invalidate a core-suite run.

### 2.3 Existing ID compatibility

Existing V2 IDs remain readable so historical manifests do not break:

```text
fast_livo2
point_lio
dlio
glim_odometry
glim_full_slam
leg_kilo2_lidar_imu
```

`leg_kilo2_lidar_imu` remains a historical implementation identity and must never be silently reinterpreted as the current `ouguangjun/Leg-KILO` `master` implementation.

The new current-master entry is:

```text
leg_kilo
```

with:

```text
family_id=leg_kilo
algorithm_generation=current_master_kilo_map_merged
source_branch=master
```

## 3. Algorithm family, output role, and sensor profile

Registry records gain:

```text
tier = CORE | RESEARCH | LEGACY
family_id
family
effective_sensor_profile
algorithm_generation
outputs
```

Every declared output has an evaluation role:

```text
ODOMETRY
SYSTEM_MAPPING
CONTROL
DIAGNOSTIC
```

A single upstream algorithm may expose multiple outputs.

Examples:

```text
GLIM
  odometry trajectory -> ODOMETRY
  globally optimized trajectory -> SYSTEM_MAPPING

Leg-KILO master
  frontend trajectory -> ODOMETRY
  backend trajectory -> SYSTEM_MAPPING

LIO-SAM
  front-end/preintegration trajectory -> ODOMETRY when exposed and semantically valid
  mapOptimization trajectory -> SYSTEM_MAPPING
```

Reports compare outputs by role rather than pretending every output topic is an independent algorithm.

Allowed sensor-profile keys are:

```text
lidar
imu
camera
kinematics
gnss
wheel_odometry
```

Results with different effective sensor profiles must not be merged into one common score.

Examples:

```text
FAST-LIVO2 + LiDAR + IMU
FAST-LIVO2 + LiDAR + IMU + Camera
Leg-KILO + LiDAR + IMU
Leg-KILO + LiDAR + IMU + Kinematics
KISS-ICP + LiDAR
```

## 4. Canonical calibration contract

Dataset Registry owns one canonical LiDAR/IMU extrinsic:

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

A LiDAR+IMU benchmark with `UNCONFIRMED` calibration may run only as:

```text
DIAGNOSTIC_ONLY
```

Each algorithm registry declares the upstream convention it needs:

```text
LIDAR_TO_IMU
IMU_TO_LIDAR
NONE
```

For inversion:

```text
R_il = R_li^T
t_il = -R_li^T * t_li
```

The benchmark core performs this conversion. Generated algorithm-specific calibration is written under the frozen run; adapters do not copy the same array when the upstream convention differs and do not modify upstream repositories.

## 5. Adapter contract

Each adapter converts a frozen Dataset + Algorithm registry record into an inspectable execution path without modifying the dataset or upstream source tree.

### 5.1 Lifecycle

Every adapter supports the logical stages:

```text
preflight
prepare
run
collect
```

`preflight` checks:

```text
source repository path
source branch/commit visibility
build/install availability
ROS distribution compatibility
required executable/package
required dataset topics/types
required point-time fields
required calibration status
required optional conversion tools
```

`prepare` creates only run-local generated configuration/remapping files.

`run` launches the upstream algorithm and bag replay using the formal benchmark replay rate.

`collect` records raw output locations and maps upstream outputs to declared benchmark roles.

### 5.2 Execution interface

Existing shell adapters remain supported during migration.

Formal runner arguments remain:

```text
<BAG_DIR> <OUTPUT_DIR>
```

Formal environment variables are:

```text
WORKSPACE
BAG_PLAY_RATE
BENCHMARK_RUN_DIR
BENCHMARK_DATASET_ID
BENCHMARK_ALGORITHM_ID
```

Formal benchmark default:

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

### 5.3 Status

Every adapter/run produces one status:

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

## 6. Two-map artifact contract

Every algorithm has two logically distinct map outputs.

### 6.1 Native Map

`Native Map` is produced by the upstream algorithm's own mapping system and may include its own voxel management, keyframes, submaps, loop closure, filtering, backend optimization, and pruning.

Native-map metadata contains:

```text
map_source = NATIVE
status = AVAILABLE | NOT_PROVIDED | FAILED
source_output
source_role
point_count when measurable
coordinate_frame
```

If an algorithm does not expose a true native global map:

```text
status = NOT_PROVIDED
```

The benchmark must never relabel its own accumulated cloud as a native map.

### 6.2 Unified Map

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

Unified-map metadata contains:

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

## 7. Common selected-scan manifest

The run freezes the actual map-reconstruction scan set once:

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

If one algorithm cannot match a selected scan, that scan remains selected globally and is counted as unmatched only for that algorithm.

## 8. Standard trajectory contract and compatibility

The existing timestamp-based trajectory standardization remains mandatory.

Required common columns remain:

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

Multi-output algorithms use role-qualified files:

```text
<algorithm>__<role>.csv
```

For backward compatibility, when an algorithm has one canonical V2 trajectory, the existing path remains readable:

```text
standardized/trajectories/<algorithm>.csv
```

That file is the compatibility alias/copy for the registry-declared default trajectory role. It must not silently switch roles between runs.

Algorithms may preserve richer native trajectories under raw output without forcing them into the common CSV schema.

## 9. Display Alignment

Display Alignment is a first-class visualization contract and is explicitly not a scientific artifact transformation.

### 9.1 Modes

Initial supported modes are only:

```text
NONE
START_XY_YAW
```

Default cross-algorithm display mode is:

```text
START_XY_YAW
```

For each algorithm/output role, the display transform removes only:

```text
initial x translation
initial y translation
initial yaw
```

The transform leaves unchanged:

```text
z coordinates
roll/pitch geometry
subsequent translational drift
subsequent yaw drift
scale error
non-rigid map distortion
```

No ICP, Umeyama, trajectory registration, or full-SE(3) best-fit alignment is allowed in the default benchmark display path because those operations can hide estimator errors.

### 9.2 Storage

Display transforms are stored separately:

```text
figures/display_alignment/<algorithm>__<role>.json
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

Display Alignment must never modify:

```text
raw output
standardized trajectory
native map
unified map
map metadata
scientific metrics
```

### 9.3 Labeling

Inspector, report, screenshots, and README GIF expose the active mode:

```text
Display alignment: NONE
Display alignment: START_XY_YAW
```

Publication figures generated with alignment record the mode in figure metadata/caption support.

## 10. Backward-compatible artifact layout

The existing V2 run layout is extended, not replaced.

```text
runs/<run_id>/
├─ manifest.json
├─ input/
├─ configs/
│  └─ generated/<algorithm>/
├─ raw/<algorithm>/
├─ standardized/
│  ├─ trajectories/
│  │  ├─ <algorithm>.csv                    # existing default-role compatibility path
│  │  ├─ <algorithm>__<role>.csv            # explicit role-qualified trajectory
│  │  └─ native/<algorithm>/                # optional upstream trajectory exports
│  ├─ map_sampling/
│  │  └─ selected_scans.csv
│  ├─ maps/<algorithm>/
│  │  ├─ unified_map.ply                    # existing V2 path retained
│  │  ├─ map_metadata.json                  # existing V2 unified metadata path retained
│  │  ├─ unified_map_metadata.json          # explicit equivalent metadata
│  │  ├─ native_map.*                       # optional, true upstream map only
│  │  └─ native_map_metadata.json
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

`map_metadata.json` remains the compatibility metadata for `unified_map.ply`; `unified_map_metadata.json` contains the same canonical unified-map record for explicit two-map consumers.

Large bags/maps remain excluded from Git under repository policy.

## 11. Per-algorithm provenance

Each algorithm run freezes:

```text
algorithm_id
display_name
tier
family_id
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

## 12. Algorithm-specific retained outputs

Common standardization must not discard useful upstream diagnostics.

### 12.1 FAST-LIVO2

Retain when available:

```text
native odometry
registered cloud
native map / voxel-map export
effective-point diagnostics
visual tracking diagnostics when camera mode is active
```

### 12.2 FAST-LIO2

Retain when available:

```text
native odometry
cloud_registered
effective points
native PCD export
```

### 12.3 Point-LIO

Retain:

```text
high-rate native state trajectory
scan-rate standardized trajectory
registered cloud/native map when available
```

### 12.4 DLIO

Retain:

```text
native odometry
native map
deskew/motion-compensation diagnostics when exposed
```

### 12.5 LIO-SAM

Retain when available:

```text
front-end/preintegration trajectory
mapOptimization trajectory
keyframe poses
loop events
native map
GPS factor diagnostics when enabled
```

### 12.6 GLIM

Retain separately:

```text
odometry trajectory
globally optimized trajectory
submaps/dump references
native exported map
backend/loop information when available
```

### 12.7 Leg-KILO current master

The canonical core adapter targets current `ouguangjun/Leg-KILO` `master`, not `legkilo-v2`.

Retain when available:

```text
frontend trajectory
backend trajectory
native global map
native tiled-map reference
loop candidates / verified loops when exposed
viewer/export logs
```

For ordinary LiDAR+IMU datasets, the adapter uses the upstream LIO sensor mode without pretending kinematic observations were present.

The upstream implementation's required extrinsic convention is declared in Registry and generated from benchmark canonical calibration.

### 12.8 KISS-ICP

Retain:

```text
native LiDAR odometry trajectory
upstream diagnostics when available
```

Its native global map may legitimately be `NOT_PROVIDED`; Unified Map remains available from its standardized trajectory.

### 12.9 Faster-LIO / SLICT

Retain common artifacts plus upstream diagnostics that can be collected without source modification.

## 13. Scoreboards

Reports produce separate benchmark views rather than one global rank.

### 13.1 Common LiDAR + IMU Odometry

Includes compatible `ODOMETRY` outputs with effective sensor profile exactly containing LiDAR + IMU and no additional active localization modality.

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

LIO-SAM enters this scoreboard only if the selected output is explicitly classified as an odometry-role output.

### 13.2 System Mapping

Compares full mapping-system outputs and Native Maps.

Typical entries:

```text
LIO-SAM mapOptimization
GLIM full SLAM
Leg-KILO backend
other algorithms with explicit global mapping/backend output
```

### 13.3 Control / Extension

Contains intentionally non-equivalent input/system configurations:

```text
KISS-ICP LiDAR-only
FAST-LIVO2 LiDAR+IMU+Vision
future Leg-KILO LiDAR+IMU+kinematics
```

These results remain visible but are not ranked as identical-input Common LIO runs.

## 14. Inspector changes

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

Changing Display Alignment transforms only in-memory display geometry.

## 15. Report and README demo changes

Report and demo generators consume the same:

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

## 16. Preflight and portability

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

## 17. Testing strategy

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
default-role trajectory compatibility path
Display Alignment NONE identity
Display Alignment START_XY_YAW removes only x/y/yaw
Display Alignment preserves z and does not rotate away roll/pitch geometry
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

## 18. Adapter implementation order

Implementation order is incremental:

```text
1. core registry/schema + provenance extensions
2. calibration conversion module
3. common selected-scan manifest
4. two-map artifact metadata while preserving V2 paths
5. Display Alignment module
6. Inspector / Report / Demo integration
7. adapter preflight framework
8. FAST-LIO2 adapter
9. KISS-ICP adapter
10. current-master Leg-KILO adapter
11. LIO-SAM adapter
12. GLIM family/role metadata migration without breaking existing IDs
13. Faster-LIO research adapter
14. SLICT research adapter
15. documentation / scoreboards / end-to-end smoke
```

Existing working FAST-LIVO2, Point-LIO, DLIO, and GLIM adapters are migrated to the richer contract without unnecessary rewrites.

## 19. Non-goals

This extension does not:

```text
vendor upstream repositories
install every upstream algorithm automatically
modify upstream algorithms to expose unavailable internal metrics
provide one misleading global score
perform automatic ICP/SE3 best-fit alignment before scientific metrics
store large bags/maps in Git
train learned navigation models
change navigation/runtime code in agt_navigation_v2
```

## 20. Acceptance criteria

The extension is complete when:

1. Core/Research/Legacy tiers and algorithm families validate through Registry;
2. all eight Core algorithm families have registry records and inspectable adapters or explicit environment blockers;
3. both Research Baselines have registry records and adapters with platform requirements recorded;
4. current `ouguangjun/Leg-KILO` master is represented separately from historical Leg-KILO 2.0;
5. a dataset has one canonical calibration with adapter-side convention conversion;
6. Unified Maps consume one frozen selected-scan manifest per run;
7. Native and Unified maps have separate metadata and cannot be silently substituted;
8. existing V2 `unified_map.ply`, `map_metadata.json`, and default trajectory paths remain readable;
9. Display Alignment supports `NONE` and `START_XY_YAW` and never modifies scientific artifacts;
10. Inspector, Report, and Demo use the same alignment/camera/ROI/map-kind semantics;
11. reports generate separate Common LIO, System Mapping, and Control/Extension views;
12. preflight can audit selected algorithms before a full bag run;
13. CI passes unit contracts, Python compilation, shell syntax, and registry smoke;
14. at least one real MID360 bag completes the extended path for two or more algorithms before merging to `main`.

## 21. Integration note for the current local verification work

At design time, GitHub `feat/lio-benchmark-v2` points to:

```text
582e8fc21a6d4c8ead5f5c01830d77cf6b9efe67
```

The user's local machine also contains later verification commits reported as:

```text
3807a03 fix: support green-house custom rosbag contract
33e32b3 docs: record green-house v2 verification
```

Those commits are not present on GitHub at the time this design is written.

Implementation must start from a branch that contains those local verification fixes, or equivalent rebased/cherry-picked changes. Do not implement baseline-suite code on top of the older remote commit and then overwrite the verified local work.
