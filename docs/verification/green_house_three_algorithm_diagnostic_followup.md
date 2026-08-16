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
trajectory frame semantics
```

before adding more baseline families.

## 4. Divergence diagnostic artifacts

The full-run `warmup=0` report produces canonical filenames:

```text
metrics/smoke_diagnostics.csv
metrics/pairwise_disagreement.csv
figures/trajectory_z_vs_time.png
figures/trajectory_roll_vs_time.png
figures/trajectory_pitch_vs_time.png
figures/trajectory_yaw_relative_vs_time.png
figures/pairwise_xy_disagreement.png
figures/pairwise_z_disagreement.png
reports/report.md
reports/report.html
```

A non-zero warmup is a separate derived diagnostic view and receives a deterministic suffix. For `--warmup-s 2.0`:

```text
metrics/smoke_diagnostics_warmup_2s.csv
metrics/pairwise_disagreement_warmup_2s.csv
figures/trajectory_z_vs_time_warmup_2s.png
figures/trajectory_roll_vs_time_warmup_2s.png
figures/trajectory_pitch_vs_time_warmup_2s.png
figures/trajectory_yaw_relative_vs_time_warmup_2s.png
figures/pairwise_xy_disagreement_warmup_2s.png
figures/pairwise_z_disagreement_warmup_2s.png
reports/report_warmup_2s.md
reports/report_warmup_2s.html
```

The post-warmup pass therefore cannot overwrite the full-run diagnostic evidence.

Pairwise comparison:

```text
uses common timestamp overlap
uses trajectory interpolation
never uses trajectory index matching
```

`START_XY_YAW` removes only each estimator's arbitrary initial XY and yaw for comparison. Z, roll, pitch, later drift, scale and non-rigid distortion remain visible.

Pairwise quantities are named **disagreement**, not error/accuracy, because no ground-truth trajectory is assumed.

## 5. Warmup result and new frame-semantics hypothesis

The `warmup=0` and `warmup=2 s` diagnostics show that the large late-run disagreement remains after removing the first two seconds. Therefore the current evidence does not support `INITIALIZATION_DOMINANT` as the primary explanation.

The trajectories also show a large initial pitch-gauge difference: FAST-LIVO2 is far from the FAST-LIO2/KISS-ICP initial pitch values. Because `START_XY_YAW` deliberately preserves Z, roll and pitch, a mismatch in parent/tracked-frame semantics can project otherwise similar physical motion into different reported Z axes.

Until the raw ROS message semantics are audited, the observed large Z disagreement must not be labeled estimator vertical error.

Current diagnostic labels:

```text
INITIALIZATION_DOMINANT       -> not supported by current warmup test
EVENT_TRIGGERED_DIVERGENCE    -> observed
POSE_FRAME_SEMANTICS_SUSPECT  -> high priority
VERTICAL_DIVERGENCE           -> observed, not yet an accuracy/error claim
ATTITUDE_DIVERGENCE           -> observed
CALIBRATION_SUSPECT           -> still open
```

## 6. Trajectory Frame Audit

Run the read-only audit on the existing raw output bags and standardized trajectories:

```bash
cd /home/yangxuan/lio_benchmark_tools
git checkout feat/lio-baseline-suite
git pull --ff-only

RUN=/tmp/lio_benchmark_runs/green_house_three_smoke_004

benchmark_base/bin/lio-benchmark audit trajectory-frames \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp
```

Outputs:

```text
metadata/frame_audit/fast_livo2.json
metadata/frame_audit/fast_lio2.json
metadata/frame_audit/kiss_icp.json
metrics/trajectory_frame_audit.csv
```

The audit records, without rewriting data:

```text
raw trajectory rosbag actually used
source trajectory topic
ROS message type
header.frame_id
child_frame_id
frame-id changes during the run
raw first position/quaternion/RPY
standardized first position/quaternion/RPY
raw -> standardized first timestamp delta
raw -> standardized first position delta
raw -> standardized first orientation delta
pose-semantics basis
registry-declared pose_represents/world_frame_semantics, or UNKNOWN
```

For `nav_msgs/msg/Odometry`, the audit records the ROS message semantics as `T_parent_child`. It does not infer that strings such as `body`, `lidar`, `base_link`, `camera_init` or `odom` necessarily mean LiDAR/IMU/base/gravity-aligned frames.

Interpretation gate:

```text
raw-to-standardized orientation delta ~= 0
    -> initial attitude difference already exists in upstream raw output

raw-to-standardized orientation delta is large
    -> trajectory extraction/standardization path is suspect

parent/child frame IDs differ across estimators
    -> investigate frame definitions before comparing Z/roll/pitch

frame IDs change during one estimator run
    -> treat as a contract violation or upstream mode transition requiring investigation
```

Do not add `START_SE3` to hide the difference at this stage.

## 7. Re-run the existing report artifacts

The existing standardized trajectories and maps are enough; the algorithms do not need to be replayed just to regenerate diagnostics.

```bash
RUN=/tmp/lio_benchmark_runs/green_house_three_smoke_004

benchmark_base/bin/lio-benchmark report \
  --run "$RUN" \
  --display-alignment START_XY_YAW \
  --warmup-s 0

benchmark_base/bin/lio-benchmark report \
  --run "$RUN" \
  --display-alignment START_XY_YAW \
  --warmup-s 2.0
```

The exact warmup value is an analysis choice, not hidden filtering. Keep the full-run (`warmup=0`) outputs as the canonical diagnostic evidence and use warmup views only to test whether initialization dominates the observed divergence.

## 8. Gate before expanding the baseline count

Review:

```text
trajectory_frame_audit.csv
metadata/frame_audit/*.json
trajectory_z_vs_time*.png
trajectory_roll_vs_time*.png
trajectory_pitch_vs_time*.png
trajectory_yaw_relative_vs_time*.png
pairwise_xy_disagreement*.png
pairwise_z_disagreement*.png
smoke_diagnostics*.csv
pairwise_disagreement*.csv
```

Only after trajectory parent/tracked-frame semantics are understood should the current difference be promoted from `POSE_FRAME_SEMANTICS_SUSPECT` to a more specific estimator/calibration diagnosis.

These labels are diagnostic notes, not algorithm-quality scores.

## 9. Next experiment sequence

```text
three-algorithm diagnostic smoke
        ↓
full vs post-warmup divergence review
        ↓
raw -> standardized Trajectory Frame Audit
        ↓
resolve parent/tracked-frame semantics
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

Do not expand to a full baseline suite until the current three-algorithm divergence is explainable enough to distinguish frame conventions, estimator behavior, calibration, timestamp and export artifacts.
