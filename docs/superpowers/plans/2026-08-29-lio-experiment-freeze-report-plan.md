# LIO Experiment Freeze + HTML/PDF Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an immutable `lio-benchmark freeze` workflow that records experiment provenance, generates deterministic evidence images, writes one shared `report_data.json`, and renders both an offline HTML archive and a direct PDF snapshot for a completed benchmark run.

**Architecture:** Treat the selected run as immutable input. Build the report model by reusing `current_run_report.build_report()` plus frozen diagnostic/map/resource artifacts, generate deterministic static evidence (including anomaly-local raw/world LiDAR using Plan A's shared projection module), then render HTML and PDF from the same model. Build the snapshot in an `.incomplete` directory, hash source/generated artifacts with SHA-256, and atomically rename to the final unique snapshot directory only when every requested output succeeds.

**Tech Stack:** Python 3.10, existing NumPy/SciPy/Matplotlib stack, ROS 2 Humble for indexed Livox message deserialization used by anomaly evidence, `Jinja2==3.1.6`, `reportlab==5.0.1`, existing `rerun-sdk==0.36.3` for the archived `.rrd` recording.

**Spec:** `docs/superpowers/specs/2026-08-29-lio-diagnostic-viewer-freeze-design.md`

**Dependency:** Plan A `docs/superpowers/plans/2026-08-29-lio-diagnostic-viewer-interaction-plan.md` must pass its completion gate first. This plan imports `viewer_i18n.py` and `viewer_projection.py` rather than creating alternate translations or projection math.

## Global Constraints

- `report_data.json` is the only semantic source for HTML and PDF; the renderers do not independently recalculate benchmark conclusions.
- Reuse `current_run_report.build_report()` for current-run comparison semantics instead of copying recommendation/health logic.
- When no independent GT exists, all baseline-relative trajectory/map quantities remain `relative-to-baseline/diagnostic/non-ground-truth`.
- Never describe FAST-LIVO2 as ground truth.
- Never describe reconstructed comparison PLY as an algorithm-native map unless the source artifact actually is native-map output.
- Freeze never overwrites an existing final snapshot directory.
- The full rosbag and large PLY files are not copied by default; their paths, sizes, and SHA-256 hashes are recorded.
- All requested outputs are success-or-error. A failed PDF must produce non-zero exit and must not leave a final directory that looks complete.
- Evidence figures are deterministic Matplotlib/static assets; reports do not rely on screenshots of the interactive Viewer.
- PDF uses local system CJK fonts only. No font binary is committed, copied into the freeze bundle, or shared.
- Default language is `zh-CN`; internal schema keys remain English.
- Freeze must not replay the rosbag or launch any LIO algorithm. It may deserialize indexed LiDAR messages directly from the source sqlite bag.

---

## File Structure

**Create**

- `benchmark_base/requirements-report.txt` — pinned Jinja2/ReportLab dependencies.
- `evaluators/report_data.py` — one report-data model, anomaly-case selection, current-run conclusions/disclaimer assembly.
- `evaluators/report_evidence.py` — existing-figure collection plus deterministic anomaly-local static evidence plots.
- `evaluators/report_html.py` — Jinja2 offline HTML renderer.
- `evaluators/report_pdf.py` — direct ReportLab PDF renderer and CJK font discovery.
- `evaluators/freeze_experiment.py` — snapshot identity, provenance hashing, orchestration, incomplete/final lifecycle.
- `benchmark_base/report_templates/report.html.j2`
- `benchmark_base/report_templates/report.css`
- `tests/test_report_data.py`
- `tests/test_report_evidence.py`
- `tests/test_report_html.py`
- `tests/test_report_pdf.py`
- `tests/test_freeze_experiment.py`

**Modify**

- `benchmark_base/lio_benchmark/entry.py` — add `freeze` command.
- `benchmark_base/lio_benchmark/postprocess.py` — build/execute `freeze_experiment.py` command.
- `tests/test_entry.py`
- `tests/test_postprocess.py`
- `evaluators/check_phase_pipeline.sh`
- `benchmark_base/docs/RERUN_DIAGNOSTIC_VIEWER.md` — link the interactive viewer to the freeze/report workflow.
- Add `benchmark_base/docs/FROZEN_EXPERIMENT_REPORT.md` if the freeze workflow needs a standalone operational guide.

---

### Task 1: Define the freeze identity, hashing primitives, and incomplete/final lifecycle

**Files:**
- Create: `evaluators/freeze_experiment.py`
- Create: `tests/test_freeze_experiment.py`

**Interfaces:**
- `sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str`.
- `sha256_path(path: Path) -> dict[str, Any]`; file result includes `kind=file,path,size_bytes,sha256`; directory result includes deterministic child entries and a digest over relative path + size + content digest.
- `benchmark_git_identity(repo_root: Path) -> dict[str, str]` returns `branch`, `commit`, `short_commit`, `dirty`.
- `build_snapshot_name(run_id: str, timestamp_utc: datetime, short_sha: str) -> str` with UTC format `YYYYmmddTHHMMSSZ`.
- `FreezeWorkspace.create(run: Path, snapshot_name: str) -> FreezeWorkspace` creates only `<RUN>/frozen/.<snapshot>.incomplete` and refuses conflicts.
- `FreezeWorkspace.finalize() -> Path` atomically renames the incomplete directory to `<RUN>/frozen/<snapshot>`.
- `FreezeWorkspace.mark_failed(error: str) -> None` writes `freeze_status.json` with `state=INCOMPLETE` and leaves only the dot-prefixed incomplete directory.

- [ ] **Step 1: Write failing hashing/lifecycle tests**

Tests must include:

```python
def test_sha256_file_is_content_sensitive_and_chunked(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == hashlib.sha256(b"abc").hexdigest()


def test_snapshot_name_is_deterministic():
    stamp = datetime(2026, 8, 29, 8, 0, 0, tzinfo=timezone.utc)
    assert build_snapshot_name("greenhouse_round1", stamp, "12d1e9f") == "greenhouse_round1_20260829T080000Z_12d1e9f"


def test_freeze_workspace_never_overwrites_final_snapshot(tmp_path):
    ...
    final.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        FreezeWorkspace.create(run, snapshot_name)
```

Add a failure test that asserts the final directory does not exist after `mark_failed()`.

- [ ] **Step 2: Run the freeze lifecycle tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_freeze_experiment.py
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement streaming SHA-256 and workspace lifecycle**

Directory hashing must sort children by POSIX relative path before combining them. Do not load the bag into RAM. File hashing loop:

```python
with path.open("rb") as stream:
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
```

Use `Path.replace()`/`os.replace()` only when finalizing within the same run filesystem.

- [ ] **Step 4: Run lifecycle tests**

Expected: PASS.

- [ ] **Step 5: Commit hashing/workspace primitives**

```bash
git add evaluators/freeze_experiment.py tests/test_freeze_experiment.py
git commit -m "feat: add immutable freeze workspace"
```

---

### Task 2: Build the single report-data model and deterministic case selection

**Files:**
- Create: `evaluators/report_data.py`
- Create: `tests/test_report_data.py`
- Modify: `tests/test_current_run_report.py` only if a tiny public helper is required; do not duplicate report semantics.

**Interfaces:**
- `select_anomaly_cases(windows: list[dict], run_status: dict, *, max_cases: int = 6) -> list[str]` returns ordered `window_id`s.
- `build_report_data(run: Path, *, baseline: str, language: str, max_cases: int = 6) -> dict[str, Any]`.
- Output schema version starts at `1` and includes `metric_class`, `no_ground_truth`, `experiment`, `dataset`, `algorithms`, `health`, `trajectory`, `maps`, `resources`, `anomalies`, `selected_case_ids`, `conclusions`, `reproducibility`, and `disclaimer`.
- Conclusions are derived from the existing `current_run_report.build_report()` recommendations plus actual anomaly evidence; they are stored as stable semantic keys + localized display strings, not renderer-specific prose.

- [ ] **Step 1: Write failing anomaly-selection tests**

Construct windows where the top severities are all position jumps and lower-ranked windows contain yaw/crash evidence. Assert the bounded selector covers required categories:

```python
def test_case_selection_covers_position_yaw_and_crash_without_duplicates():
    ids = select_anomaly_cases(windows, run_status, max_cases=6)
    assert len(ids) <= 6
    assert len(ids) == len(set(ids))
    selected = {w["window_id"]: w for w in windows if w["window_id"] in ids}
    assert any("position_jump" in w["types"] for w in selected.values())
    assert any("yaw_jump" in w["types"] for w in selected.values())
    assert any(w["algorithm"] == "dlio" for w in selected.values())
```

- [ ] **Step 2: Write failing report semantic tests**

Use a minimal temporary run fixture and monkeypatch `current_run_report.build_report` with a known current-run model. Assert:

```python
assert data["metric_class"] == "relative-to-baseline/diagnostic/non-ground-truth"
assert data["no_ground_truth"] is True
assert "ground truth" not in " ".join(data["conclusions"]).lower()
assert data["baseline"] == "fast_livo2"
```

Also assert machine anomaly types remain `position_jump`/`yaw_jump` while localized labels use `viewer_i18n`.

- [ ] **Step 3: Run report-data tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_report_data.py
```

Expected: FAIL because `report_data.py` does not exist.

- [ ] **Step 4: Implement report-data assembly by composition**

Import and call:

```python
from current_run_report import build_report as build_current_run_report
from viewer_i18n import tr, translate_anomaly_types
```

Do not recompute whole-run RMSE/P95/recommendation logic inside `report_data.py`. Read `diagnostic_timeline.json`, `pointcloud_frame_index.json`, `manifest.json`, and `run_status.json` only for fields not already represented by the current-run report model.

- [ ] **Step 5: Implement conclusions as evidence-limited statements**

Examples of allowed conclusion generation rules:

```python
if recommendations.get("closest_to_baseline"):
    conclusions.append({
        "kind": "closest_to_baseline",
        "algorithm": recommendations["closest_to_baseline"],
        "metric_class": METRIC_CLASS,
    })
```

For anomalies, store window IDs/times/severity rather than freehand interpretation. The renderers localize the display text.

- [ ] **Step 6: Run report-data and current-run report tests**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q \
  tests/test_report_data.py \
  tests/test_current_run_report.py \
  tests/test_current_run_diagnostics.py
```

Expected: PASS.

- [ ] **Step 7: Commit the report-data model**

```bash
git add evaluators/report_data.py tests/test_report_data.py
git commit -m "feat: add frozen report data model"
```

---

### Task 3: Generate deterministic evidence images, including anomaly-local raw/world LiDAR

**Files:**
- Create: `evaluators/report_evidence.py`
- Create: `tests/test_report_evidence.py`

**Interfaces:**
- `collect_existing_figures(run: Path, output_root: Path) -> list[dict[str, Any]]` copies only report figures into the freeze evidence tree and records source/destination metadata.
- `generate_case_evidence(run: Path, case: dict, *, baseline: str, output_dir: Path, point_step: int = 20) -> dict[str, str]`.
- Each selected case can produce: `trajectory.png`, `motion.png`, `resources.png`, `raw_lidar.png`, `world_selected.png`, and when selected algorithm differs from baseline, `world_baseline.png`.
- Reuse Plan A `viewer_projection.IndexedLidarScan` and projection helpers.

- [ ] **Step 1: Write failing existing-figure collection test**

Build a temporary run containing only two known figures and assert only present files are copied to deterministic category paths:

```python
items = collect_existing_figures(run, out)
assert {Path(i["destination"]).name for i in items} == {"position_step_10hz.png", "cpu_aligned.png"}
```

Missing optional figures must be recorded as unavailable in report data, not fabricated.

- [ ] **Step 2: Write failing deterministic case-plot tests**

Monkeypatch indexed-scan loading with a tiny scan and create a tiny standardized trajectory. Generate one case twice into separate directories and compare decoded image dimensions plus a deterministic data summary returned by the function. Do not require PNG byte-for-byte equality because Matplotlib metadata may vary unless explicitly fixed.

Assert world projection calls the shared helper; a monkeypatch on `report_evidence.project_points_to_display_world` must observe per-point times.

- [ ] **Step 3: Run evidence tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_report_evidence.py
```

Expected: FAIL because `report_evidence.py` does not exist.

- [ ] **Step 4: Implement existing-figure collection**

Recognize exactly these current-run paths when present:

```text
figures/comparison_dashboard.png
figures/diagnostic_timeline/position_step_10hz.png
figures/diagnostic_timeline/yaw_step_10hz.png
figures/diagnostic_timeline/cpu_aligned.png
figures/diagnostic_timeline/rss_aligned.png
figures/fast_livo2_baseline_maps/map_comparison_xy.png
figures/fast_livo2_baseline_maps/map_comparison_xz.png
```

If the actual dashboard filename differs in the repository, use the existing generated filename discovered by tests/current outputs and update this exact list before committing. Do not glob unrelated stale historical figures into the report.

- [ ] **Step 5: Implement case-local plots**

Use a fixed review crop of the window's existing `review_start_bag_time_s`/`review_end_bag_time_s` when available; otherwise use `[start-2 s, end+2 s]` clipped to run coverage.

Rules:

- trajectory plot: baseline + case algorithm local XY crop and current-window markers;
- motion plot: 10 Hz `delta_position_m`, `delta_yaw_deg`, `speed_mps`;
- resources plot: clock-aligned CPU and RSS using existing resource CSV bag times;
- raw/world pointcloud: nearest indexed frame to deterministic window midpoint, same scan for all projections;
- world selected/baseline: use exactly Plan A shared projection math and medium LOD by default.

Use fixed figure sizes/DPI and explicit titles from `viewer_i18n` so HTML and PDF receive the same image files.

- [ ] **Step 6: Run evidence tests**

Expected: PASS.

- [ ] **Step 7: Commit deterministic evidence generation**

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
- `render_html(report_data: dict[str, Any], *, bundle_root: Path, output_path: Path, language: str) -> Path`.
- HTML references only relative paths inside the freeze snapshot and works from `file://` without network access.
- Dependency pin: `Jinja2==3.1.6`.

- [ ] **Step 1: Add the pinned report requirements**

`benchmark_base/requirements-report.txt`:

```text
# Frozen HTML/PDF experiment reports only.
Jinja2==3.1.6
reportlab==5.0.1
```

- [ ] **Step 2: Write failing HTML render tests**

Create one tiny report model and one placeholder PNG. Assert:

```python
html = output.read_text(encoding="utf-8")
assert "实验摘要" in html
assert "relative-to-baseline/diagnostic/non-ground-truth" in html
assert "https://" not in html
assert "http://" not in html
assert "evidence/" in html
```

Also render `language="en"` and assert the English headings exist without changing schema content.

- [ ] **Step 3: Run HTML tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_report_html.py
```

Expected: FAIL because renderer/template do not exist.

- [ ] **Step 4: Implement Jinja2 environment with autoescape**

Use:

```python
Environment(
    loader=FileSystemLoader(template_dir),
    autoescape=select_autoescape(["html", "xml"]),
)
```

Copy `report.css` into `report/report.css` and reference it relatively. Use the spec's 11-section ordering exactly. HTML may show the complete anomaly table, while detailed image cards use the bounded selected cases recorded in `report_data.json`.

- [ ] **Step 5: Run HTML tests**

Expected: PASS.

- [ ] **Step 6: Commit HTML report support**

```bash
git add \
  benchmark_base/requirements-report.txt \
  benchmark_base/report_templates/report.html.j2 \
  benchmark_base/report_templates/report.css \
  evaluators/report_html.py \
  tests/test_report_html.py
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
- `render_pdf(report_data: dict[str, Any], *, bundle_root: Path, output_path: Path, language: str, font_path: Path | None = None) -> Path`.
- Uses `reportlab==5.0.1`.

- [ ] **Step 1: Write failing font-discovery tests using temporary fake candidate paths**

Do not depend on the CI machine actually having Noto CJK. Test the selection policy with temp files:

```python
def test_find_cjk_font_returns_first_existing_candidate(tmp_path):
    first = tmp_path / "missing.ttc"
    second = tmp_path / "NotoSansCJK-Regular.ttc"
    second.write_bytes(b"placeholder")
    assert find_cjk_font([first, second]) == second
```

Add a test that no candidates raises a `RuntimeError` containing an Ubuntu installation hint such as `fonts-noto-cjk`.

- [ ] **Step 2: Write a PDF smoke test with a known test font injection**

The test may monkeypatch `register_pdf_fonts` so unit tests do not package/share a real font. Render a one-page synthetic report and assert the PDF starts with `%PDF-` and has non-trivial size.

- [ ] **Step 3: Run PDF tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q tests/test_report_pdf.py
```

Expected: FAIL because the renderer does not exist.

- [ ] **Step 4: Implement system font discovery policy**

Probe common Ubuntu paths in deterministic order, including:

```text
/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf
/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc
```

If none exist for `zh-CN`, raise with:

```text
Chinese PDF requires a local CJK font. On Ubuntu install: sudo apt install fonts-noto-cjk
```

For `en`, ReportLab built-in fonts may be used without CJK discovery.

- [ ] **Step 5: Implement the 11-section PDF with shared data/evidence**

Use ReportLab Platypus `SimpleDocTemplate`, `Paragraph`, `Table`, `Image`, `PageBreak`, and registered CJK font styles. Do not re-read benchmark metrics in the renderer. Every metric value and case selection comes from `report_data`.

Include the diagnostic/no-GT disclaimer near the report summary and again in the methodology/footnote area.

- [ ] **Step 6: Run PDF tests**

Expected: PASS.

- [ ] **Step 7: Commit PDF support**

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
- CLI:

```text
lio-benchmark freeze \
  --run <RUN> \
  --baseline fast_livo2 \
  --lang zh-CN|en \
  [--html] [--pdf] \
  [--max-cases 6]
```

When neither `--html` nor `--pdf` is supplied, both are `True`.

- `freeze_experiment(run, baseline, language, html, pdf, max_cases) -> Path` returns the final snapshot directory only after successful finalization.

- [ ] **Step 1: Write failing CLI dispatch tests**

Assert:

```python
entry.main(["freeze", "--run", str(tmp_path), "--baseline", "fast_livo2", "--lang", "zh-CN", "--dry-run"])
```

passes `freeze_html=True`, `freeze_pdf=True`, `freeze_max_cases=6` to `execute_stage`. Add an explicit `--html` only case where PDF is false.

- [ ] **Step 2: Write failing orchestration test with stub renderers**

Monkeypatch heavy functions so the test can verify order:

```text
create workspace
hash required sources
build report_data
generate evidence
save experiment.rrd
render HTML
render PDF
write final freeze_manifest.json
finalize atomically
```

Assert a renderer exception leaves only `.snapshot.incomplete/freeze_status.json` with `state=INCOMPLETE` and no final snapshot.

- [ ] **Step 3: Run orchestration tests and verify failure**

```bash
PYTHONNOUSERSITE=1 python3 -m pytest -q \
  tests/test_freeze_experiment.py \
  tests/test_entry.py \
  tests/test_postprocess.py
```

Expected: FAIL until freeze CLI/orchestration is implemented.

- [ ] **Step 4: Implement source provenance inventory before report generation**

Required source inventory must include when present:

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
figures/fast_livo2_baseline_maps/*.ply
```

Also hash the dataset bag directory and manifest-referenced algorithm config/patch files that exist. Missing required files produce a preflight error before rendering; optional figures remain optional.

- [ ] **Step 5: Generate the archived RRD through the existing viewer path**

Invoke the native viewer recording builder or subprocess with deterministic frozen settings:

```text
pointcloud mode = anomaly
point LODs = 10,20,80
world pointcloud mode = anomaly
no spawn = true
save = <incomplete>/viewer/experiment.rrd
```

Do not start a web server during freeze.

- [ ] **Step 6: Generate `report_data.json`, evidence, HTML, and PDF**

Write JSON with `sort_keys=True`, UTF-8, and indentation. Render only requested formats. If both flags are absent at CLI parse time, normalize them to both enabled before calling the freezer.

- [ ] **Step 7: Write `freeze_manifest.json` last, including generated hashes**

The manifest must include:

```json
{
  "schema_version": 1,
  "state": "COMPLETE",
  "source_run": "...",
  "run_id": "...",
  "freeze_timestamp_utc": "...",
  "benchmark_git": {"branch": "...", "commit": "...", "dirty": false},
  "baseline": "fast_livo2",
  "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
  "language": "zh-CN",
  "dataset": {"path": "...", "size_bytes": 0, "sha256": "..."},
  "source_artifacts": [],
  "generated_artifacts": []
}
```

If the benchmark repo is dirty, record `dirty=true`; do not silently pretend the snapshot came from a clean commit.

- [ ] **Step 8: Run orchestration/CLI tests**

Run the Step 3 command.

Expected: PASS.

- [ ] **Step 9: Commit freeze orchestration**

```bash
git add \
  evaluators/freeze_experiment.py \
  benchmark_base/lio_benchmark/entry.py \
  benchmark_base/lio_benchmark/postprocess.py \
  tests/test_freeze_experiment.py \
  tests/test_entry.py \
  tests/test_postprocess.py
git commit -m "feat: freeze reproducible benchmark experiment"
```

---

### Task 7: Add full validation, documentation, and freeze the greenhouse Round1 result

**Files:**
- Modify: `evaluators/check_phase_pipeline.sh`
- Modify: `benchmark_base/docs/RERUN_DIAGNOSTIC_VIEWER.md`
- Create: `benchmark_base/docs/FROZEN_EXPERIMENT_REPORT.md`

**Interfaces:**
- Python self-test covers report data/evidence/renderers/freezer.
- Report dependency install command is explicit and separate from core benchmark dependencies.

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

Exact host setup:

```bash
source ~/lio_benchmark_tools/.venv-viewer/bin/activate
python -m pip install -r benchmark_base/requirements-report.txt
fc-match "Noto Sans CJK SC"
```

If the font is missing:

```bash
sudo apt install fonts-noto-cjk
```

Do not add the font to the repository.

- [ ] **Step 3: Run the complete Python gate**

```bash
cd ~/lio_benchmark_tools
source /opt/ros/humble/setup.bash
PYTHONNOUSERSITE=1 bash evaluators/check_phase_pipeline.sh
git diff --check
```

Expected: all tests pass; no whitespace errors.

- [ ] **Step 4: Run the Round1 freeze command**

```bash
source ~/lio_benchmark_tools/.venv-viewer/bin/activate
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

Expected: command returns zero and prints one final `<RUN>/frozen/...` directory.

- [ ] **Step 5: Validate the frozen directory structurally**

```bash
SNAPSHOT=$(find "$RUN/frozen" -mindepth 1 -maxdepth 1 -type d ! -name '.*' | sort | tail -1)
find "$SNAPSHOT" -maxdepth 3 -type f | sort
```

Required files:

```text
freeze_manifest.json
report_data.json
report/index.html
report/report.css
report/report.pdf
viewer/experiment.rrd
```

and evidence images under `evidence/`.

- [ ] **Step 6: Validate semantic invariants in the frozen data**

```bash
python3 - "$SNAPSHOT" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "freeze_manifest.json").read_text())
data = json.loads((root / "report_data.json").read_text())
assert manifest["state"] == "COMPLETE"
assert manifest["metric_class"] == "relative-to-baseline/diagnostic/non-ground-truth"
assert data["metric_class"] == manifest["metric_class"]
assert data["baseline"] == "fast_livo2"
assert len(data["selected_case_ids"]) <= 6
print("semantic freeze checks: PASS")
PY
```

- [ ] **Step 7: Inspect the generated reports manually**

```bash
xdg-open "$SNAPSHOT/report/index.html"
xdg-open "$SNAPSHOT/report/report.pdf"
```

Acceptance checklist:

- Chinese headings render correctly in HTML and PDF;
- overview/comparison/map/resource images are embedded;
- selected anomaly cases include position/yaw/crash coverage when available;
- GLIM `353-354 s` appears if selected by deterministic case rules or is at minimum present in the full HTML anomaly table;
- report wording says baseline-relative diagnostic/non-ground-truth and never calls FAST-LIVO2 ground truth;
- DLIO lifecycle failure is not compared as a healthy full-run candidate;
- reconstructed maps are described as comparison visualizations, not native algorithm maps.

- [ ] **Step 8: Verify immutability/no-overwrite behavior**

Immediately run the same freeze command again. It must create a distinct timestamped snapshot; it must not modify the first final directory. Compare the first snapshot manifest hash before/after:

```bash
sha256sum "$SNAPSHOT/freeze_manifest.json"
```

The digest must remain unchanged.

- [ ] **Step 9: Commit docs/gate after real-host acceptance**

```bash
git add \
  evaluators/check_phase_pipeline.sh \
  benchmark_base/docs/RERUN_DIAGNOSTIC_VIEWER.md \
  benchmark_base/docs/FROZEN_EXPERIMENT_REPORT.md
git commit -m "docs: validate frozen benchmark reports"
```

---

## Plan B Completion Gate

The freeze/report feature is complete only when:

- Plan A completion gate is already green.
- All Python phase/comparison/viewer/report tests pass on the Ubuntu benchmark host.
- `lio-benchmark freeze` returns zero for greenhouse Round1 and creates a unique final snapshot.
- `freeze_manifest.json` records source and generated SHA-256 provenance including the source bag without copying the full bag.
- `report_data.json` is the shared semantic source for both renderers.
- HTML opens offline and contains embedded/local evidence only.
- PDF renders Chinese with a local system CJK font and no repository font asset.
- The RRD opens independently with the pinned Rerun version.
- Re-running freeze does not mutate the first snapshot.
- No report statement upgrades baseline-relative diagnostic results into absolute accuracy claims.
