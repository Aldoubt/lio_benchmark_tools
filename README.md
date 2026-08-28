# LIO Benchmark Tools

> This repository contains a reproducible ROS 2 LIO/SLAM benchmark harness for MID360 datasets, with algorithm adapters, run manifests, trajectory standardization, diagnostic evaluation, resource monitoring, reports and visualization.

## Current development workflow

The active multi-algorithm benchmark work is developed on feature branches. A completed run can be post-processed without replaying the original rosbag:

```bash
benchmark_base/bin/lio-benchmark visualize --run /path/to/run
```

The lightweight comparison path generates health-aware trajectory figures, baseline-relative diagnostics and resource summaries from standardized trajectories and recorded process-tree resource samples.

Important output examples:

- `figures/comparison_dashboard/trajectory_xy_overlay.png`: health-valid trajectory overlay.
- `figures/comparison_dashboard/relative_to_baseline.png`: relative RMSE/P95 to the selected baseline; diagnostic only when no independent ground truth exists.
- `figures/resource_curves/resource_curves.png`: CPU/RSS/thread time series.
- `figures/resource_curves/resource_summary_valid.png`: health-valid resource summary using CPU median/mean/P95; instantaneous peak CPU remains in JSON/CSV.

For the detailed workflow and interpretation boundaries, see `benchmark_base/docs/COMPARISON_VISUALIZATION.md`.

## Metric boundary

If a dataset does not contain independent ground truth, trajectory length, Z range, endpoint displacement and baseline-relative RMSE/P95 are diagnostic quantities. They must not be reported as ATE/RPE or absolute accuracy.

CPU values use the recorded process-tree logical CPU sum: 100% corresponds to one logical CPU core. A failed or incomplete trajectory must not be interpreted as resource-efficient simply because its mean CPU or memory is low.

## Repository layout

- `benchmark_base/`: CLI, manifests, schemas and benchmark documentation.
- `configs/algorithms/`: algorithm-specific integration/configuration.
- `evaluators/`: trajectory, report, map and resource-analysis tools.
- `ros2_adapters/`: ROS 2 message/data adapters.
- `tests/`: regression tests for benchmark contracts and analysis logic.
- `patches/`: upstream compatibility patches used by benchmark integrations.

## License

See `LICENSE`.
