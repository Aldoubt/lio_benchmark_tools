# Diagnostic Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `lio-benchmark bundle --run <RUN_DIR>` to create one portable diagnostic `.tar.gz` containing small benchmark evidence, generated bundle metadata, and optional reports/figures without modifying existing run artifacts.

**Architecture:** Put all archive selection, exclusion, summary generation, Git provenance capture, and tar creation in a ROS-independent `benchmark_base.lib.diagnostic_bundle` module. Keep `benchmark_base/bin/lio-benchmark` responsible only for parsing `bundle` arguments, resolving the run, calling the library, and printing the resulting archive path. Generated bundle metadata is written directly into the tar stream as in-memory members so the only filesystem mutation is the final archive.

**Tech Stack:** Python 3.10 standard library (`pathlib`, `json`, `tarfile`, `io`, `subprocess`, `datetime`, `fnmatch`), existing unittest suite, existing `lio-benchmark` CLI.

## Global Constraints

- Default command: `lio-benchmark bundle --run "$RUN"`.
- Default output: `<RUN>/reports/bundles/<run_id>_diagnostic_bundle.tar.gz`.
- Default bundle excludes `raw/**`, `.db3`, `.mcap`, `.ply`, `.pcd`, build/install trees, source repositories, report HTML/Markdown, and PNG figures.
- `--include-reports` adds existing `reports/*.md`, `reports/*.html`, and `figures/*.png` only; it does not regenerate them.
- `--output <path>` overrides the archive path.
- Selected algorithms are discovered from frozen `manifest.json`; no hard-coded algorithm IDs.
- Missing optional evidence is non-fatal and recorded in archive-local `metadata/bundle/bundle_manifest.json` and `metadata/bundle/SUMMARY.txt`.
- Git provenance capture is read-only: no stash, reset, commit, or working-tree mutation.
- Generated `metadata/bundle/*` members are archive-only and are not staged in the run directory.
- Archive member names are run-relative and do not embed the run directory as a prefix.
- The archive must never include itself recursively.

---

### Task 1: Diagnostic bundle library

**Files:**
- Create: `benchmark_base/lib/diagnostic_bundle.py`
- Create: `benchmark_base/tests/test_diagnostic_bundle.py`

**Interfaces:**
- Consumes: `run: pathlib.Path`, `repository_root: pathlib.Path`, `include_reports: bool`, `output: pathlib.Path | None`.
- Produces: `create_diagnostic_bundle(run: Path, repository_root: Path, include_reports: bool = False, output: Path | None = None) -> Path`.
- Produces helper dataclass `BundleSelection(included: tuple[str, ...], missing: tuple[str, ...])` for deterministic testable file selection.

- [ ] **Step 1: Write failing tests for default selection and exclusions**

Create `benchmark_base/tests/test_diagnostic_bundle.py` with a temporary run containing:

```python
manifest = {
    "run_id": "unit_smoke_001",
    "dataset": {"dataset_id": "unit_dataset", "bag_dir": "/data/unit"},
    "algorithms": {"algo_a": {}, "algo_b": {}},
}
```

Create small files under `metrics/`, `metadata/frame_audit/`, `metadata/runtime_provenance/`, `standardized/map_sampling/`, and `standardized/maps/<algorithm>/unified/metadata.json`. Also create excluded files under `raw/`, `standardized/maps/algo_a/unified/map.ply`, `figures/plot.png`, and `reports/report.md`.

Assertions:

```python
archive = create_diagnostic_bundle(run, repository_root=repo)
with tarfile.open(archive, "r:gz") as tf:
    names = set(tf.getnames())

self.assertIn("manifest.json", names)
self.assertIn("metrics/runtime_provenance.csv", names)
self.assertIn("standardized/maps/algo_b/unified/metadata.json", names)
self.assertNotIn("raw/algo_a/raw.db3", names)
self.assertNotIn("standardized/maps/algo_a/unified/map.ply", names)
self.assertNotIn("figures/plot.png", names)
self.assertNotIn("reports/report.md", names)
```

Also assert `metadata/bundle/SUMMARY.txt`, `metadata/bundle/bundle_manifest.json`, `metadata/bundle/benchmark_git_head.txt`, `metadata/bundle/benchmark_git_status.txt`, and `metadata/bundle/benchmark_local.patch` exist inside the archive.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_diagnostic_bundle -v
```

Expected: FAIL because `benchmark_base.lib.diagnostic_bundle` does not exist.

- [ ] **Step 3: Implement deterministic file collection and exclusions**

Implement in `benchmark_base/lib/diagnostic_bundle.py`:

```python
@dataclass(frozen=True)
class BundleSelection:
    included: tuple[str, ...]
    missing: tuple[str, ...]


def collect_bundle_files(run: Path, manifest: dict[str, Any], include_reports: bool) -> BundleSelection:
    ...
```

Required candidate set:

```text
manifest.json
RUN_STATUS.md
metrics/runtime_provenance.csv
metrics/trajectory_frame_audit.csv
metrics/smoke_diagnostics.csv
metrics/smoke_diagnostics_warmup_*.csv
metrics/pairwise_disagreement.csv
metrics/pairwise_disagreement_warmup_*.csv
metadata/frame_audit/**/*.json
metadata/runtime_provenance/**/*.json
standardized/map_sampling/metadata.json
standardized/map_sampling/selected_scans.csv
standardized/maps/<algorithm>/unified/metadata.json
```

With `include_reports=True`, additionally collect:

```text
reports/*.md
reports/*.html
figures/*.png
```

All returned paths are POSIX run-relative strings sorted lexicographically. Never traverse `raw/` or include `.db3`, `.mcap`, `.ply`, `.pcd`.

- [ ] **Step 4: Implement Git provenance capture without mutation**

Implement:

```python
def capture_git_provenance(repository_root: Path) -> dict[str, str]:
    ...
```

Use only read commands:

```text
git -C <repo> rev-parse HEAD
git -C <repo> status --short
git -C <repo> diff
```

If any command is unavailable/fails, return textual `UNAVAILABLE` values rather than raising.

- [ ] **Step 5: Implement archive-local summary and manifest generation**

Implement:

```python
def build_bundle_manifest(...)->dict[str, Any]: ...
def build_summary(...)->str: ...
```

`bundle_manifest.json` schema:

```json
{
  "schema": "lio_benchmark_diagnostic_bundle/v1",
  "run_id": "unit_smoke_001",
  "created_at": "...",
  "include_reports": false,
  "archive_name": "unit_smoke_001_diagnostic_bundle.tar.gz",
  "included": [],
  "missing": [],
  "excluded_large_artifacts": ["raw/**", "**/*.db3", "**/*.mcap", "**/*.ply", "**/*.pcd"]
}
```

The final `included` list must contain both physical run files and generated `metadata/bundle/*` members.

`SUMMARY.txt` must describe only evidence that exists. For missing runtime provenance/frame audit/map metadata, write `UNAVAILABLE` rather than synthesizing PASS/FAIL.

- [ ] **Step 6: Implement tar creation with in-memory generated members**

Implement:

```python
def create_diagnostic_bundle(
    run: Path,
    repository_root: Path,
    include_reports: bool = False,
    output: Path | None = None,
) -> Path:
    ...
```

Behavior:

1. resolve and validate `run/manifest.json` as JSON object
2. derive default output under `run/reports/bundles/`
3. collect physical run-relative files
4. compute Git provenance, bundle manifest, and summary in memory
5. create parent directory for output
6. write physical files to `tarfile.open(output, "w:gz")` using `arcname=<run-relative>`
7. add generated text/JSON via `TarInfo` + `io.BytesIO`
8. ensure the output archive path itself is never among selected physical files
9. return the output path

The implementation may replace an existing output archive but must not write any other staging file.

- [ ] **Step 7: Add tests for optional reports, missing evidence, algorithm discovery, archive self-exclusion, and no staging mutation**

Add assertions that:

```python
archive = create_diagnostic_bundle(run, repo, include_reports=True)
```

includes report/PNG files, while default mode does not.

Use an algorithm named `unexpected_algo_name` in manifest and verify its map metadata is collected to prove the implementation is not hard-coded.

Delete an optional audit file and verify bundling succeeds and `bundle_manifest.json["missing"]` lists its run-relative path.

Set `output=run / "reports/bundles/custom.tar.gz"`, run twice, and verify `custom.tar.gz` is not a member of itself.

Snapshot the run tree before/after excluding the final archive and verify no `metadata/bundle/` directory is created on disk.

- [ ] **Step 8: Run Task 1 tests GREEN**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_diagnostic_bundle -v
```

Expected: all tests PASS.

- [ ] **Step 9: Commit Task 1**

```bash
git add benchmark_base/lib/diagnostic_bundle.py benchmark_base/tests/test_diagnostic_bundle.py
git commit -m "feat: add diagnostic bundle archive library"
```

---

### Task 2: Main CLI integration

**Files:**
- Modify: `benchmark_base/bin/lio-benchmark`
- Modify: `benchmark_base/tests/test_cli_manifest.py`

**Interfaces:**
- Consumes: `create_diagnostic_bundle(...)` from Task 1.
- Produces CLI: `lio-benchmark bundle --run PATH [--include-reports] [--output PATH]`.

- [ ] **Step 1: Write failing CLI help test**

Add to `benchmark_base/tests/test_cli_manifest.py`:

```python
def test_bundle_cli_exposes_diagnostic_archive_options(self) -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "benchmark_base/bin/lio-benchmark"), "bundle", "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    self.assertEqual(0, result.returncode, result.stderr)
    self.assertIn("--run", result.stdout)
    self.assertIn("--include-reports", result.stdout)
    self.assertIn("--output", result.stdout)
```

- [ ] **Step 2: Run CLI test to verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_cli_manifest.ManifestTest.test_bundle_cli_exposes_diagnostic_archive_options -v
```

Expected: FAIL because `bundle` is not a recognized subcommand.

- [ ] **Step 3: Add CLI handler and parser**

Import:

```python
from benchmark_base.lib.diagnostic_bundle import create_diagnostic_bundle
```

Add:

```python
def cmd_bundle(args: argparse.Namespace) -> None:
    run, _ = resolve_run(args.run)
    archive = create_diagnostic_bundle(
        run=run,
        repository_root=MODULE_ROOT,
        include_reports=args.include_reports,
        output=args.output,
    )
    print(archive)
```

Parser:

```python
bundle = sub.add_parser("bundle")
bundle.add_argument("--run", type=Path, required=True)
bundle.add_argument("--include-reports", action="store_true")
bundle.add_argument("--output", type=Path)
bundle.set_defaults(func=cmd_bundle)
```

- [ ] **Step 4: Run CLI tests GREEN**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_cli_manifest -v
python3 -m unittest benchmark_base.tests.test_diagnostic_bundle -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add benchmark_base/bin/lio-benchmark benchmark_base/tests/test_cli_manifest.py
git commit -m "feat: expose diagnostic bundle CLI"
```

---

### Task 3: User documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/verification/green_house_trajectory_semantics_followup.md` if present; otherwise modify the current green-house verification document that contains the fixed run workflow.

**Interfaces:**
- Documents: default minimal bundle, optional reports, output path, upload workflow.

- [ ] **Step 1: Add concise README usage**

Document:

```bash
RUN=/home/yangxuan/lio_benchmark_runs/green_house/green_house_three_smoke_004
benchmark_base/bin/lio-benchmark bundle --run "$RUN"
```

Expected output:

```text
$RUN/reports/bundles/green_house_three_smoke_004_diagnostic_bundle.tar.gz
```

Optional:

```bash
benchmark_base/bin/lio-benchmark bundle --run "$RUN" --include-reports
```

State explicitly that raw bags and point-cloud binaries are excluded.

- [ ] **Step 2: Add the bundle command as the final step of the green-house diagnostic workflow**

Document that after audit/standardization/reporting, the reviewer only needs the generated bundle rather than terminal transcript fragments.

- [ ] **Step 3: Run complete verification**

Run:

```bash
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators reporting visualization
bash -n evaluators/*.sh
python3 benchmark_base/bin/lio-benchmark list algorithms >/dev/null
python3 benchmark_base/bin/lio-benchmark bundle --help
```

Expected: zero test failures, compileall exit 0, shell syntax exit 0, registry smoke exit 0, bundle help exit 0.

- [ ] **Step 4: Inspect diff for scope and forbidden additions**

Run:

```bash
git diff --check
git status --short
```

Confirm no raw artifacts, archive files, generated bundles, or unrelated local-run data were committed.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md docs/verification benchmark_base
# Add only the intended docs/code already reviewed
git commit -m "docs: document diagnostic bundle workflow"
```
