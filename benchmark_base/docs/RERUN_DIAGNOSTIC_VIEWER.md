# Rerun offline diagnostic viewer

The viewer is a display/inspection layer over frozen benchmark artifacts. It does not change trajectory, map-health, resource-alignment, or anomaly definitions.

## Prerequisites

Generate the unified diagnostic timeline and LiDAR frame index first:

```bash
RUN=/path/to/run

benchmark_base/bin/lio-benchmark diagnostics \
  --run "$RUN" \
  --baseline fast_livo2 \
  --hz 10 \
  --with-pointcloud-index
```

The main full-run algorithms should report `resource_alignment_mode=strict/clock-anchored` when the run contains valid `/clock` anchors and recorded/header timing evidence.

Install the viewer dependency separately from the core benchmark environment:

```bash
python3 -m pip install -r benchmark_base/requirements-viewer.txt
```

The branch currently pins `rerun-sdk==0.36.3` because the Python blueprint API is intentionally version-sensitive.

## Launch the MVP

Source the ROS overlays that provide the bag's exact LiDAR message type when raw point-cloud viewing is enabled:

```bash
source /opt/ros/humble/setup.bash
source /home/yangxuan/agt_navigation_v2/install/setup.bash
source /home/yangxuan/lio_benchmark_algorithms/adapter_ws/install/setup.bash
```

Then launch:

```bash
benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --baseline fast_livo2
```

Default behavior:

- all algorithms from `metrics/diagnostic_timeline.json` are loaded;
- existing reconstructed PLY maps are shown with a display-only `map_point_step=4` reduction;
- trajectories are aligned to the selected baseline with the same initial-yaw + translation diagnostic convention;
- current algorithm positions are logged on the shared `bag_time` timeline;
- CPU, RSS, thread count, 10 Hz position step, yaw step, and speed are logged as synchronized scalar series;
- anomaly windows are logged as timestamped events;
- raw LiDAR uses `pointcloud-mode=anomaly` by default, so only indexed scans near anomaly windows are deserialized and logged.

No rosbag replay and no LIO algorithm process is started.

## Useful modes

Focus on a small candidate set:

```bash
benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --algorithms fast_livo2,point_lio,lio_sam_no_loop,glim_full_slam
```

Disable raw LiDAR completely for the fastest launch:

```bash
benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --pointcloud-mode none
```

Log periodic raw scans as well as exact anomaly-near scans:

```bash
benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --pointcloud-mode sampled \
  --pointcloud-period 1.0 \
  --point-step 20
```

This still uses the SQLite frame index and reads only selected message IDs. It does not replay the bag or pre-extract the full point cloud.

Reduce reconstructed-map display load:

```bash
benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --map-point-step 8
```

## Save an offline RRD

```bash
OUT="$RUN/viewer/greenhouse_round1.rrd"

benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --pointcloud-mode anomaly \
  --save "$OUT" \
  --no-spawn

rerun "$OUT"
```

This is useful for preserving a reproducible inspection artifact without changing the benchmark run itself.

## Intended UI contract

The MVP blueprint is intentionally thin:

- `Map + trajectories`: baseline-aligned reconstructed maps and full trajectories, with the current 10 Hz pose highlighted as the time cursor moves;
- `Current raw LiDAR`: selected raw LiDAR frame in sensor-local coordinates;
- `CPU` / `RSS` / `Motion anomalies`: synchronized performance and trajectory-diagnostic curves;
- `Anomaly windows`: timestamped event records such as the GLIM full-SLAM correction near 353–354 s.

Rerun's global time cursor provides the interaction. Moving or clicking the `bag_time` cursor updates current poses, scalar curves, and whichever indexed raw LiDAR frame has been logged at that time.

## Important semantics

- The PLY maps were reconstructed from the same raw LiDAR data under different standardized trajectories. They are trajectory-induced map-consistency visualizations, not each algorithm's native mapper output.
- Baseline-relative trajectory/map values are diagnostic/non-ground-truth unless independent ground truth exists.
- A full-SLAM pose-graph correction may legitimately create a discontinuity event. The viewer does not convert anomaly windows into lifecycle-health failures.
- `pointcloud-mode=anomaly` is sparse by design. Use `sampled` when you want more continuous raw-scene context while scrubbing.
- Raw LiDAR is displayed in sensor-local coordinates in the MVP. World-frame scan overlay can be added later using the frozen calibration and selected trajectory, without changing the diagnostic timeline contract.
