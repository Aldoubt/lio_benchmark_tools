# Rerun offline diagnostic viewer

The viewer is a display/inspection layer over frozen benchmark artifacts. It does not redefine trajectory health, map health, resource alignment, anomaly thresholds, or metric semantics.

Without independent ground truth, baseline-relative trajectory/map quantities remain `relative-to-baseline/diagnostic/non-ground-truth`.

## 1. Prerequisites

Generate the diagnostic timeline and LiDAR frame index first:

```bash
RUN=/path/to/run

benchmark_base/bin/lio-benchmark diagnostics \
  --run "$RUN" \
  --baseline fast_livo2 \
  --hz 10 \
  --with-pointcloud-index
```

Source the ROS overlays that provide the exact LiDAR message type in the bag:

```bash
source /opt/ros/humble/setup.bash
source /home/yangxuan/agt_navigation_v2/install/setup.bash
source /home/yangxuan/lio_benchmark_algorithms/adapter_ws/install/setup.bash
```

The tested Viewer SDK is pinned to:

```text
rerun-sdk==0.36.3
@rerun-io/web-viewer==0.36.3
```

The WebViewer package version intentionally matches the Python Rerun SDK version.

## 2. Python environment

Keep the ROS/benchmark scientific Python stack separate from user-site packages. On the Ubuntu benchmark host, the known-good gate uses the system NumPy/SciPy environment:

```bash
PYTHONNOUSERSITE=1 bash evaluators/check_phase_pipeline.sh
```

A Viewer venv may inherit the ROS/system packages:

```bash
python3 -m venv --system-site-packages .venv-viewer
source .venv-viewer/bin/activate
python -m pip install --no-deps rerun-sdk==0.36.3
```

No font binaries or large bag/point-cloud assets are added by the Viewer.

## 3. Native Viewer

Native mode remains the quick inspection path:

```bash
benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --mode native \
  --baseline fast_livo2 \
  --lang zh-CN \
  --algorithms fast_livo2,point_lio,lio_sam_no_loop,glim_full_slam
```

Repository-owned panel labels default to Chinese. Use `--lang en` for English. Machine-readable JSON/CSV keys remain English.

The Blueprint panel stays expanded so algorithm groups and point-cloud LODs can be shown/hidden interactively.

## 4. Raw LiDAR and point density

Raw LiDAR remains in sensor-local coordinates under:

```text
sensor/raw_lidar/dense
sensor/raw_lidar/medium
sensor/raw_lidar/sparse
```

Default strides:

```text
dense=10
medium=20
sparse=80
```

Configure them with:

```bash
--point-lods 10,20,80
```

Each selected rosbag message is deserialized once at the dense stride. Medium/sparse LODs are derived from that dense selection in memory; the sqlite message is not reread for each LOD.

Raw frame selection modes:

```text
none     no raw LiDAR
anomaly  anomaly-near indexed frames only
sampled  periodic frames plus anomaly-near frames
```

Example:

```bash
benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --mode native \
  --pointcloud-mode sampled \
  --pointcloud-period 1.0 \
  --point-lods 10,20,80
```

No rosbag replay is used.

## 5. World LiDAR projection

World LiDAR is logged separately from raw sensor-local LiDAR:

```text
world_lidar/<algorithm>/dense
world_lidar/<algorithm>/medium
world_lidar/<algorithm>/sparse
```

The projection deliberately reuses the comparison-map reconstruction chain:

```text
Livox header + per-point offset_time
  -> LiDAR point time
  -> manifest lidar_to_imu extrinsic
  -> standardized trajectory XYZ interpolation + quaternion Slerp
  -> algorithm pose
  -> initial-yaw + translation alignment to baseline
  -> shared display origin
```

The Viewer therefore answers: “where would this exact scan be placed in the displayed comparison world according to algorithm X?” It is not an independently verified absolute-world measurement.

Pose interpolation respects `evaluation.max_pose_interpolation_gap_s`. If no valid pose covers a scan/point, the projected cloud is omitted instead of extrapolated.

World-cloud modes:

```text
none     no projected world cloud
anomaly  anomaly-near frames only (default)
sampled  periodic plus anomaly-near frames
```

Select the initially visible algorithm with:

```bash
--world-algorithm point_lio
```

All startup-selected algorithms are prelogged for the bounded world-frame set, so Blueprint/Web controls can switch algorithms without rereading the bag.

## 6. WebViewer with algorithm controls and anomaly click-to-seek

The formal interactive mode uses a small localhost TypeScript/Vite shell around Rerun WebViewer. Rerun still renders 3D, plots, entities, selection, and the timeline; the shell owns only benchmark-specific controls.

Install/build once:

```bash
cd benchmark_base/web_viewer
npm install
npm test
npm run build
cd ../..
```

After `package-lock.json` has been generated and committed, repeatable installations use `npm ci`.

Launch:

```bash
benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --mode web \
  --baseline fast_livo2 \
  --lang zh-CN \
  --algorithms fast_livo2,point_lio,lio_sam_no_loop,glim_full_slam \
  --pointcloud-mode sampled \
  --pointcloud-period 1.0 \
  --world-pointcloud-mode anomaly
```

The shell exposes:

- algorithm multi-select;
- selected world-LiDAR algorithm;
- Dense/Medium/Sparse LOD selection;
- Chinese/English selection;
- anomaly-window buttons.

Clicking an anomaly button:

1. selects the Rerun `bag_time` timeline;
2. pauses playback;
3. seeks to the anomaly-window midpoint in nanoseconds;
4. ensures the anomaly algorithm is visible;
5. changes the selected world-LiDAR algorithm to that anomaly algorithm.

This interaction does not modify benchmark artifacts.

`--mode web --save ...` is intentionally rejected. Use native mode for `.rrd` recording output.

Use `--no-spawn` in web mode when you want the localhost server without automatically opening a browser.

## 7. Native `.rrd` output

```bash
OUT="$RUN/viewer/greenhouse_round1.rrd"
mkdir -p "$(dirname "$OUT")"

benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" \
  --mode native \
  --pointcloud-mode anomaly \
  --world-pointcloud-mode anomaly \
  --save "$OUT" \
  --no-spawn

rerun "$OUT"
```

The `.rrd` is a display artifact. It does not replace the original metrics, standardized trajectories, pointcloud frame index, or source rosbag.

## 8. Algorithm visibility

Startup scope is controlled by `--algorithms`:

```bash
--algorithms fast_livo2,point_lio,glim_full_slam
```

Native mode also exposes Rerun Blueprint eye toggles. Web mode exposes explicit algorithm checkboxes and sends only visibility/LOD/language state back to the Python process, which updates the Rerun blueprint. Metric data is never rewritten.

## 9. Verification gates

Python/benchmark gate:

```bash
cd ~/lio_benchmark_tools
PYTHONNOUSERSITE=1 bash evaluators/check_phase_pipeline.sh
git diff --check
```

Web gate:

```bash
cd benchmark_base/web_viewer
npm test
npm run build
test -f dist/index.html
```

For the greenhouse Round1 acceptance, inspect at least one known correction window in WebViewer and verify that clicking the anomaly card moves the shared `bag_time` cursor and switches the world cloud to the anomaly algorithm. The acceptance is interaction validation, not an absolute accuracy claim.
