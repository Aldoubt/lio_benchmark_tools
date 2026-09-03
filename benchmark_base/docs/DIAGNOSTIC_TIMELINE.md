# Unified diagnostic timeline

This backend prepares one time axis for later interactive LIO inspection. It is post-processing only: it does not rerun a LIO algorithm.

## Why a fixed-rate timeline exists

The raw `trajectory_discontinuity.py` output keeps each algorithm's native output samples. That is useful for audit, but `Δposition/sample` and `Δyaw/sample` are not directly comparable when algorithms publish at different rates.

`diagnostic_timeline.py` therefore resamples every standardized trajectory onto a grid anchored to the run sensor-time origin. The default is `10 Hz` (`0.1 s` per sample). Cross-algorithm step, speed, yaw-rate and acceleration inspection should use this fixed-rate artifact.

## Run it

```bash
benchmark_base/bin/lio-benchmark diagnostics \
  --run /path/to/run \
  --baseline fast_livo2 \
  --hz 10
```

This does not reread the raw point-cloud bag. It consumes standardized trajectories plus existing clock/resource/bag-analysis evidence.

Outputs:

```text
metrics/diagnostic_timeline.json
metrics/diagnostic_timeline/<algorithm>.csv
metrics/diagnostic_timeline/resources/<algorithm>.csv
reports/diagnostic_timeline.md
figures/diagnostic_timeline/position_step_10hz.png
figures/diagnostic_timeline/yaw_step_10hz.png
figures/diagnostic_timeline/cpu_aligned.png
figures/diagnostic_timeline/rss_aligned.png
```

Each per-algorithm timeline row contains:

- absolute sensor/header timestamp;
- bag-relative time;
- XYZ/yaw;
- fixed-rate `Δposition` and `|Δyaw|`;
- speed, yaw rate and scalar acceleration;
- nearest clock-aligned CPU/RSS/thread/write sample when timing evidence supports it;
- resource-sample age and alignment mode;
- anomaly-window ids/types covering that time.

## Anomaly windows

Fixed-rate jump events use the existing robust threshold policy and are grouped per algorithm. Events separated by at most `1.0 s` belong to one window by default. Each window stores:

- exact event start/end bag time;
- a default `±0.5 s` review context;
- event count/types;
- peak position/yaw step;
- severity relative to the event threshold;
- original event records.

This means a sequence such as several GLIM corrected-pose jumps around one second of bag time can be presented as one review region instead of many unrelated markers.

Anomaly windows remain diagnostic. A full-SLAM pose-graph correction can be legitimate and does not automatically change lifecycle/trajectory health.

## Resource alignment

The resource monitor records wall-clock timestamps. `diagnostic_timeline.py` reuses the phase-analysis alignment chain:

```text
resource wall time
  -> /clock anchors
  -> recorded ROS time
  -> recorded-minus-header bag evidence
  -> sensor/header time
  -> bag-relative time
```

When strict anchors/evidence are available, the timeline reports `strict/clock-anchored`. Missing evidence is not fabricated; resource columns remain empty and the alignment mode/warnings explain why.

## Point-cloud frame index

Point-cloud indexing is optional because it deserializes LiDAR message headers from the source rosbag:

```bash
benchmark_base/bin/lio-benchmark diagnostics \
  --run /path/to/run \
  --baseline fast_livo2 \
  --hz 10 \
  --with-pointcloud-index
```

Before using this option, source the ROS overlay that provides the bag's exact LiDAR message type (for the greenhouse bag this includes `livox_ros_driver2/msg/CustomMsg`).

Outputs:

```text
metrics/pointcloud_frame_index.csv
metrics/pointcloud_frame_index.json
```

Each frame index row contains:

- sqlite message id;
- recorded timestamp;
- LiDAR header timestamp;
- bag-relative time.

No point-cloud payload is copied. The JSON keeps the source sqlite path and index metadata, so a later viewer can seek to a selected frame and deserialize only the nearby raw LiDAR messages it needs.

## Intended frontend contract

A later interactive viewer can use the artifacts above to share one cursor across:

```text
bag-relative time
  -> trajectory pose / fixed-rate motion diagnostics
  -> CPU / RSS / threads
  -> anomaly window
  -> raw LiDAR frame index
  -> existing phase analysis
```

The display layer must not redefine the underlying benchmark metrics. Baseline-relative trajectory/map values remain diagnostic/non-ground-truth when independent ground truth is unavailable.
