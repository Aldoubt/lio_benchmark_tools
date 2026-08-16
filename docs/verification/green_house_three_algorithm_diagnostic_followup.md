# Green-house Three-Algorithm Divergence Follow-up

## 1. First real multi-family smoke

Frozen diagnostic run:

```text
/tmp/lio_benchmark_runs/green_house_three_smoke_004
```

The same green-house bag was replayed for about 15 seconds at rate 1.0 in isolated ROS domains.

| Algorithm | Trajectory samples | Duration | Unified Map points |
|---|---:|---:|---:|
| FAST-LIVO2 | 144 | 14.27 s | 26,725 |
| FAST-LIO2 | 139 | 13.80 s | 24,902 |
| KISS-ICP | 124 | 14.30 s | 24,360 |

All three runners returned zero in the smoke run.

## 2. Calibration boundary remains diagnostic-only

Canonical convention:

```text
LIDAR_TO_IMU
```

Frozen values used by the smoke:

```text
R = identity
t = [0.011, 0.02329, -0.04412] m
status = BLOCKED_CALIBRATION
source = handheld_mid360_sensor_v01.yaml / legacy mid360_lio_only.yaml
```

These values are frozen for reproducibility but are not claimed verified. Therefore this smoke must not be promoted to a formal calibrated ranking.

KISS-ICP is LiDAR-only, so the LiDAR–IMU calibration blocker does not apply to its estimator input; it still participates in the same Unified Map/display pipeline as a control baseline.

## 3. Why the next step is diagnostics rather than more algorithms

The first `START_XY_YAW` figures show a reproducible estimator divergence pattern. FAST-LIO2 and KISS-ICP are visually close in the short XY trajectory, while FAST-LIVO2 follows a different planar displacement. FAST-LIO2/KISS-ICP also show a strong height trend in the Unified Map visualization.

Without ground truth and verified calibration these observations are not accuracy verdicts. The next task is to determine whether the divergence is primarily associated with:

```text
XY displacement
Z drift
roll / pitch evolution
yaw evolution
initialization/warmup
```

before adding more baseline families.

## 4. New diagnostic artifacts

`lio-benchmark report` now generates, in addition to the existing report:

```text
metrics/smoke_diagnostics.csv
metrics/pairwise_disagreement.csv
figures/trajectory_z_vs_time.png
figures/trajectory_roll_vs_time.png
figures/trajectory_pitch_vs_time.png
figures/trajectory_yaw_relative_vs_time.png
figures/pairwise_xy_disagreement.png
figures/pairwise_z_disagreement.png
```

Pairwise comparison:

```text
uses common timestamp overlap
uses trajectory interpolation
never uses trajectory index matching
```

`START_XY_YAW` removes only each estimator's arbitrary initial XY and yaw for comparison. Z, roll, pitch, later drift, scale and non-rigid distortion remain visible.

Pairwise quantities are named **disagreement**, not error/accuracy, because no ground-truth trajectory is assumed.

## 5. Re-run the existing smoke artifacts

After pulling the latest `feat/lio-baseline-suite`:

```bash
cd /home/yangxuan/lio_benchmark_tools
RUN=/tmp/lio_benchmark_runs/green_house_three_smoke_004

benchmark_base/bin/lio-benchmark report \
  --run "$RUN" \
  --display-alignment START_XY_YAW \
  --warmup-s 0
```

Then generate an additional post-initialization view without modifying the source artifacts, for example:

```bash
benchmark_base/bin/lio-benchmark report \
  --run "$RUN" \
  --display-alignment START_XY_YAW \
  --warmup-s 2.0
```

The exact warmup value is an analysis choice, not hidden filtering. Always retain the full-run (`warmup=0`) outputs alongside any warmup-aware view.

## 6. Gate before expanding the baseline count

Review at least:

```text
trajectory_z_vs_time.png
trajectory_roll_vs_time.png
trajectory_pitch_vs_time.png
trajectory_yaw_relative_vs_time.png
pairwise_xy_disagreement.png
pairwise_z_disagreement.png
smoke_diagnostics.csv
pairwise_disagreement.csv
```

Then classify the current difference as one or more of:

```text
INITIALIZATION_DOMINANT
PLANAR_DIVERGENCE
VERTICAL_DIVERGENCE
ATTITUDE_DIVERGENCE
TIMESTAMP_OR_EXPORT_SUSPECT
CALIBRATION_SUSPECT
UNRESOLVED
```

These labels are diagnostic notes, not algorithm-quality scores.

## 7. Next experiment sequence

```text
three-algorithm diagnostic smoke
        ↓
freeze/verify LiDAR–IMU calibration
        ↓
repeat the same 15 s segment
        ↓
compare whether divergence persists
        ↓
60–120 s representative segment
        ↓
Point-LIO / DLIO / Leg-KILO / LIO-SAM / GLIM integration
        ↓
full 623 s frozen benchmark
```

Do not expand to a full baseline suite until the current three-algorithm divergence is explainable enough to distinguish estimator behavior from calibration/timestamp/export artifacts.
