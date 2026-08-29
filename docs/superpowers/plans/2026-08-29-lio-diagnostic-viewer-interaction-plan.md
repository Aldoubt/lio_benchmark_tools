# LIO Diagnostic Viewer Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Rerun diagnostic viewer with Chinese-first labels, one shared world-pointcloud projection implementation, native/web viewer modes, runtime algorithm visibility control, and anomaly-card click-to-seek without changing benchmark metric semantics.

**Architecture:** Extract the map-reconstruction pose/projection math into a shared Python module and make both map reconstruction and the viewer consume that implementation. Keep the existing native Rerun path for fast inspection. Add a thin local TypeScript/Vite shell around `@rerun-io/web-viewer@0.36.3`; the shell controls time through the supported WebViewer API and sends visibility state to a small Python HTTP controller that updates the Rerun blueprint in the same process that owns the gRPC recording stream.

**Tech Stack:** Python 3.10, ROS 2 Humble, Ubuntu-system NumPy/SciPy, `rerun-sdk==0.36.3`, TypeScript `7.0.2`, Vite `8.2.2`, `@rerun-io/web-viewer==0.36.3`, `vite-plugin-wasm==3.6.0`, `vite-plugin-top-level-await==1.6.0`, Vitest `4.1.11`.

**Spec:** `docs/superpowers/specs/2026-08-29-lio-diagnostic-viewer-freeze-design.md`

## Global Constraints

- Do not change trajectory health, map health, anomaly thresholds, phase classification, resource-alignment semantics, or the `relative-to-baseline/diagnostic/non-ground-truth` metric class.
- Do not introduce any claim that FAST-LIVO2 is ground truth.
- Default repository-owned display language is `zh-CN`; machine-readable JSON/CSV keys remain English and stable.
- `@rerun-io/web-viewer` must stay at `0.36.3` to match `rerun-sdk==0.36.3`.
- Raw point-cloud bytes remain in the source rosbag. The viewer may deserialize selected indexed messages but must not pre-extract or duplicate the full bag.
- World-pointcloud projection must reuse the existing map-reconstruction chain: per-point Livox time, LiDAR extrinsic, interpolated full 3D trajectory pose, initial-yaw/translation baseline alignment, and shared display origin.
- Greenhouse calibration remains diagnostic/provisional; world projection is a visualization according to algorithm X, not an independently verified absolute pose.
- Keep raw sensor-local LiDAR visible as a separate audit entity.
- Default world-pointcloud logging is anomaly-window only; sampled world projection is opt-in.
- No font binary is added to the repository.
- Local benchmark tests on the Ubuntu host use the known-compatible system NumPy/SciPy environment with `PYTHONNOUSERSITE=1` where appropriate.

---

## File Structure

**Create**

- `evaluators/viewer_i18n.py` — repository-owned `zh-CN`/`en` translations.
- `evaluators/viewer_projection.py` — shared trajectory interpolation/alignment/LiDAR projection math.
- `evaluators/web_diagnostic_viewer.py` — Rerun gRPC recording owner plus local web shell launcher.
- `benchmark_base/lio_benchmark/web_viewer_server.py` — stdlib HTTP server for built assets, config JSON, and state POSTs.
- `benchmark_base/web_viewer/package.json`
- `benchmark_base/web_viewer/package-lock.json`
- `benchmark_base/web_viewer/tsconfig.json`
- `benchmark_base/web_viewer/vite.config.ts`
- `benchmark_base/web_viewer/index.html`
- `benchmark_base/web_viewer/src/main.ts`
- `benchmark_base/web_viewer/src/state.ts`
- `benchmark_base/web_viewer/src/i18n.ts`
- `benchmark_base/web_viewer/src/style.css`
- `benchmark_base/web_viewer/src/state.test.ts`
- `benchmark_base/web_viewer/src/i18n.test.ts`
- `tests/test_viewer_i18n.py`
- `tests/test_viewer_projection.py`
- `tests/test_web_viewer_server.py`

**Modify**

- `evaluators/visualize_baseline_maps.py`
- `evaluators/rerun_diagnostic_viewer.py`
- `benchmark_base/lio_benchmark/entry.py`
- `benchmark_base/lio_benchmark/postprocess.py`
- `benchmark_base/docs/RERUN_DIAGNOSTIC_VIEWER.md`
- `benchmark_base/requirements-viewer.txt`
- `tests/test_rerun_diagnostic_viewer.py`
- `tests/test_entry.py`
- `tests/test_postprocess.py`
- `tests/test_map_reconstruction_selection.py`
- `evaluators/check_phase_pipeline.sh`
- `.gitignore`

---

### Task 1: Add the shared Chinese/English presentation layer

**Files:**
- Create: `evaluators/viewer_i18n.py`
- Create: `tests/test_viewer_i18n.py`
- Modify: `evaluators/rerun_diagnostic_viewer.py`
- Modify: `benchmark_base/lio_benchmark/entry.py`
- Modify: `benchmark_base/lio_benchmark/postprocess.py`
- Modify: `tests/test_entry.py`
- Modify: `tests/test_postprocess.py`

**Interfaces:**
- Produces `SUPPORTED_LANGUAGES = ("zh-CN", "en")`.
- Produces `normalize_language(value: str) -> str`.
- Produces `tr(lang: str, key: str, **values: object) -> str`.
- Produces `translate_anomaly_types(lang: str, values: list[str]) -> list[str]`.
- Viewer CLI adds `--lang {zh-CN,en}` with default `zh-CN`.

- [ ] **Step 1: Write the failing translation tests**

Create `tests/test_viewer_i18n.py` with:

```python
import pytest
from viewer_i18n import normalize_language, tr, translate_anomaly_types


def test_chinese_display_strings():
    assert normalize_language("zh-CN") == "zh-CN"
    assert tr("zh-CN", "view.map_trajectories") == "地图与轨迹"
    assert tr("zh-CN", "view.raw_lidar") == "当前原始激光点云"
    assert translate_anomaly_types("zh-CN", ["position_jump", "yaw_jump"]) == ["位置突变", "航向突变"]


def test_english_display_strings():
    assert tr("en", "view.map_trajectories") == "Map + trajectories"
    assert translate_anomaly_types("en", ["position_jump"]) == ["Position jump"]


def test_missing_translation_key_fails_loudly():
    with pytest.raises(KeyError, match="missing.key"):
        tr("zh-CN", "missing.key")
```

Extend `tests/test_entry.py::test_viewer_dispatches_display_options` to pass `--lang en` and assert `viewer_language == "en"`. Extend `tests/test_postprocess.py::test_viewer_stage_only_launches_rerun_consumer` to assert `--lang` and `en` are present in the command.

- [ ] **Step 2: Run the focused tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q \
  tests/test_viewer_i18n.py \
  tests/test_entry.py \
  tests/test_postprocess.py
```

Expected: FAIL because `viewer_i18n.py` and `--lang` do not exist.

- [ ] **Step 3: Implement the translation table and CLI plumbing**

Use one table:

```python
SUPPORTED_LANGUAGES = ("zh-CN", "en")

_TRANSLATIONS = {
    "zh-CN": {
        "view.map_trajectories": "地图与轨迹",
        "view.raw_lidar": "当前原始激光点云",
        "view.world_lidar": "世界坐标点云",
        "view.cpu": "CPU 占用",
        "view.rss": "内存占用",
        "view.motion": "运动异常",
        "view.anomaly_windows": "异常时间窗口",
        "anomaly.position_jump": "位置突变",
        "anomaly.yaw_jump": "航向突变",
        "lod.dense": "稠密",
        "lod.medium": "中等",
        "lod.sparse": "稀疏",
        "status.pose_unavailable": "姿态不可用",
    },
    "en": {
        "view.map_trajectories": "Map + trajectories",
        "view.raw_lidar": "Current raw LiDAR",
        "view.world_lidar": "World LiDAR",
        "view.cpu": "CPU",
        "view.rss": "RSS",
        "view.motion": "Motion anomalies",
        "view.anomaly_windows": "Anomaly windows",
        "anomaly.position_jump": "Position jump",
        "anomaly.yaw_jump": "Yaw jump",
        "lod.dense": "Dense",
        "lod.medium": "Medium",
        "lod.sparse": "Sparse",
        "status.pose_unavailable": "Pose unavailable",
    },
}
```

Use `tr()` for repository-owned view/anomaly labels only. Do not translate entity paths, algorithm keys, metric keys, or stored JSON.

- [ ] **Step 4: Re-run the focused tests and verify PASS**

Run the Step 2 command.

- [ ] **Step 5: Commit Task 1**

```bash
git add evaluators/viewer_i18n.py evaluators/rerun_diagnostic_viewer.py \
  benchmark_base/lio_benchmark/entry.py benchmark_base/lio_benchmark/postprocess.py \
  tests/test_viewer_i18n.py tests/test_entry.py tests/test_postprocess.py
git commit -m "feat: add viewer localization layer"
```

---

### Task 2: Extract and lock one projection implementation shared by maps and viewer

**Files:**
- Create: `evaluators/viewer_projection.py`
- Create: `tests/test_viewer_projection.py`
- Modify: `evaluators/visualize_baseline_maps.py`
- Modify: `tests/test_map_reconstruction_selection.py`

**Interfaces:**
- Dataclass `TrajectoryModel(timestamp_s: np.ndarray, positions: np.ndarray, rotations: Rotation, slerp: Slerp)`.
- Dataclass `IndexedLidarScan(bag_time_s: float, header_timestamp_s: float, points_xyz: np.ndarray, point_times_s: np.ndarray, intensity: np.ndarray)`.
- `load_standardized_trajectory(path: Path) -> TrajectoryModel`.
- `pose_at(model: TrajectoryModel, times_s: np.ndarray, *, max_gap_s: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]`, where the third result is a boolean validity mask.
- `initial_yaw_translation_alignment(reference: TrajectoryModel, candidate: TrajectoryModel) -> tuple[np.ndarray, np.ndarray, dict[str, float]]`.
- `project_points_to_display_world(points_xyz: np.ndarray, point_times_s: np.ndarray, trajectory: TrajectoryModel, extrinsic_rotation: np.ndarray, extrinsic_translation: np.ndarray, alignment_rotation: np.ndarray, alignment_translation: np.ndarray, origin: np.ndarray, max_gap_s: float | None) -> tuple[np.ndarray, np.ndarray]`.
- `visualize_baseline_maps.py` imports these helpers and no longer owns a second pose/alignment implementation.

- [ ] **Step 1: Write a concrete failing full-3D/per-point-time test**

Create a standardized trajectory CSV inside the test rather than relying on undefined fixtures:

```python
import csv
import numpy as np
from scipy.spatial.transform import Rotation
from viewer_projection import load_standardized_trajectory, project_points_to_display_world


def _write_test_trajectory(path):
    quats = Rotation.from_euler(
        "xyz",
        [[0.0, 0.0, 0.0], [10.0, 20.0, 30.0]],
        degrees=True,
    ).as_quat()
    rows = [
        [100.0, 0.0, 0.0, 0.0, *quats[0]],
        [100.1, 1.0, 0.5, 0.2, *quats[1]],
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp_s", "x_m", "y_m", "z_m", "qx", "qy", "qz", "qw"])
        writer.writerows(rows)


def test_world_projection_uses_per_point_time_full_3d_pose_and_extrinsic(tmp_path):
    path = tmp_path / "trajectory.csv"
    _write_test_trajectory(path)
    trajectory = load_standardized_trajectory(path)
    points = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    times = np.array([100.02, 100.08])
    extrinsic_rotation = Rotation.from_euler("y", 30.0, degrees=True).as_matrix()
    world, valid = project_points_to_display_world(
        points,
        times,
        trajectory,
        extrinsic_rotation,
        np.array([0.2615, 0.0, 0.3]),
        np.eye(3),
        np.zeros(3),
        np.zeros(3),
        0.25,
    )
    assert valid.tolist() == [True, True]
    assert not np.allclose(world[0], world[1])
```

Add a second test with trajectory timestamps `100.0` and `101.0`, query `100.5`, and `max_gap_s=0.25`; assert `valid.tolist() == [False]` and no extrapolated point is treated as valid.

- [ ] **Step 2: Write a regression-equivalence test for the existing map formula**

For valid in-range points, calculate the legacy formula in the test:

```python
positions, rotations, valid = pose_at(trajectory, times, max_gap_s=None)
lidar_in_body = (extrinsic_rotation @ points.T).T + extrinsic_translation
legacy_world = np.einsum("nij,nj->ni", rotations, lidar_in_body) + positions
legacy_aligned = (alignment_rotation @ legacy_world.T).T + alignment_translation - origin
assert np.allclose(shared_world, legacy_aligned, atol=1e-9)
```

- [ ] **Step 3: Run focused tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q \
  tests/test_viewer_projection.py \
  tests/test_map_reconstruction_selection.py
```

Expected: FAIL because the shared module does not exist.

- [ ] **Step 4: Move the existing map math into `viewer_projection.py`**

Keep the transform order exactly:

```python
lidar_in_body = (extrinsic_rotation @ selected_points.T).T + extrinsic_translation
world = np.einsum("nij,nj->ni", rotations, lidar_in_body) + positions
aligned = (alignment_rotation @ world.T).T + alignment_translation - origin
```

`pose_at()` interpolates XYZ and uses SciPy `Slerp`. With a gap limit, validity is true only inside trajectory coverage and when the enclosing sample interval is no larger than `max_gap_s`; invalid queries are never extrapolated.

- [ ] **Step 5: Refactor `visualize_baseline_maps.py` to import shared helpers**

Remove its local `load_trajectory`, `pose_at`, and `initial_yaw_translation_alignment` after callers switch. Keep bag reading, voxelization, PLY writing, and plotting in the map script. Existing valid map reconstruction must remain numerically unchanged.

- [ ] **Step 6: Run projection/map tests and verify PASS**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q \
  tests/test_viewer_projection.py \
  tests/test_map_reconstruction_selection.py \
  tests/test_map_comparison_enhancement.py
```

- [ ] **Step 7: Commit Task 2**

```bash
git add evaluators/viewer_projection.py evaluators/visualize_baseline_maps.py \
  tests/test_viewer_projection.py tests/test_map_reconstruction_selection.py
git commit -m "refactor: share lidar world projection math"
```

---

### Task 3: Add structured indexed scans and world-pointcloud logging to native Rerun

**Files:**
- Modify: `evaluators/rerun_diagnostic_viewer.py`
- Modify: `tests/test_rerun_diagnostic_viewer.py`
- Modify: `benchmark_base/lio_benchmark/entry.py`
- Modify: `benchmark_base/lio_benchmark/postprocess.py`
- Modify: `tests/test_entry.py`
- Modify: `tests/test_postprocess.py`

**Interfaces:**
- `scan_from_livox_message(message: object, frame: dict[str, object], *, dense_step: int) -> IndexedLidarScan`.
- `_read_indexed_lidar_scans(...) -> list[IndexedLidarScan]` replaces the point-only tuple return.
- `world_entity_paths(algorithm: str) -> dict[str, str]` returns dense/medium/sparse world paths.
- `log_recording(..., world_pointcloud_mode: str, world_algorithm: str | None, language: str, ...) -> dict[str, object]`.
- CLI adds `--world-pointcloud-mode {none,anomaly,sampled}` default `anomaly` and `--world-algorithm <algorithm>` defaulting to baseline.

- [ ] **Step 1: Write a concrete failing Livox timing test**

```python
from types import SimpleNamespace
import pytest
from rerun_diagnostic_viewer import scan_from_livox_message


def test_livox_scan_preserves_header_plus_offset_time():
    stamp = SimpleNamespace(sec=100, nanosec=0)
    message = SimpleNamespace(
        header=SimpleNamespace(stamp=stamp),
        points=[
            SimpleNamespace(x=float(i), y=0.0, z=0.0, offset_time=i * 1000, reflectivity=i)
            for i in range(21)
        ],
    )
    frame = {"message_id": 11, "bag_time_s": 0.0}
    scan = scan_from_livox_message(message, frame, dense_step=10)
    assert scan.points_xyz.shape == (3, 3)
    assert scan.point_times_s.tolist() == pytest.approx([100.0, 100.00001, 100.00002])
```

Add:

```python
def test_world_entity_paths_are_grouped_by_algorithm():
    assert world_entity_paths("glim_full_slam") == {
        "dense": "world_lidar/glim_full_slam/dense",
        "medium": "world_lidar/glim_full_slam/medium",
        "sparse": "world_lidar/glim_full_slam/sparse",
    }
```

Update CLI tests for both new flags.

- [ ] **Step 2: Run focused viewer tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q \
  tests/test_rerun_diagnostic_viewer.py \
  tests/test_entry.py \
  tests/test_postprocess.py
```

- [ ] **Step 3: Implement one sqlite read/deserialization per selected frame**

For Livox `CustomMsg`:

```python
selected = message.points[::dense_step]
xyz = np.asarray([[p.x, p.y, p.z] for p in selected], dtype=np.float64)
point_times = header_time + np.asarray([p.offset_time for p in selected], dtype=np.float64) * 1e-9
intensity = np.asarray([p.reflectivity for p in selected], dtype=np.float64)
```

Filter all arrays with the same finite/range mask. Derive medium/sparse arrays from the dense arrays; do not reread sqlite for another LOD.

- [ ] **Step 4: Log world projection for all startup-selected algorithms under the bounded policy**

Read `manifest.json` calibration and `evaluation.max_pose_interpolation_gap_s`. For each startup-selected algorithm, compute baseline alignment/display origin and call `project_points_to_display_world()`. Raw entity remains sensor-local. Default world frame selection uses anomaly-near frames only even if raw mode is sampled.

If no projected point is valid for a frame, omit the world cloud and log a timestamped viewer-owned status event using `status.pose_unavailable`.

- [ ] **Step 5: Update the native blueprint**

Add separate sensor-local and world-pointcloud views. Only medium LOD is visible by default. Only `--world-algorithm` is visible in the world view by default; all prelogged algorithm groups remain available via the expanded Blueprint panel.

- [ ] **Step 6: Re-run focused tests and verify PASS**

Run the Step 2 command.

- [ ] **Step 7: Commit Task 3**

```bash
git add evaluators/rerun_diagnostic_viewer.py benchmark_base/lio_benchmark/entry.py \
  benchmark_base/lio_benchmark/postprocess.py tests/test_rerun_diagnostic_viewer.py \
  tests/test_entry.py tests/test_postprocess.py
git commit -m "feat: project indexed lidar into viewer world"
```

---

### Task 4: Build the deterministic TypeScript WebViewer shell

**Files:**
- Create: `benchmark_base/web_viewer/package.json`
- Create: `benchmark_base/web_viewer/package-lock.json`
- Create: `benchmark_base/web_viewer/tsconfig.json`
- Create: `benchmark_base/web_viewer/vite.config.ts`
- Create: `benchmark_base/web_viewer/index.html`
- Create: `benchmark_base/web_viewer/src/state.ts`
- Create: `benchmark_base/web_viewer/src/i18n.ts`
- Create: `benchmark_base/web_viewer/src/style.css`
- Create: `benchmark_base/web_viewer/src/state.test.ts`
- Create: `benchmark_base/web_viewer/src/i18n.test.ts`
- Modify: `.gitignore`

**Interfaces:**
- `ViewerConfig = {grpcUrl, language, algorithms, baseline, worldAlgorithm, anomalyWindows}`.
- `ViewerState = {visibleAlgorithms, worldAlgorithm, pointLod, language}`.
- `anomalySeekNanoseconds(window) -> number` returns midpoint seconds converted to integer nanoseconds.
- `POST /api/state` payload is `ViewerState`.

- [ ] **Step 1: Create the pinned package manifest and lockfile**

`package.json` uses exactly:

```json
{
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run"
  },
  "dependencies": {"@rerun-io/web-viewer": "0.36.3"},
  "devDependencies": {
    "typescript": "7.0.2",
    "vite": "8.2.2",
    "vite-plugin-top-level-await": "1.6.0",
    "vite-plugin-wasm": "3.6.0",
    "vitest": "4.1.11"
  }
}
```

Run `npm install` in `benchmark_base/web_viewer/` and commit the generated `package-lock.json`.

- [ ] **Step 2: Write failing state/i18n tests**

`state.test.ts`:

```ts
import {expect, test} from "vitest";
import {anomalySeekNanoseconds, normalizeState} from "./state";

const config = {
  grpcUrl: "rerun+http://127.0.0.1:9876/proxy",
  language: "zh-CN" as const,
  algorithms: ["fast_livo2", "glim_full_slam"],
  baseline: "fast_livo2",
  worldAlgorithm: "fast_livo2",
  anomalyWindows: [],
};

test("anomaly midpoint becomes rerun nanoseconds", () => {
  expect(anomalySeekNanoseconds({start_bag_time_s: 353.0, end_bag_time_s: 354.0})).toBe(353500000000);
});

test("empty algorithm selection is normalized to baseline", () => {
  expect(normalizeState(config, {visibleAlgorithms: []}).visibleAlgorithms).toEqual(["fast_livo2"]);
});
```

`i18n.test.ts` checks `地图与轨迹`, `异常时间窗口`, `位置突变`, and the English equivalents.

- [ ] **Step 3: Run web tests and verify failure**

```bash
cd benchmark_base/web_viewer
npm test
```

- [ ] **Step 4: Implement pure state helpers and Vite config**

`vite.config.ts` contains:

```ts
import {defineConfig} from "vite";
import wasm from "vite-plugin-wasm";
import topLevelAwait from "vite-plugin-top-level-await";

export default defineConfig({plugins: [wasm(), topLevelAwait()]});
```

Ignore `benchmark_base/web_viewer/node_modules/` and `benchmark_base/web_viewer/dist/` in `.gitignore`.

- [ ] **Step 5: Run `npm test` and `npm run build` and verify PASS**

```bash
npm test
npm run build
test -f dist/index.html
```

- [ ] **Step 6: Commit Task 4**

```bash
git add .gitignore benchmark_base/web_viewer
git commit -m "feat: add rerun web viewer shell"
```

---

### Task 5: Add Python web controller and anomaly click-to-seek

**Files:**
- Create: `benchmark_base/lio_benchmark/web_viewer_server.py`
- Create: `tests/test_web_viewer_server.py`
- Create: `evaluators/web_diagnostic_viewer.py`
- Create: `benchmark_base/web_viewer/src/main.ts`
- Modify: `evaluators/rerun_diagnostic_viewer.py`
- Modify: `benchmark_base/lio_benchmark/entry.py`
- Modify: `benchmark_base/lio_benchmark/postprocess.py`
- Modify: `tests/test_entry.py`
- Modify: `tests/test_postprocess.py`

**Interfaces:**
- `WebViewerServer(config: dict[str, object], state_callback: Callable[[dict[str, object]], None], dist_dir: Path, host: str = "127.0.0.1", port: int = 0)`.
- `GET /viewer-config.json` returns `ViewerConfig`.
- `POST /api/state` validates state, invokes `state_callback`, returns 204; invalid state returns 400.
- `rerun_diagnostic_viewer.send_blueprint(..., visible_algorithms: set[str], world_algorithm: str, point_lod: str, lang: str)` is reusable by the web controller.

- [ ] **Step 1: Write failing Python controller tests**

Create a temporary `dist/index.html`, start the server on port `0`, fetch `/viewer-config.json`, and assert `baseline == "fast_livo2"`. POST:

```json
{
  "visibleAlgorithms": ["fast_livo2"],
  "worldAlgorithm": "fast_livo2",
  "pointLod": "medium",
  "language": "zh-CN"
}
```

and assert the callback receives the same normalized values. POST `worldAlgorithm="unknown"` and assert HTTP 400.

- [ ] **Step 2: Implement the browser interaction in `main.ts`**

Startup:

```ts
const config = await fetch("/viewer-config.json").then(r => r.json()) as ViewerConfig;
const viewer = new WebViewer();
await viewer.start(config.grpcUrl, document.querySelector("#viewer") as HTMLElement, {
  width: "",
  height: "",
  hide_welcome_screen: true,
});
```

Render algorithm checkboxes, world-algorithm selector, LOD choice, language selector, and anomaly buttons. On anomaly click:

```ts
const recordingId = viewer.get_active_recording_id();
if (recordingId === null) throw new Error("No active Rerun recording");
viewer.set_active_timeline(recordingId, "bag_time");
viewer.set_playing(recordingId, false);
viewer.set_current_time(recordingId, "bag_time", anomalySeekNanoseconds(window));
state.worldAlgorithm = window.algorithm;
await postState(state);
```

- [ ] **Step 3: Run Python/web tests before server wiring**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_web_viewer_server.py tests/test_entry.py tests/test_postprocess.py
cd benchmark_base/web_viewer && npm test && npm run build
```

Expected before Python implementation: Python tests FAIL; web pure tests/build PASS.

- [ ] **Step 4: Implement the stdlib HTTP server and blueprint state callback**

Use `ThreadingHTTPServer` bound to `127.0.0.1`. Validate non-empty visible-algorithm subset, known world algorithm, valid LOD, and supported language. The callback sends a new blueprint with visibility overrides for `world/algorithms/<algorithm>` groups and `world_lidar/<algorithm>/<lod>` entities. It does not mutate metric files or recording data.

- [ ] **Step 5: Implement `web_diagnostic_viewer.py` lifecycle**

The sequence is:

```python
rr.init("lio_benchmark_offline_diagnostic_viewer", spawn=False)
server_uri = rr.serve_grpc(grpc_port=args.grpc_port, cors_allow_origin=[http_origin])
log_recording(..., spawn=False, save=None, send_blueprint=False)
send_blueprint(...initial state...)
server = WebViewerServer(...grpcUrl=server_uri...)
webbrowser.open(server.url)
server.serve_forever()
```

Keep the Rerun recording/server alive until Ctrl-C; shut down HTTP cleanly on `KeyboardInterrupt`.

- [ ] **Step 6: Add `viewer --mode native|web` dispatch**

Default is `native`. `postprocess.py` dispatches native to `rerun_diagnostic_viewer.py` and web to `web_diagnostic_viewer.py`. `--mode web --save` is rejected with a clear validation error; freeze/report later use the native save path.

- [ ] **Step 7: Re-run Python/web tests and verify PASS**

Run the Step 3 commands.

- [ ] **Step 8: Commit Task 5**

```bash
git add benchmark_base/lio_benchmark/web_viewer_server.py benchmark_base/web_viewer/src/main.ts \
  evaluators/web_diagnostic_viewer.py evaluators/rerun_diagnostic_viewer.py \
  benchmark_base/lio_benchmark/entry.py benchmark_base/lio_benchmark/postprocess.py \
  tests/test_web_viewer_server.py tests/test_entry.py tests/test_postprocess.py
git commit -m "feat: add anomaly-seeking web diagnostic viewer"
```

---

### Task 6: Integrate gates, docs, and greenhouse Round1 acceptance

**Files:**
- Modify: `benchmark_base/docs/RERUN_DIAGNOSTIC_VIEWER.md`
- Modify: `benchmark_base/requirements-viewer.txt`
- Modify: `evaluators/check_phase_pipeline.sh`

- [ ] **Step 1: Extend Python static/self tests**

Compile `viewer_i18n.py`, `viewer_projection.py`, `web_diagnostic_viewer.py`, and `web_viewer_server.py`; add `test_viewer_i18n.py`, `test_viewer_projection.py`, and `test_web_viewer_server.py` to pytest. Keep Node build outside the core Python gate so benchmark-only hosts do not require Node.

- [ ] **Step 2: Document viewer-specific web gate and Node requirement**

Document Node `>=20.19` or `>=22.12`, then:

```bash
cd benchmark_base/web_viewer
npm ci
npm test
npm run build
```

- [ ] **Step 3: Run complete Python gate**

```bash
cd ~/lio_benchmark_tools
source /opt/ros/humble/setup.bash
PYTHONNOUSERSITE=1 bash evaluators/check_phase_pipeline.sh
git diff --check
```

Expected: all tests PASS; `git diff --check` has no output.

- [ ] **Step 4: Run complete web gate**

```bash
cd ~/lio_benchmark_tools/benchmark_base/web_viewer
node --version
npm ci
npm test
npm run build
```

Expected: all commands PASS and `dist/index.html` exists.

- [ ] **Step 5: Run native Round1 acceptance**

```bash
source ~/lio_benchmark_tools/.venv-viewer/bin/activate
source /opt/ros/humble/setup.bash
source /home/yangxuan/agt_navigation_v2/install/setup.bash
source /home/yangxuan/lio_benchmark_algorithms/adapter_ws/install/setup.bash
RUN=/home/yangxuan/lio_benchmark_runs/greenhouse_full623_round1_001

benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" --mode native --lang zh-CN --baseline fast_livo2 \
  --algorithms fast_livo2,point_lio,lio_sam_no_loop,glim_full_slam \
  --pointcloud-mode sampled --pointcloud-period 1.0 --point-lods 10,20,80 \
  --world-pointcloud-mode anomaly --world-algorithm fast_livo2
```

Verify Chinese repository-owned titles, separate raw/world pointcloud views, medium LOD default, and manual algorithm visibility in Blueprint.

- [ ] **Step 6: Run web Round1 acceptance**

```bash
benchmark_base/bin/lio-benchmark viewer \
  --run "$RUN" --mode web --lang zh-CN --baseline fast_livo2 \
  --algorithms fast_livo2,point_lio,lio_sam_no_loop,glim_full_slam \
  --pointcloud-mode sampled --pointcloud-period 1.0 --point-lods 10,20,80 \
  --world-pointcloud-mode anomaly
```

Acceptance evidence:

- clicking GLIM full-SLAM `353.00-354.00 s` pauses and seeks `bag_time` to approximately `353.5 s`;
- shell selects `glim_full_slam` as world projection for that card;
- switching FAST-LIVO2/GLIM changes visibility only;
- CPU/RSS/motion use the same Rerun playhead;
- no rosbag replay or LIO process starts.

- [ ] **Step 7: Commit docs/gate after host acceptance**

```bash
git status --short
git diff --check
git add benchmark_base/docs/RERUN_DIAGNOSTIC_VIEWER.md \
  benchmark_base/requirements-viewer.txt evaluators/check_phase_pipeline.sh
git commit -m "docs: validate interactive diagnostic viewer"
```

---

## Plan A Completion Gate

Do not start the experiment-freeze/report plan until all are true:

- Python phase/comparison/viewer self-test passes on the Ubuntu benchmark host.
- Web `npm ci`, `npm test`, and `npm run build` pass.
- Native viewer still opens Round1 without metric regeneration.
- Web anomaly click seeks the GLIM `353-354 s` window correctly on `bag_time`.
- World-pointcloud projection is visible for FAST-LIVO2 and GLIM at that window.
- No frozen metric definitions or Round1 benchmark outputs were changed.
