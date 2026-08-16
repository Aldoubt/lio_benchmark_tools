# Green-house Trajectory Semantics Follow-up

## 1. Scope

This note follows the real three-algorithm smoke run:

```text
/home/yangxuan/lio_benchmark_runs/green_house/green_house_three_smoke_004
```

The dataset is a handheld MID360 recording and the sensor had a non-level initial attitude. Therefore a physically meaningful gravity-aligned estimator is expected to preserve a non-zero initial roll/pitch rather than necessarily starting at identity.

No result in this note is an accuracy ranking. Ground truth is absent and the LiDAR-IMU calibration is still diagnostic/unverified.

## 2. Raw frame audit evidence

| Algorithm | Parent frame | Child frame | Initial pitch | Raw -> standardized first-pose delta |
|---|---|---|---:|---:|
| FAST-LIVO2 | `camera_init` | `aft_mapped` | about 0.671 rad | 0 |
| FAST-LIO2 | `odom` | `sensor` | about 0.0097 rad | 0 |
| KISS-ICP | `odom_lidar` | `livox_frame` | 0 rad | 0 |

The standardizer did not create the initial attitude difference. The difference already exists in the raw Odometry messages.

## 3. Source-backed trajectory semantics

### FAST-LIVO2

For the current benchmark launch/configuration:

```text
tracked physical frame = IMU_BODY
world gauge            = GRAVITY_ALIGNED
runtime labels         = camera_init -> aft_mapped
```

The current `agt_mapping` configuration enables `uav.gravity_align_en: true`. FAST-LIVO2 estimates gravity during IMU initialization and applies its gravity-alignment step. A handheld non-level start therefore appears as a non-zero initial attitude in the gravity-aligned world frame.

### FAST-LIO2

The declared ROS2 execution implementation (`Franklif1/Fast_LIO2_ROS2`, branch `ros2`) indicates:

```text
tracked physical frame = IMU_BODY
world gauge            = INITIAL_BODY_ALIGNED
source labels          = camera_init -> body
```

However, the real smoke output was:

```text
odom -> sensor
```

This is a runtime provenance/frame-contract mismatch until the exact local package source and commit are identified. Do not silently reinterpret `sensor` as `body`.

### KISS-ICP

With the benchmark's default KISS-ICP ROS2 settings:

```text
tracked physical frame = LIDAR
world gauge            = INITIAL_LIDAR_ALIGNED
runtime labels         = odom_lidar -> <input LiDAR frame>
```

For the green-house bag the input cloud frame is `livox_frame`. KISS-ICP is LiDAR-only and has no gravity observation, so an identity initial pose does not mean the physical handheld sensor was level.

## 4. Why the previous Z plots are not yet Z-error plots

The three trajectories do not share the same native world gauge:

```text
FAST-LIVO2  gravity-aligned world
FAST-LIO2   initial-body-aligned world (declared implementation)
KISS-ICP    initial-LiDAR-aligned world
```

Therefore direct raw comparisons of Z / roll / pitch mix estimator behavior with coordinate-gauge differences. Keep the term `disagreement`; do not promote the approximately 1.4 m Z separation to an accuracy/drift verdict yet.

## 5. Unified Map tracked-frame correction

The previous Unified Map implementation always performed:

```text
LiDAR scan
  -> canonical LiDAR-to-IMU extrinsic
  -> trajectory pose
  -> world
```

That is appropriate when the trajectory tracks `IMU_BODY`, but it is incorrect for a LiDAR-tracked trajectory such as KISS-ICP.

The updated reconstruction is now:

```text
tracked_frame = IMU_BODY
  LiDAR -> IMU -> trajectory pose -> world

tracked_frame = LIDAR
  LiDAR -> trajectory pose -> world
```

Unknown/unsupported tracked-frame semantics fail closed instead of guessing.

Consequently the KISS-ICP Unified Map from the original smoke should be regenerated. The previous map is retained only as historical diagnostic evidence.

## 6. Runtime provenance gate

The benchmark now exposes:

```bash
benchmark_base/bin/lio-benchmark audit runtime-provenance \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp
```

It combines:

```text
current source-backed registry contract
+ run-local trajectory frame audit
+ ROS package prefix
+ local source git remote / commit / branch / dirty state
```

and emits:

```text
metadata/runtime_provenance/<algorithm>.json
metrics/runtime_provenance.csv
```

Possible states include:

```text
MATCH
SOURCE_MISMATCH
FRAME_CONTRACT_MISMATCH
UNRESOLVED
```

FAST-LIVO2 deliberately remains `UNRESOLVED` if the exact local ROS2 execution repository cannot be proven. The official upstream algorithm repository is not silently substituted for an unknown runtime port.

## 7. Re-audit the existing smoke without rerunning estimators

```bash
cd /home/yangxuan/lio_benchmark_tools
git checkout feat/lio-baseline-suite
git pull --ff-only

RUN=/home/yangxuan/lio_benchmark_runs/green_house/green_house_three_smoke_004

benchmark_base/bin/lio-benchmark audit trajectory-frames \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp

benchmark_base/bin/lio-benchmark audit runtime-provenance \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp
```

For a 15 s smoke, rebuild the Common Scan Manifest for the actual replay window before regenerating maps:

```bash
benchmark_base/bin/lio-benchmark standardize scan-manifest \
  --run "$RUN" \
  --start-offset-s 0 \
  --duration-s 15 \
  --overwrite
```

Then regenerate Unified Maps with tracked-frame-aware reconstruction:

```bash
for ALG in fast_livo2 fast_lio2 kiss_icp; do
  benchmark_base/bin/lio-benchmark standardize map \
    --run "$RUN" \
    --algorithm "$ALG"
done
```

Finally regenerate the diagnostic report when visual review is needed:

```bash
benchmark_base/bin/lio-benchmark report \
  --run "$RUN" \
  --display-alignment START_XY_YAW \
  --warmup-s 0
```

## 8. Package one diagnostic bundle for review

After the audit/standardization steps, package the small evidence required for review into one archive:

```bash
benchmark_base/bin/lio-benchmark bundle --run "$RUN"
```

Default output:

```text
$RUN/reports/bundles/green_house_three_smoke_004_diagnostic_bundle.tar.gz
```

The default bundle includes the frozen manifest, audit CSV/JSON files, scan-manifest metadata, per-algorithm Unified Map metadata, and archive-local Git HEAD/status/diff evidence. It deliberately excludes `raw/`, rosbag databases, `.ply`/`.pcd` maps, report files, and PNG figures.

When report HTML/Markdown and diagnostic PNGs are also needed:

```bash
benchmark_base/bin/lio-benchmark bundle \
  --run "$RUN" \
  --include-reports
```

Bundling does not rerun algorithms, standardization, or reporting. It does not modify existing run artifacts or local source changes; the only filesystem output is the requested `.tar.gz` archive.

## 9. Gate before relative-SE3 or gravity-normalized comparison

Do not add a full `START_SE3` alignment yet.

First require:

```text
1. tracked physical frame is known
2. runtime provenance is MATCH (or explicitly diagnostic-only)
3. canonical LiDAR-IMU calibration direction/value is frozen
4. map reconstruction uses the correct tracked frame
```

After those gates, the benchmark can add two explicitly different derived views:

```text
A. relative-motion view
   common physical tracked frame + remove arbitrary initial SE(3) gauge

B. gravity-aware vertical/attitude view
   common physical tracked frame + independently defined gravity-aligned evaluation frame
```

The two views must remain separate. The relative-motion view must not be used to claim gravity/height accuracy, and the gravity-aware view must not silently inject IMU information into a LiDAR-only estimator without recording that it is evaluation-frame normalization only.
