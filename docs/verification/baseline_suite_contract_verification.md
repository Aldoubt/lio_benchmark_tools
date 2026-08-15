# LIO Baseline Suite Contract Verification

Date: 2026-08-16
Branch: `feat/lio-baseline-suite`

## 1. Verification scope

This document records the distinction between:

```text
CONTRACT_VERIFIED
REAL_MACHINE_NOT_TESTED
BLOCKED_ENVIRONMENT
BLOCKED_CALIBRATION
```

A green contract CI proves registry/schema/unit/syntax behavior. It does **not** prove that every upstream ROS algorithm has successfully consumed a real bag on the current machine.

## 2. Frozen suite design

### Core families

```text
FAST-LIVO2
FAST-LIO2
Point-LIO
DLIO
LIO-SAM
GLIM
current Leg-KILO master
KISS-ICP
```

GLIM retains two backward-compatible runnable IDs:

```text
glim_odometry      -> ODOMETRY
glim_full_slam     -> SYSTEM_MAPPING
```

### Research

```text
Faster-LIO
SLICT
```

### Legacy identity

```text
leg_kilo2_lidar_imu
```

The legacy ID is not silently reinterpreted as current `ouguangjun/Leg-KILO` master.

## 3. Verified core contracts

The branch contains automated tests for:

```text
registry record identity and schema
Core / Research / Legacy tiers
algorithm family and evaluation roles
sensor profiles
current Leg-KILO vs historical Leg-KILO identity
GLIM family role separation
canonical LiDAR->IMU calibration
inverse IMU->LiDAR conversion
unconfirmed calibration fail-closed semantics
adapter preflight / prepare / collect lifecycle
ROS distro environment gating
required input modalities and capabilities
V1 manifest backward compatibility
V2 registry resolution
MID360 timestamp layout
custom Livox message handling
strict trajectory timestamp ordering
position interpolation + quaternion shortest-arc SLERP
common selected-scan manifest
Native vs Unified Map provenance
Display Alignment NONE / START_XY_YAW
Display Alignment scientific-artifact immutability
role-aware Display Alignment metadata
scoreboard grouping
missing report artifacts remaining missing rather than zero
ROI / camera preset round trips
Live Debug session / event marker contract
```

## 4. CI evidence

The GitHub Actions `Core Contracts` workflow executes:

```bash
python3 -m pip install --disable-pip-version-check numpy
python3 -m unittest benchmark_base.tests.test_registry -v
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 benchmark_base/bin/lio-benchmark list algorithms
python3 benchmark_base/bin/lio-benchmark show algorithm leg_kilo2_lidar_imu
```

A full CI run including the baseline-suite code, role-aware Display Alignment tests, Research adapter registry contracts, and updated README completed successfully on commit:

```text
551310188886a533ddf2f534ac0df9fd45682e42
```

Any later documentation-only commit must still pass the same workflow before the branch is treated as contract-green.

## 5. Two-map contract

### Native Map

Definition:

```text
an upstream algorithm's own mapping output
```

Allowed status:

```text
AVAILABLE
NOT_PROVIDED
FAILED
```

Benchmark-accumulated point clouds are never relabeled as Native Map.

### Unified Map

Definition:

```text
same frozen raw LiDAR
+ same selected_scans.csv
+ same canonical calibration
+ algorithm standardized trajectory
+ same near-range / point-sampling / voxel policy
+ same reconstruction implementation
```

Backward-compatible V2 paths remain available while new explicit native/unified directories are introduced.

## 6. Display Alignment contract

Supported modes:

```text
NONE
START_XY_YAW
```

Default cross-algorithm display mode:

```text
START_XY_YAW
```

It removes only arbitrary initial horizontal origin and initial yaw.

It preserves:

```text
initial Z
roll / pitch
subsequent drift
scale error
non-rigid map distortion
```

It never writes back to standardized trajectories, Native Maps, Unified Maps, or scientific metrics.

Display Alignment metadata is role-aware. A `glim_full_slam` compatibility trajectory is recorded as `SYSTEM_MAPPING`, not incorrectly hard-coded as `ODOMETRY`.

Inspector, Report, and Demo share the same alignment transform implementation. Comparison views use shared coordinate/color ranges rather than per-algorithm fitting.

## 7. Adapter contract status

| Algorithm ID | Tier | Adapter contract | Real-machine status represented by this verification |
|---|---|---|---|
| `fast_livo2` | CORE | present | real green-house reference smoke PASS |
| `fast_lio2` | CORE | present | REAL_MACHINE_NOT_TESTED in this verification |
| `point_lio` | CORE | present | previous green-house verification blocked by local integration environment |
| `dlio` | CORE | present | previous green-house verification blocked by local integration environment |
| `lio_sam` | CORE | present | REAL_MACHINE_NOT_TESTED in this verification |
| `glim_odometry` | CORE | present | previous green-house verification blocked by local integration environment |
| `glim_full_slam` | CORE | present | previous green-house verification blocked by local integration environment |
| `leg_kilo` | CORE | present | REAL_MACHINE_NOT_TESTED for current master adapter |
| `kiss_icp` | CORE | present | REAL_MACHINE_NOT_TESTED in this verification |
| `faster_lio` | RESEARCH | present | BLOCKED_ENVIRONMENT on ROS2 Humble by design; selected upstream is ROS1 Melodic/Noetic |
| `slict` | RESEARCH | present | BLOCKED_ENVIRONMENT on ROS2 Humble by design; selected upstream master targets ROS2 Jazzy |
| `leg_kilo2_lidar_imu` | LEGACY | retained | historical identity only |

`present` means a registry/runner contract exists and is syntax/contract checked. It does not mean the upstream algorithm has completed a real dataset run.

## 8. Verified real green-house reference

Existing real-data V2 verification used:

```text
/home/yangxuan/agt_navigation_v2/runtime/rosbag/green-house
```

FAST-LIVO2 reference result:

```text
full replay                  622.99 s
LiDAR frames                 6230
standardized trajectory      6227 samples
selected Unified Map scans   1246
matched scans                1238 / 1246
matched ratio                99.36%
Unified Map points           772,631
```

This demonstrates the real-data core chain:

```text
rosbag
-> estimator trajectory
-> timestamp standardization
-> common LiDAR association
-> Unified Map
-> Inspector / Report
```

## 9. Remaining calibration blocker

The green-house dataset has not yet frozen a physically confirmed LiDAR-IMU extrinsic value in the formal research contract.

Therefore current map comparisons from that dataset remain diagnostic evidence, not final publication ranking evidence.

Before a formal multi-algorithm comparison:

1. identify the actual calibration used during data acquisition / validated mapping
2. freeze it as canonical `LIDAR_TO_IMU`
3. record source/status as `CONFIRMED`
4. let each adapter generate its algorithm-specific convention run-locally
5. rerun affected algorithms/maps

## 10. Research adapter environment policy

### Faster-LIO

Selected upstream:

```text
gaoxiang12/faster-lio main
ROS1 Melodic / Noetic
```

For a rosbag2 dataset, the adapter requires an explicit converted ROS1 bag artifact via `BENCHMARK_ROS1_BAG_FILE`. It never performs a hidden conversion.

### SLICT

Selected upstream:

```text
brytsknguyen/slict master
Ubuntu 24.04 / ROS2 Jazzy
```

It requires an explicitly reviewed dataset-specific SLICT YAML through `BENCHMARK_SLICT_CONFIG`. It does not silently copy a public-dataset config.

## 11. Next real-machine integration sequence

Do not begin with ten full 623-second runs.

For each newly integrated algorithm, first use one representative short bag segment containing straight motion, a turn, and repetitive geometry when possible.

Recommended order:

```text
1. FAST-LIVO2 reference
2. FAST-LIO2
3. KISS-ICP
4. current Leg-KILO master
5. Point-LIO
6. DLIO
7. LIO-SAM
8. GLIM odometry
9. GLIM full SLAM
10. Faster-LIO only on a supported ROS1 environment
11. SLICT only on a supported Jazzy environment
```

Per-algorithm gate:

```text
preflight PASS
process starts
bag is consumed
trajectory exists
trajectory timestamps strictly increase
no NaN / Inf
trajectory covers intended bag interval
standard trajectory succeeds
Unified Map succeeds
matched scan ratio is reported
Native Map provenance is explicit
logs/failure evidence retained
```

Only algorithms passing the short smoke move to the complete frozen bag.

## 12. Full frozen benchmark acceptance

A formal cross-scene run should preserve, per algorithm:

```text
raw trajectory/output
standardized trajectory
Native Map status/artifact
Unified Map
runtime/resource metadata
parameters/config hash
source branch/commit/dirty state
canonical and generated calibration provenance
selected scan manifest
matched/unmatched scan counts
adapter/preflight status
logs
failure markers when relevant
Display Alignment metadata only for derived figures
```

The benchmark report must continue to separate:

```text
Common LiDAR+IMU Odometry
System Mapping
Control / Extension
```

No single global rank is scientifically meaningful across those three views.

## 13. Current verdict

```text
BASELINE SUITE CONTRACT: IMPLEMENTED / CI-VERIFIED
MULTI-ALGORITHM REAL-MACHINE INTEGRATION: INCOMPLETE
FORMAL GREEN-HOUSE RANKING: BLOCKED_CALIBRATION
```

The next work is integration smoke testing and calibration freeze, not another benchmark-core redesign.
