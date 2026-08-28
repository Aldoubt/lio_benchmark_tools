# Comparison and visualization workflow

This document describes the post-processing path for an existing benchmark run. The goal is to separate expensive ROS/bag processing from lightweight result inspection.

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
- `figures/resource_curves/resource_curves.png`
- `figures/resource_curves/resource_summary.png`
- `figures/resource_curves/resource_summary_valid.png`
- `reports/comprehensive_comparison.{json,md,csv}`
- `figures/comprehensive_comparison/comprehensive_summary.png`

`compare` always refreshes the standardized comparison first, then renders figures and the comprehensive report.

## Lightweight visualization only

```bash
benchmark_base/bin/lio-benchmark visualize --run /path/to/run
```

If `metrics/full_comparison.json` already exists, this does not replay the trajectory bags. It uses standardized CSV trajectories and existing resource-monitor outputs.

The default trajectory figures only show algorithms whose lifecycle status is `SUCCESS` and whose trajectory health flags are empty. Diverged or incomplete algorithms remain available in the `*_all.png` figures so failures are not hidden but also do not destroy the scale of paper-facing plots.

The XY overlay uses initial yaw + translation alignment to the selected baseline. This is a relative diagnostic visualization. Without independent ground truth it must not be interpreted as ATE/RPE or absolute accuracy.

Select another baseline when needed:

```bash
benchmark_base/bin/lio-benchmark visualize \
  --run /path/to/run \
  --baseline glim_odometry
```

## Resource figures

`resource_curves.png` keeps the full process-tree time series for CPU, RSS and thread count. CPU 100% means one logical CPU core. Do not interpret a low average CPU value as efficiency when the corresponding trajectory has failed or terminated early.

`resource_summary.png` keeps all algorithms and marks rows with trajectory health failures. `resource_summary_valid.png` excludes those health-fail algorithms for selection-oriented comparison. Mean and peak CPU are drawn as side-by-side bars rather than overlaid bars, and every panel uses algorithm labels on the x-axis.

Peak CPU is intentionally retained because it describes scheduler demand, but for bursty algorithms it can be much larger than the typical load. The time-series curve should be consulted together with the mean/peak summary; a future resource schema may add median/P95 CPU and bag/sensor time so bursts can be tied to specific trajectory segments.

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
- A very large path length can dominate linear plots; the dashboard switches the path-length panel to logarithmic scale when the dynamic range is large.
- Map reconstruction compares how the same raw LiDAR points are projected by different trajectories; it does not measure each algorithm's internal mapping implementation.
