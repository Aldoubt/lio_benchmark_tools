# Comparison and visualization workflow

This document describes the post-processing path for an existing benchmark run. The goal is to separate expensive ROS/bag processing from lightweight result inspection, and to keep failed/divergent trajectories from flattening the scale of otherwise comparable runs.

## One-command comparison

```bash
benchmark_base/bin/lio-benchmark compare --run /path/to/run
```

The default command is lightweight after standardized trajectories exist. It generates or refreshes:

- `metrics/full_comparison.json`
- `reports/full_comparison.md`
- `figures/comparison_dashboard/trajectory_xy_overlay.png`
- `figures/comparison_dashboard/trajectory_z_drift.png`
- `figures/comparison_dashboard/diagnostic_dashboard.png`
- `figures/comparison_dashboard/relative_to_baseline.png`
- `figures/comparison_dashboard/trajectory_xy_overlay_all.png`
- `figures/comparison_dashboard/trajectory_z_drift_all.png`
- `figures/comparison_dashboard/diagnostic_dashboard_all.png`
- `figures/resource_curves/resource_curves.png`
- `figures/resource_curves/resource_summary.png`
- `reports/comprehensive_comparison.{json,md,csv}`
- `figures/comprehensive_comparison/comprehensive_summary.png`

`compare` always refreshes the standardized comparison first, then renders figures and the comprehensive report.

## Lightweight visualization only

```bash
benchmark_base/bin/lio-benchmark visualize --run /path/to/run
```

If `metrics/full_comparison.json` already exists, this does not replay the trajectory bags. It uses standardized CSV trajectories and existing resource-monitor outputs.

The primary XY/Z/dashboard figures are health-gated: an algorithm is shown in the primary comparison when its lifecycle status is `SUCCESS` and `health_flags` is empty. Runs marked with flags such as `trajectory_short` or `path_divergence` remain available in the corresponding `*_all.png` failure-diagnostic figures. This prevents a kilometre-scale divergence from hiding metre-scale differences among usable trajectories.

The XY overlay uses initial yaw + translation alignment to the selected baseline. This is a relative diagnostic visualization. Without independent ground truth it must not be interpreted as ATE/RPE or absolute accuracy.

`relative_to_baseline.png` shows baseline-relative RMSE and P95 only for health-valid trajectories. It is useful for comparing trajectory-shape agreement with the selected baseline, but it is still not an absolute accuracy score.

Select another baseline when needed:

```bash
benchmark_base/bin/lio-benchmark visualize \
  --run /path/to/run \
  --baseline glim_odometry
```

## Optional map reconstruction

Map reconstruction is intentionally opt-in because it re-reads the raw LiDAR bag and can be expensive for long MID360 datasets.

```bash
benchmark_base/bin/lio-benchmark compare \
  --run /path/to/run \
  --with-maps \
  --scan-step 5 \
  --point-step 20 \
  --voxel 0.12
```

This additionally runs `visualize_baseline_maps.py` and writes baseline-aligned PLY/maps under `figures/fast_livo2_baseline_maps/` by default.

## Individual stages

```bash
benchmark_base/bin/lio-benchmark standardize --run /path/to/run
benchmark_base/bin/lio-benchmark evaluate --run /path/to/run
benchmark_base/bin/lio-benchmark visualize --run /path/to/run
benchmark_base/bin/lio-benchmark report --run /path/to/run
```

`standardize` and `evaluate` currently share the canonical `summarize_smoke_run.py` pass because trajectory extraction, cleanup, diagnostic metrics and resource summary are produced together. This avoids maintaining two incompatible parsing paths.

Use `--dry-run` on any of these commands to inspect the exact subprocess plan before execution.

## Output semantics

- `path_length_m`, `z_range_m`, endpoint displacement and baseline-relative RMSE are diagnostics when no independent ground truth exists.
- CPU 100% means one logical CPU core in the existing resource monitor.
- Peak RSS is process-tree resident memory when the monitor data is available.
- A lifecycle `SUCCESS` does not by itself mean that a trajectory is usable; health flags are evaluated separately.
- The primary dashboard excludes health-failed trajectories. The all-results dashboard retains them and switches path/Z panels to logarithmic scale when the dynamic range is large.
- Resource values from a divergent or short trajectory must not be interpreted as efficiency advantages without considering trajectory health.
- Map reconstruction compares how the same raw LiDAR points are projected by different trajectories; it does not measure each algorithm's internal mapping implementation.
