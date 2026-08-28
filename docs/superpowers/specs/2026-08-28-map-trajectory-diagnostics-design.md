# Map + trajectory diagnostics design

## Goal

Strengthen the existing greenhouse LIO comparison pipeline before building an interactive frontend.

The core pipeline must quantify two things that are currently visible only by manual inspection:

1. trajectory-induced map consistency relative to the selected baseline;
2. timestamped trajectory discontinuities that can later drive an interactive anomaly viewer.

No independent ground truth is available. All baseline-relative quantities remain diagnostic/non-ground-truth and must not be called ATE/RPE or absolute map accuracy.

## Scope

### Map consistency

Use the already reconstructed PLY maps in the selected baseline frame. Do not replay LIO algorithms.

For every available map report:

- raw XYZ extent (`max-min`), retained for audit;
- robust XYZ extent (`P99-P1`) to reduce sensitivity to isolated points;
- baseline-relative voxel occupancy IoU using a comparison voxel no smaller than 0.5 m;
- symmetric nearest-neighbour mean/RMSE/P95 distance, computed on deterministic bounded samples;
- independent `map_health_flags` and `map_health_pass`.

Conservative map-health flags:

- `excessive_robust_z_span`: candidate robust Z span exceeds 2x the baseline robust Z span;
- `low_baseline_voxel_iou`: baseline-relative voxel IoU is below 0.10;
- `high_symmetric_nn_p95`: symmetric NN P95 exceeds 2.0 m.

The baseline always has IoU=1, NN=0 and no map-health flags.

Map health is separate from trajectory lifecycle/health. Primary map figures require both trajectory health and map health; `*_all` figures retain every reconstructable map for failure diagnosis.

### Trajectory discontinuity diagnostics

Consume existing standardized trajectory CSVs only. Do not replay bags or algorithms.

For each algorithm compute one row per consecutive trajectory sample:

- sensor timestamp;
- time relative to the original bag LiDAR `header_first_s` when current-run `bag_analysis.json` is available;
- fallback time relative to baseline standardized trajectory start when bag timing evidence is unavailable;
- `dt_s`;
- position step magnitude;
- yaw step magnitude after unwrap;
- speed;
- yaw rate;
- current XYZ position.

Detect discontinuity events with robust per-trajectory thresholds:

- position threshold = `max(0.5 m, median + 10 * 1.4826 * MAD)`;
- yaw threshold = `max(10 deg, median + 10 * 1.4826 * MAD)`.

Events are diagnostic only. A loop-closure correction can be a real jump rather than an algorithm failure, so discontinuity events do not automatically modify trajectory health.

Outputs:

- `metrics/trajectory_discontinuity.json` — summary + timestamped anomaly events + time-origin provenance;
- `metrics/trajectory_discontinuity/<algorithm>.csv` — complete per-step time series suitable for a later frontend;
- `reports/trajectory_discontinuity.md`;
- `figures/trajectory_discontinuity/position_step.png`;
- `figures/trajectory_discontinuity/yaw_step.png`.

### Current-run report integration

`current_run_report.py` consumes the new artifacts when present:

- expose map health separately from trajectory health;
- make `recommendation_eligible` false when a current-run map exists and explicitly fails map health;
- keep map-missing runs eligible based on trajectory health alone;
- show discontinuity counts/maxima without turning them into an automatic failure gate.

### Future interactive frontend contract

The interactive frontend is explicitly deferred. This core work provides the artifacts it will need:

- standardized trajectory CSVs;
- reconstructed PLYs;
- map consistency metrics;
- trajectory discontinuity per-step CSVs and timestamped events;
- existing resource-monitor sample history;
- existing strict clock/bag timing evidence and phase analysis.

A later frontend can use one selected bag-relative sensor timestamp to highlight trajectory position, nearby point-cloud data and synchronized resource/phase anomalies without changing the metric definitions implemented here.
