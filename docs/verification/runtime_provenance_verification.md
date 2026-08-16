# Runtime Provenance Verification

Date: 2026-08-16

## Target-machine acceptance

Repository branch: `feat/lio-baseline-suite`

Implementation HEAD: `496df8bdaf2cc686e5dac1b4af249f4ead3e0f11`

Target run:

```text
/home/yangxuan/lio_benchmark_runs/green_house/green_house_provenance_accept_20260816_172559
```

The fresh target run used the frozen three-algorithm manifest and produced:

```text
FAST-LIVO2: runtime PASS, identity FROZEN, provenance MATCH, frame MATCH
FAST-LIO2:  runtime PASS, identity FROZEN, provenance MATCH, frame MATCH
KISS-ICP:   runtime PASS, identity FROZEN, provenance MATCH, frame MATCH
```

The run-local evidence is:

```text
metadata/algorithms/<algorithm>/runtime_identity.json
metrics/runtime_provenance.csv
metrics/trajectory_frame_audit.csv
```

## Audited Runtime Sources

FAST-LIVO2 is a vendored ROS 2 package:

```text
repository: Aldoubt/agt_navigation_v2
source_subpath: third_party/fast_livo2_ros2
commit: f060ee88f7d907948e6095e2cd985715e45678ab
package: fast_livo
executable: fastlivo_mapping
```

FAST-LIO2 is the explicit binary built from:

```text
repository: PolarisXQ/SCURM_SentryNavigation
source_subpath: FAST_LIO
commit: 46e6425c692ec98f8e65446fb6fdd360f44ef8e5
package: fast_lio
executable: fastlio_mapping
binary: /home/yangxuan/RM-NAV/build/fast_lio/fastlio_mapping
```

The audited FAST-LIO2 frame contract is `odom -> sensor`, matching the source implementation and generated benchmark configuration. No frame relabeling or coordinate transform was applied.

KISS-ICP provenance remains matched to `PRBonn/kiss-icp`, with the persistent runtime overlay recorded in its frozen identity.

## Scientific Boundary

LiDAR-IMU calibration remains `UNCONFIRMED`.

FAST-LIVO2 and FAST-LIO2 remain `DIAGNOSTIC_ONLY`.

This verification establishes runtime implementation provenance and frame-contract consistency only. It does not establish estimator accuracy and does not implement or claim Relative SE(3) Motion Benchmark results.
