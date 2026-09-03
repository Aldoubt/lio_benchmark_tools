# LIO Experiment Freeze + HTML/PDF Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an immutable `lio-benchmark freeze` workflow that records experiment provenance, generates deterministic evidence images, writes one shared `report_data.json`, and renders both an offline HTML archive and a direct PDF snapshot for a completed benchmark run.

**Architecture:** Treat the selected run as immutable input. Build the report model by reusing `current_run_report.build_report()` plus frozen diagnostic/map/resource artifacts, generate deterministic static evidence including anomaly-local raw/world LiDAR through Plan A's shared projection module, then render HTML and PDF from the same model. Build the snapshot in a dot-prefixed incomplete directory, hash source/generated artifacts with SHA-256, and atomically rename to the final unique snapshot directory only when every requested output succeeds.

**Tech Stack:** Python 3.10, existing NumPy/SciPy/Matplotlib stack, ROS 2 Humble for indexed Livox message deserialization, `Jinja2==3.1.6`, `reportlab==5.0.1`, existing `rerun-sdk==0.36.3` for archived `.rrd` output.

**Spec:** `docs/superpowers/specs/2026-08-29-lio-diagnostic-viewer-freeze-design.md`

**Dependency:** Plan A `docs/superpowers/plans/2026-08-29-lio-diagnostic-viewer-interaction-plan.md` must pass its completion gate first. This plan imports `viewer_i18n.py` and `viewer_projection.py` rather than creating alternate translation or projection implementations.

## Global Constraints

- `report_data.json` is the only semantic source for HTML and PDF; renderers do not independently recalculate benchmark conclusions.
- Reuse `current_run_report.build_report()` for current-run comparison semantics instead of copying recommendation/health logic.
- When no independent GT exists, all baseline-relative trajectory/map quantities remain `relative-to-baseline/diagnostic/non-ground-truth`.
- Never describe FAST-LIVO2 as ground truth.
- Never describe reconstructed comparison PLY as an algorithm-native map unless the source artifact actually is native-map output.
- Freeze never overwrites an existing final snapshot directory.
- The full rosbag and large PLY files are not copied by default; their paths, sizes, and SHA-256 hashes are recorded.
- All requested outputs are success-or-error. A failed PDF returns non-zero and must not leave a final directory that looks complete.
- Evidence figures are deterministic Matplotlib/static assets; reports do not depend on screenshots of the interactive Viewer.
- PDF uses local system CJK fonts only. No font binary is committed, copied into the freeze bundle, or shared.
- Default language is `zh-CN`; internal schema keys remain English.
- Freeze does not replay the rosbag or launch any LIO algorithm. It may deserialize indexed LiDAR messages directly from the source sqlite bag.

---

## File Structure

**Create**

- `benchmark_base/requirements-report.txt`
- `evaluators/report_data.py`
- `evaluators/report_evidence.py`
- `evaluators/report_html.py`
- `evaluators/report_pdf.py`
- `evaluators/freeze_experiment.py`
- `benchmark_base/report_templates/report.html.j2`
- `benchmark_base/report_templates/report.css`
- `tests/test_report_data.py`
- `tests/test_report_evidence.py`
- `tests/test_report_html.py`
- `tests/test_report_pdf.py`
- `tests/test_freeze_experiment.py`
- `benchmark_base/docs/FROZEN_EXPERIMENT_REPORT.md`

**Modify**

- `benchmark_base/lio_benchmark/entry.py`
- `benchmark_base/lio_benchmark/postprocess.py`
- `tests/test_entry.py`
- `tests/test_postprocess.py`
- `evaluators/check_phase_pipeline.sh`
- `benchmark_base/docs/RERUN_DIAGNOSTIC_VIEWER.md`

---

### Task 1: Define freeze identity, hashing primitives, and incomplete/final lifecycle

**Files:**
- Create: `evaluators/freeze_experiment.py`
- Create: `tests/test_freeze_experiment.py`

**Interfaces:**
- `sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str`.
- `sha256_path(path: Path) -> dict[str, object]`; file result has `kind`, `path`, `size_bytes`, `sha256`; directory result has deterministic child entries and aggregate digest.
- `benchmark_git_identity(repo_root: Path) -> dict[str, object]` returns `branch`, `commit`, `short_commit`, `dirty`.
- `build_snapshot_name(run_id: str, timestamp_utc: datetime, short_sha: str) -> str` with UTC format `YYYYmmddTHHMMSSZ`.
- `FreezeWorkspace.create(run: Path, snapshot_name: str) -> FreezeWorkspace` creates only `<RUN>/frozen/.<snapshot>.incomplete` and refuses conflicts.
- `FreezeWorkspace.finalize() -> Path` atomically renames incomplete to `<RUN>/frozen/<snapshot>`.
- `FreezeWorkspace.mark_failed(error: str) -> None` writes `freeze_status.json` with `state=INCOMPLETE` and leaves no final snapshot.

- [ ] **Step 1: Write failing hashing/lifecycle tests**

```python
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import pytest
from freeze_experiment import FreezeWorkspace, build_snapshot_name, sha256_file


def test_sha256_file_matches_content(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == hashlib.sha256(b"abc").hexdigest()


def test_snapshot_name_is_deterministic():
    stamp = datetime(2026, 8, 29, 8, 0, 0, tzinfo=timezone.utc)
    assert build_snapshot_name("greenhouse_round1", stamp, "12d1e9f") == "greenhouse_round1_20260829T080000Z_12d1e9f"


def test_freeze_workspace_never_overwrites_final_snapshot(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    final = run / "frozen" / "greenhouse_round1_20260829T080000Z_12d1e9f"
    final.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        FreezeWorkspace.create(run, final.name)


def test_failed_workspace_never_becomes_final(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    name = "greenhouse_round1_20260829T080000Z_12d1e9f"
    workspace = FreezeWorkspace.create(run, name)
    workspace.mark_failed("pdf failed")
    assert not (run / "frozen" / name).exists()
    status = workspace.incomplete_dir / "freeze_status.json"
    assert '"INCOMPLETE"' in status.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run lifecycle tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_freeze_experiment.py
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement streaming SHA-256 and workspace lifecycle**

Hash file contents in chunks:

```python
with path.open("rb") as stream:
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        digest.update(chunk)
```

Directory hashing sorts children by POSIX relative path and combines relative path, size, and child digest. Never load the bag into RAM. Finalization uses `Path.replace()` or `os.replace()` only within the same run filesystem.

- [ ] **Step 4: Re-run lifecycle tests and verify PASS**

- [ ] **Step 5: Commit Task 1**

```bash
git add evaluators/freeze_experiment.py tests/test_freeze_experiment.py
git commit -m "feat: add immutable freeze workspace"
```

---

### Task 2: Build one report-data model and deterministic anomaly-case selection

**Files:**
- Create: `evaluators/report_data.py`
- Create: `tests/test_report_data.py`

**Interfaces:**
- `select_anomaly_cases(windows: list[dict[str, object]], run_status: dict[str, object], *, max_cases: int = 6) -> list[str]` returns ordered `window_id`s.
- `build_report_data(run: Path, *, baseline: str, language: str, max_cases: int = 6) -> dict[str, object]`.
- Schema version starts at `1` and includes `metric_class`, `no_ground_truth`, `baseline`, `experiment`, `dataset`, `algorithms`, `health`, `trajectory`, `maps`, `resources`, `anomalies`, `selected_case_ids`, `conclusions`, `reproducibility`, `disclaimer`.
- Conclusions reuse `current_run_report.build_report()` recommendations and explicit anomaly evidence.

- [ ] **Step 1: Write a concrete failing case-selection test**

```python
from report_data import select_anomaly_cases


def test_case_selection_covers_position_yaw_and_crash_without_duplicates():
    windows = [
        {"window_id": "point:1", "algorithm": "point_lio", "severity": 3.0, "types": ["position_jump"]},
        {"window_id": "glim:1", "algorithm": "glim_full_slam", "severity": 2.5, "types": ["position_jump"]},
        {"window_id": "kiss:1", "algorithm": "kiss_icp", "severity": 2.0, "types": ["yaw_jump"]},
        {"window_id": "dlio:1", "algorithm": "dlio", "severity": 1.5, "types": ["position_jump"]},
    ]
    run_status = {
        "algorithms": {
            "point_lio": {"result": {"status": "SUCCESS"}},
            "glim_full_slam": {"result": {"status": "SUCCESS"}},
            "kiss_icp": {"result": {"status": "SUCCESS"}},
            "dlio": {"result": {"status": "RUNTIME_CRASH"}},
        }
    }
    ids = select_anomaly_cases(windows, run_status, max_cases=4)
    assert len(ids) == len(set(ids))
    selected = [window for window in windows if window["window_id"] in ids]
    assert any("position_jump" in window["types"] for window in selected)
    assert any("yaw_jump" in window["types"] for window in selected)
    assert any(window["algorithm"] == "dlio" for window in selected)
```

- [ ] **Step 2: Write report semantic tests with a concrete stub current-run model**

Monkeypatch `report_data.build_current_run_report` to return:

```python
{
    "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
    "baseline": "fast_livo2",
    "recommendations": {"closest_to_baseline": "point_lio"},
    "algorithms": [],
}
```

Create minimal `manifest.json`, `metadata/run_status.json`, and `metrics/diagnostic_timeline.json`, then assert:

```python
assert data["metric_class"] == "relative-to-baseline/diagnostic/non-ground-truth"
assert data["no_ground_truth"] is True
assert data["baseline"] == "fast_livo2"
assert data["anomalies"][0]["types"] == ["position_jump"]
assert data["anomalies"][0]["display_types_zh"] == ["位置突变"]
```

- [ ] **Step 3: Run report-data tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_report_data.py
```

- [ ] **Step 4: Implement report-data assembly by composition**

Import:

```python
from current_run_report import build_report as build_current_run_report
from viewer_i18n import tr, translate_anomaly_types
```

Do not recompute whole-run RMSE/P95/recommendation logic in `report_data.py`. Read diagnostic timeline, pointcloud frame index, manifest, and run status only for fields not already represented by the current-run report model.

- [ ] **Step 5: Implement evidence-limited conclusion records**

Store structured records such as:

```python
{
    "kind": "closest_to_baseline",
    "algorithm": "point_lio",
    "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
}
```

For anomalies, store window ID, algorithm, start/end time, types, and severity. Renderers localize these records. Do not store claims of absolute accuracy.

- [ ] **Step 6: Run report-data/current-report tests and verify PASS**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q \
  tests/test_report_data.py \
  tests/test_current_run_report.py \
  tests/test_current_run_diagnostics.py
```

- [ ] **Step 7: Commit Task 2**

```bash
git add evaluators/report_data.py tests/test_report_data.py
git commit -m "feat: add frozen report data model"
```

---

### Task 3: Generate deterministic evidence images including anomaly-local raw/world LiDAR

**Files:**
- Create: `evaluators/report_evidence.py`
- Create: `tests/test_report_evidence.py`

**Interfaces:**
- `collect_existing_figures(run: Path, output_root: Path) -> list[dict[str, object]]`.
- `generate_case_evidence(run: Path, case: dict[str, object], *, baseline: str, output_dir: Path, point_step: int = 20) -> dict[str, str]`.
- Case outputs are `trajectory.png`, `motion.png`, `resources.png`, `raw_lidar.png`, `world_selected.png`, and when selected algorithm differs from baseline, `world_baseline.png`.
- Reuse `viewer_projection.IndexedLidarScan` and Plan A projection helpers.

- [ ] **Step 1: Write failing existing-figure collection test**

Create only:

```text
figures/comparison_dashboard/diagnostic_dashboard.png
figures/diagnostic_timeline/cpu_aligned.png
```

in a temporary run, then assert `collect_existing_figures()` copies exactly those files to deterministic evidence destinations. Missing optional figures are not fabricated.

- [ ] **Step 2: Write failing projection/evidence tests**

Create a tiny indexed scan and standardized trajectory. Monkeypatch `report_evidence.project_points_to_display_world` with a wrapper that records the `point_times_s` argument and delegates to the real helper. Run `generate_case_evidence()` and assert:

```python
assert observed_point_times.shape[0] == scan.points_xyz.shape[0]
assert (output_dir / "raw_lidar.png").is_file()
assert (output_dir / "world_selected.png").is_file()
```

Run the same case twice into separate directories and assert corresponding PNG dimensions are equal and returned evidence metadata are identical except for destination paths.

- [ ] **Step 3: Run evidence tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_report_evidence.py
```

- [ ] **Step 4: Implement exact existing-figure allowlist**

Recognize only these current-run figure paths when present:

```text
figures/comparison_dashboard/trajectory_xy_overlay.png
figures/comparison_dashboard/trajectory_z_drift.png
figures/comparison_dashboard/diagnostic_dashboard.png
figures/comparison_dashboard/relative_to_baseline.png
figures/diagnostic_timeline/position_step_10hz.png
figures/diagnostic_timeline/yaw_step_10hz.png
figures/diagnostic_timeline/cpu_aligned.png
figures/diagnostic_timeline/rss_aligned.png
figures/fast_livo2_baseline_maps/map_comparison_xy.png
figures/fast_livo2_baseline_maps/map_comparison_xz.png
```

Do not glob unrelated `*_all` or historical figures into the primary report evidence.

- [ ] **Step 5: Implement deterministic case-local plots**

Use `review_start_bag_time_s` and `review_end_bag_time_s` when present; otherwise use `[start_bag_time_s - 2.0, end_bag_time_s + 2.0]` clipped to `[0, run_duration]`.

Rules:

- trajectory plot: baseline plus case algorithm local XY crop;
- motion plot: 10 Hz `delta_position_m`, `delta_yaw_deg`, `speed_mps`;
- resources plot: clock-aligned CPU/RSS from resource CSV bag times;
- raw/world pointcloud: nearest indexed frame to deterministic window midpoint, same scan for every projection;
- world selected/baseline: Plan A shared projection math, medium LOD by default.

Set fixed figure size, DPI, labels, and Matplotlib metadata so repeated generation is visually deterministic.

- [ ] **Step 6: Re-run evidence tests and verify PASS**

- [ ] **Step 7: Commit Task 3**

```bash
git add evaluators/report_evidence.py tests/test_report_evidence.py
git commit -m "feat: generate deterministic benchmark evidence"
```

---

### Task 4: Render the offline HTML report from `report_data.json`

**Files:**
- Create: `benchmark_base/requirements-report.txt`
- Create: `benchmark_base/report_templates/report.html.j2`
- Create: `benchmark_base/report_templates/report.css`
- Create: `evaluators/report_html.py`
- Create: `tests/test_report_html.py`

**Interfaces:**
- `render_html(report_data: dict[str, object], *, bundle_root: Path, output_path: Path, language: str) -> Path`.
- HTML references only relative paths inside the freeze snapshot and works from `file://` without network access.
- Dependency pin: `Jinja2==3.1.6`.

- [ ] **Step 1: Add pinned report requirements**

`benchmark_base/requirements-report.txt`:

```text
# Frozen HTML/PDF experiment reports only.
Jinja2==3.1.6
reportlab==5.0.1
```

- [ ] **Step 2: Write failing HTML tests**

Create a small report model and one placeholder PNG. Assert the generated Chinese HTML contains `实验摘要`, `relative-to-baseline/diagnostic/non-ground-truth`, and a relative `evidence/` image path. Assert no `http://` or `https://` reference exists. Render `language="en"` and assert `Experiment Summary` appears while internal metric keys stay unchanged.

- [ ] **Step 3: Run HTML tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_report_html.py
```

- [ ] **Step 4: Implement Jinja2 autoescaped renderer**

```python
Environment(
    loader=FileSystemLoader(template_dir),
    autoescape=select_autoescape(["html", "xml"]),
)
```

Copy `report.css` to `report/report.css` and reference it relatively. Use the spec's 11-section ordering. HTML shows the complete anomaly table; detailed image cards use only `selected_case_ids` from `report_data.json`.

- [ ] **Step 5: Re-run HTML tests and verify PASS**

- [ ] **Step 6: Commit Task 4**

```bash
git add benchmark_base/requirements-report.txt benchmark_base/report_templates/report.html.j2 \
  benchmark_base/report_templates/report.css evaluators/report_html.py tests/test_report_html.py
git commit -m "feat: render offline benchmark html report"
```

---

### Task 5: Render a direct Chinese-capable PDF without shipping fonts

**Files:**
- Create: `evaluators/report_pdf.py`
- Create: `tests/test_report_pdf.py`

**Interfaces:**
- `find_cjk_font(candidates: list[Path] | None = None) -> Path`.
- `register_pdf_fonts(font_path: Path) -> dict[str, str]`.
- `render_pdf(report_data: dict[str, object], *, bundle_root: Path, output_path: Path, language: str, font_path: Path | None = None) -> Path`.
- Uses `reportlab==5.0.1`.

- [ ] **Step 1: Write failing font-discovery tests**

```python
from pathlib import Path
import pytest
from report_pdf import find_cjk_font


def test_find_cjk_font_returns_first_existing_candidate(tmp_path):
    missing = tmp_path / "missing.ttc"
    existing = tmp_path / "NotoSansCJK-Regular.ttc"
    existing.write_bytes(b"test-only-placeholder")
    assert find_cjk_font([missing, existing]) == existing


def test_find_cjk_font_error_has_ubuntu_install_hint(tmp_path):
    with pytest.raises(RuntimeError, match="fonts-noto-cjk"):
        find_cjk_font([tmp_path / "missing.ttc"])
```

The placeholder file is used only to test path selection; no ReportLab font registration is attempted with it.

- [ ] **Step 2: Write a PDF renderer smoke test without bundling a font**

For `language="en"`, render a one-page synthetic report with built-in Helvetica and assert the output starts with `%PDF-` and is larger than 1 KiB. Separately monkeypatch `find_cjk_font` and `register_pdf_fonts` in the Chinese renderer test so unit tests verify control flow without storing a real CJK font in the repository.

- [ ] **Step 3: Run PDF tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_report_pdf.py
```

- [ ] **Step 4: Implement deterministic system-font discovery**

Probe in order:

```text
/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf
/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc
```

If Chinese output is requested and none exist, raise:

```text
Chinese PDF requires a local CJK font. On Ubuntu install: sudo apt install fonts-noto-cjk
```

English may use ReportLab built-in fonts.

- [ ] **Step 5: Implement the 11-section direct PDF**

Use ReportLab Platypus `SimpleDocTemplate`, `Paragraph`, `Table`, `Image`, and `PageBreak`. Read no benchmark files in the renderer. Every value, conclusion, case choice, and evidence path comes from `report_data` and the freeze bundle. Put the no-GT diagnostic disclaimer near the summary and again in the methodology/footer area.

- [ ] **Step 6: Re-run PDF tests and verify PASS**

- [ ] **Step 7: Commit Task 5**

```bash
git add evaluators/report_pdf.py tests/test_report_pdf.py
git commit -m "feat: render frozen benchmark pdf report"
```

---

### Task 6: Orchestrate `lio-benchmark freeze`, provenance manifest, RRD, and atomic completion

**Files:**
- Modify: `evaluators/freeze_experiment.py`
- Modify: `tests/test_freeze_experiment.py`
- Modify: `benchmark_base/lio_benchmark/entry.py`
- Modify: `benchmark_base/lio_benchmark/postprocess.py`
- Modify: `tests/test_entry.py`
- Modify: `tests/test_postprocess.py`

**Interfaces:**

```text
lio-benchmark freeze \
  --run <RUN> \
  --baseline fast_livo2 \
  --lang zh-CN|en \
  [--html] [--pdf] \
  [--max-cases 6]
```

When neither `--html` nor `--pdf` is supplied, both are enabled. `freeze_experiment(run: Path, baseline: str, language: str, html: bool, pdf: bool, max_cases: int) -> Path` returns only the final completed snapshot path.

- [ ] **Step 1: Write failing CLI dispatch tests**

Assert `entry.main(["freeze", "--run", str(tmp_path), "--baseline", "fast_livo2", "--lang", "zh-CN", "--dry-run"])` dispatches `freeze_html=True`, `freeze_pdf=True`, `freeze_max_cases=6`. Add a second test with explicit `--html` and assert `freeze_html=True`, `freeze_pdf=False`.

- [ ] **Step 2: Write failing orchestration-order/failure tests**

Monkeypatch heavy functions with call-recording stubs and assert this order:

```text
create workspace
inventory/hash required sources
build report data
generate evidence
save experiment RRD
render HTML
render PDF
write complete freeze manifest
finalize atomically
```

Make the PDF stub raise `RuntimeError("pdf failed")`; assert the final snapshot path does not exist and `.snapshot.incomplete/freeze_status.json` contains `INCOMPLETE`.

- [ ] **Step 3: Run orchestration tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q \
  tests/test_freeze_experiment.py \
  tests/test_entry.py \
  tests/test_postprocess.py
```

- [ ] **Step 4: Implement required source provenance inventory**

Hash when present:

```text
manifest.json
metadata/run_status.json
metrics/full_comparison.json
metrics/diagnostic_timeline.json
metrics/trajectory_discontinuity.json
metrics/pointcloud_frame_index.json
metrics/diagnostic_timeline/*.csv
metrics/diagnostic_timeline/resources/*.csv
standardized/trajectories/*.csv
figures/fast_livo2_baseline_maps/map_comparison_metrics.json
figures/fast_livo2_baseline_maps/*_map.ply
```

Also hash the dataset bag directory plus manifest-referenced algorithm config and patch files that exist. Missing required machine-readable inputs fail during preflight; missing optional figures do not.

- [ ] **Step 5: Save archived RRD through the existing native recording path**

Use deterministic frozen settings:

```text
pointcloud_mode=anomaly
point_lods=10,20,80
world_pointcloud_mode=anomaly
spawn=false
save=<incomplete>/viewer/experiment.rrd
```

Do not start the web shell during freeze.

- [ ] **Step 6: Generate report data, evidence, and requested renderers**

Write `report_data.json` with UTF-8, indentation, and stable key ordering. Render only requested formats. CLI normalization decides whether both formats are enabled before the freezer is called.

- [ ] **Step 7: Write `freeze_manifest.json` last with generated hashes**

The concrete schema starts with:

```json
{
  "schema_version": 1,
  "state": "COMPLETE",
  "source_run": "/home/yangxuan/lio_benchmark_runs/greenhouse_full623_round1_001",
  "run_id": "greenhouse_full623_round1_001",
  "freeze_timestamp_utc": "2026-08-29T08:00:00+00:00",
  "benchmark_git": {
    "branch": "feat/phase-aware-benchmark",
    "commit": "12d1e9f930207fb2c52262a4ef2d7e36688585ab",
    "dirty": false
  },
  "baseline": "fast_livo2",
  "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
  "language": "zh-CN",
  "dataset": {
    "path": "/home/yangxuan/lio_benchmark_tools/date/green-house",
    "size_bytes": 1,
    "sha256": "64-character-sha256-hex-string-is-written-at-runtime"
  },
  "source_artifacts": [],
  "generated_artifacts": []
}
```

The example `size_bytes`/hash are illustrative schema values only; implementation writes measured values. If the benchmark repo is dirty, record `dirty=true` and never imply a clean commit.

- [ ] **Step 8: Re-run orchestration/CLI tests and verify PASS**

Run the Step 3 command.

- [ ] **Step 9: Commit Task 6**

```bash
git add evaluators/freeze_experiment.py benchmark_base/lio_benchmark/entry.py \
  benchmark_base/lio_benchmark/postprocess.py tests/test_freeze_experiment.py \
  tests/test_entry.py tests/test_postprocess.py
git commit -m "feat: freeze reproducible benchmark experiment"
```

---

### Task 7: Add full validation/docs and freeze greenhouse Round1

**Files:**
- Modify: `evaluators/check_phase_pipeline.sh`
- Modify: `benchmark_base/docs/RERUN_DIAGNOSTIC_VIEWER.md`
- Create: `benchmark_base/docs/FROZEN_EXPERIMENT_REPORT.md`

- [ ] **Step 1: Add report modules/tests to the Python gate**

Compile:

```text
evaluators/report_data.py
evaluators/report_evidence.py
evaluators/report_html.py
evaluators/report_pdf.py
evaluators/freeze_experiment.py
```

Run:

```text
tests/test_report_data.py
tests/test_report_evidence.py
tests/test_report_html.py
tests/test_report_pdf.py
tests/test_freeze_experiment.py
```

- [ ] **Step 2: Document dependency and font preflight**

```bash
source ~/lio_benchmark_tools/.venv-viewer/bin/activate
python -m pip install -r benchmark_base/requirements-report.txt
fc-match "Noto Sans CJK SC"
```

If CJK font is missing:

```bash
sudo apt install fonts-noto-cjk
```

- [ ] **Step 3: Run the complete Python gate**

```bash
cd ~/lio_benchmark_tools
source /opt/ros/humble/setup.bash
PYTHONNOUSERSITE=1 bash evaluators/check_phase_pipeline.sh
git diff --check
```

Expected: all tests PASS and `git diff --check` has no output.

- [ ] **Step 4: Install report deps into the viewer venv and run Round1 freeze**

```bash
source ~/lio_benchmark_tools/.venv-viewer/bin/activate
python -m pip install -r benchmark_base/requirements-report.txt
source /opt/ros/humble/setup.bash
source /home/yangxuan/agt_navigation_v2/install/setup.bash
source /home/yangxuan/lio_benchmark_algorithms/adapter_ws/install/setup.bash
RUN=/home/yangxuan/lio_benchmark_runs/greenhouse_full623_round1_001

benchmark_base/bin/lio-benchmark freeze \
  --run "$RUN" \
  --baseline fast_livo2 \
  --lang zh-CN \
  --html \
  --pdf \
  --max-cases 6
```

Expected: exit zero and one new final `<RUN>/frozen/<snapshot>` path.

- [ ] **Step 5: Validate frozen directory structure**

```bash
SNAPSHOT=$(find "$RUN/frozen" -mindepth 1 -maxdepth 1 -type d ! -name '.*' | sort | tail -1)
find "$SNAPSHOT" -maxdepth 3 -type f | sort
```

Required:

```text
freeze_manifest.json
report_data.json
report/index.html
report/report.css
report/report.pdf
viewer/experiment.rrd
```

plus evidence images under `evidence/`.

- [ ] **Step 6: Validate frozen semantic invariants**

```bash
python3 - "$SNAPSHOT" <<'PY'
import json
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "freeze_manifest.json").read_text(encoding="utf-8"))
data = json.loads((root / "report_data.json").read_text(encoding="utf-8"))
assert manifest["state"] == "COMPLETE"
assert manifest["metric_class"] == "relative-to-baseline/diagnostic/non-ground-truth"
assert data["metric_class"] == manifest["metric_class"]
assert data["baseline"] == "fast_livo2"
assert len(data["selected_case_ids"]) <= 6
print("semantic freeze checks: PASS")
PY
```

- [ ] **Step 7: Inspect HTML/PDF manually**

```bash
xdg-open "$SNAPSHOT/report/index.html"
xdg-open "$SNAPSHOT/report/report.pdf"
```

Acceptance checklist:

- Chinese headings render correctly in both formats;
- trajectory/map/resource/diagnostic images are present;
- selected detailed cases cover position/yaw/crash evidence when those categories exist;
- GLIM `353-354 s` is present in the full HTML anomaly table even if deterministic top-6 rules choose other detailed cases;
- wording says baseline-relative diagnostic/non-ground-truth and never calls FAST-LIVO2 ground truth;
- DLIO runtime failure is excluded from healthy whole-run recommendation;
- reconstructed maps are described as comparison visualizations rather than native algorithm maps.

- [ ] **Step 8: Verify no-overwrite behavior**

Before running freeze a second time, save:

```bash
FIRST_MANIFEST_SHA=$(sha256sum "$SNAPSHOT/freeze_manifest.json" | awk '{print $1}')
```

Run the same freeze command again. It must create a different timestamped snapshot. Then verify:

```bash
test "$FIRST_MANIFEST_SHA" = "$(sha256sum "$SNAPSHOT/freeze_manifest.json" | awk '{print $1}')"
```

- [ ] **Step 9: Commit docs/gate after real-host acceptance**

```bash
git add evaluators/check_phase_pipeline.sh benchmark_base/docs/RERUN_DIAGNOSTIC_VIEWER.md \
  benchmark_base/docs/FROZEN_EXPERIMENT_REPORT.md
git commit -m "docs: validate frozen benchmark reports"
```

---

## Plan B Completion Gate

The freeze/report feature is complete only when:

- Plan A completion gate is green.
- All Python phase/comparison/viewer/report tests pass on the Ubuntu benchmark host.
- `lio-benchmark freeze` succeeds for greenhouse Round1 and creates a unique final snapshot.
- `freeze_manifest.json` records source/generated SHA-256 provenance including source-bag hash without copying the full bag.
- `report_data.json` is the shared semantic source for both renderers.
- HTML opens offline using local evidence only.
- PDF renders Chinese with a local system CJK font and no repository font asset.
- The RRD opens independently with the pinned Rerun version.
- Re-running freeze does not mutate the first snapshot.
- No report statement upgrades baseline-relative diagnostics into absolute accuracy claims.
