# Freeze Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the internal immutable-freeze foundation: deterministic snapshot identity, source validation, SHA-256 provenance, small-artifact copying, `INCOMPLETE -> COMPLETE` lifecycle, and generated-artifact registration without exposing the final `lio-benchmark freeze` CLI before RRD/report generation exists.

**Architecture:** Add one focused `evaluators/freeze_experiment.py` module. It reads an already post-processed run, validates core diagnostic artifacts, creates a non-overwriting frozen workspace, copies small run-contained evidence under `source/`, records external large assets by path/size/hash, writes `freeze_manifest.json` atomically, and exposes registration/finalization APIs for later RRD/report plans. It never reruns algorithms, reconstructs maps, or mutates the source run.

**Tech Stack:** Python 3.10 stdlib (`pathlib`, `hashlib`, `json`, `datetime`, `subprocess`, `shutil`, `os`, `re`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-native-freeze-export-design.md`

## Global Constraints

- Native Rerun remains the formal interactive diagnosis path; WebViewer is experimental and receives no P0 implementation work.
- Existing benchmark metric, health, alignment, map, phase, and anomaly semantics must not change.
- When no independent GT is available, metric class remains exactly `relative-to-baseline/diagnostic/non-ground-truth`.
- Freeze never overwrites an existing snapshot.
- Freeze never silently reruns missing algorithms or modifies the source run.
- Core comparison/diagnostic evidence is required; optional map, phase, point-cloud-index, resource, and static-figure evidence may be absent and must be disclosed rather than synthesized.
- Failed/crashed/truncated algorithms with available standardized/diagnostic evidence remain represented; existing health policy controls recommendation eligibility.
- Do not duplicate the full rosbag or large PLY assets by default; record external path, byte size, and SHA-256.
- Do not distribute font binaries.
- This plan intentionally does **not** add `lio-benchmark freeze`; the final CLI is added only after Native `.rrd` and report generation are wired so `COMPLETE` has its final product meaning.

---

## File Structure

- Create: `evaluators/freeze_experiment.py` — freeze identity, hashing, source discovery, copy policy, manifest lifecycle.
- Create: `tests/test_freeze_experiment.py` — focused TDD coverage for all core invariants.
- No changes to `benchmark_base/lio_benchmark/entry.py` or `postprocess.py` in this plan.

---

### Task 1: Deterministic hashing, naming, and atomic JSON primitives

**Files:**
- Create: `evaluators/freeze_experiment.py`
- Create: `tests/test_freeze_experiment.py`

**Interfaces:**
- Produces: `sha256_path(path: Path) -> tuple[str, int]`
- Produces: `freeze_directory_name(run_id: str, created_at: datetime, git_short_sha: str) -> str`
- Produces: `write_json_atomic(path: Path, payload: dict[str, Any]) -> None`

- [ ] **Step 1: Write failing tests for file/directory hashing and stable naming**

```python
import datetime as dt
import hashlib
import json
from pathlib import Path

from freeze_experiment import freeze_directory_name, sha256_path, write_json_atomic


def test_sha256_path_hashes_file_bytes(tmp_path):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"abc")
    digest, size = sha256_path(path)
    assert digest == hashlib.sha256(b"abc").hexdigest()
    assert size == 3


def test_sha256_path_directory_is_sorted_and_content_sensitive(tmp_path):
    root = tmp_path / "bag"
    root.mkdir()
    (root / "b.db3").write_bytes(b"B")
    (root / "a.yaml").write_bytes(b"A")
    first, size = sha256_path(root)
    assert size == 2
    (root / "b.db3").write_bytes(b"C")
    second, _ = sha256_path(root)
    assert first != second


def test_freeze_directory_name_is_sanitized_and_deterministic():
    created = dt.datetime(2026, 8, 30, 15, 40, 5, tzinfo=dt.timezone.utc)
    assert freeze_directory_name("greenhouse/run 01", created, "abcdef12") == (
        "greenhouse_run_01_20260830T154005Z_abcdef12"
    )


def test_write_json_atomic_leaves_only_final_file(tmp_path):
    path = tmp_path / "freeze_manifest.json"
    write_json_atomic(path, {"freeze_state": "INCOMPLETE"})
    assert json.loads(path.read_text(encoding="utf-8"))["freeze_state"] == "INCOMPLETE"
    assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH="$PWD/evaluators:$PWD/benchmark_base" \
python3 -m pytest -q tests/test_freeze_experiment.py
```

Expected: collection/import failure because `freeze_experiment.py` does not exist.

- [ ] **Step 3: Implement minimal primitives**

Create `evaluators/freeze_experiment.py` with these behaviors:

```python
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

CHUNK_BYTES = 1024 * 1024


def _stream_file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def sha256_path(path: Path) -> tuple[str, int]:
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"freeze hashing does not follow symlinks: {path}")
    if path.is_file():
        return _stream_file_digest(path)
    if not path.is_dir():
        raise FileNotFoundError(path)

    digest = hashlib.sha256()
    total = 0
    files = sorted(p for p in path.rglob("*") if p.is_file())
    for item in files:
        if item.is_symlink():
            raise ValueError(f"freeze hashing does not follow symlinks: {item}")
        rel = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        with item.open("rb") as stream:
            while True:
                chunk = stream.read(CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
        digest.update(b"\0")
    return digest.hexdigest(), total


def freeze_directory_name(run_id: str, created_at: dt.datetime, git_short_sha: str) -> str:
    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    safe_run = re.sub(r"[^A-Za-z0-9._-]+", "_", str(run_id)).strip("_") or "run"
    stamp = created_at.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_sha = re.sub(r"[^0-9A-Za-z]+", "", str(git_short_sha))
    if not safe_sha:
        raise ValueError("git_short_sha must not be empty")
    return f"{safe_run}_{stamp}_{safe_sha}"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same pytest command. Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add evaluators/freeze_experiment.py tests/test_freeze_experiment.py
git commit -m "feat: add freeze hashing primitives"
```

---

### Task 2: Discover and validate required/optional source evidence

**Files:**
- Modify: `evaluators/freeze_experiment.py`
- Modify: `tests/test_freeze_experiment.py`

**Interfaces:**
- Consumes: `sha256_path(...)`
- Produces: `discover_freeze_sources(run: Path) -> dict[str, Any]`
- Returned keys: `algorithms`, `required_files`, `optional_files`, `optional_evidence`, `run_status`, `manifest`, `diagnostic_timeline`.

Core required files are exactly:

```text
manifest.json
metadata/run_status.json
metrics/full_comparison.json
metrics/trajectory_discontinuity.json
metrics/diagnostic_timeline.json
standardized/trajectories/<algorithm>.csv       for every diagnostic algorithm
metrics/diagnostic_timeline/<algorithm>.csv      for every diagnostic algorithm
```

Optional evidence files are recorded when present:

```text
metrics/pointcloud_frame_index.json
metrics/phase_analysis.json
figures/fast_livo2_baseline_maps/map_comparison_metrics.json
metrics/diagnostic_timeline/resources/<algorithm>.csv
```

- [ ] **Step 1: Add a reusable synthetic completed-run fixture helper and RED tests**

```python
def make_core_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    (run / "metrics" / "diagnostic_timeline").mkdir(parents=True)
    (run / "standardized" / "trajectories").mkdir(parents=True)
    manifest = {
        "dataset": {"bag_dir": str(tmp_path / "bag"), "ground_truth": None},
        "evaluation": {"ground_truth_available": False},
        "algorithms": {
            "fast_livo2": {"group": "lidar_imu_odometry", "commit": "abc"},
            "dlio": {"group": "lidar_imu_odometry", "commit": "def"},
        },
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "metadata" / "run_status.json").write_text(
        json.dumps({"run_id": "run-001", "state": "COMPLETED"}), encoding="utf-8"
    )
    for rel in ("full_comparison.json", "trajectory_discontinuity.json"):
        (run / "metrics" / rel).write_text("{}", encoding="utf-8")
    (run / "metrics" / "diagnostic_timeline.json").write_text(
        json.dumps({"algorithm_order": ["fast_livo2", "dlio"], "anomaly_windows": []}),
        encoding="utf-8",
    )
    for algorithm in ("fast_livo2", "dlio"):
        (run / "standardized" / "trajectories" / f"{algorithm}.csv").write_text(
            "timestamp,x,y,z\n0,0,0,0\n", encoding="utf-8"
        )
        (run / "metrics" / "diagnostic_timeline" / f"{algorithm}.csv").write_text(
            "bag_time_s,x_m,y_m,z_m\n0,0,0,0\n", encoding="utf-8"
        )
    bag = tmp_path / "bag"
    bag.mkdir()
    (bag / "metadata.yaml").write_text("rosbag2_bagfile_information: {}", encoding="utf-8")
    return run


def test_discover_freeze_sources_keeps_failed_algorithm_evidence(tmp_path):
    run = make_core_run(tmp_path)
    sources = discover_freeze_sources(run)
    assert sources["algorithms"] == ["fast_livo2", "dlio"]
    required = {path.relative_to(run).as_posix() for path in sources["required_files"]}
    assert "standardized/trajectories/dlio.csv" in required
    assert "metrics/diagnostic_timeline/dlio.csv" in required


def test_discover_freeze_sources_fails_when_core_diagnostic_is_missing(tmp_path):
    run = make_core_run(tmp_path)
    (run / "metrics" / "trajectory_discontinuity.json").unlink()
    with pytest.raises(FileNotFoundError, match="trajectory_discontinuity"):
        discover_freeze_sources(run)


def test_discover_freeze_sources_marks_optional_evidence_without_requiring_it(tmp_path):
    run = make_core_run(tmp_path)
    sources = discover_freeze_sources(run)
    assert sources["optional_evidence"] == {
        "maps": False,
        "phase_analysis": False,
        "pointcloud_index": False,
        "resource_timelines": False,
    }
```

- [ ] **Step 2: Run the three new tests and verify RED**

Expected: import/name failure for `discover_freeze_sources`.

- [ ] **Step 3: Implement source discovery**

Add JSON loading and exact-path validation. The algorithm list must come from `metrics/diagnostic_timeline.json` `algorithm_order`; an empty list is an error. Do not derive it from enabled algorithms in the config because failed/truncated run evidence is defined by actual diagnostic artifacts.

The function must return existing optional resource CSVs and booleans computed as:

```python
optional_evidence = {
    "maps": (run / "figures/fast_livo2_baseline_maps/map_comparison_metrics.json").is_file(),
    "phase_analysis": (run / "metrics/phase_analysis.json").is_file(),
    "pointcloud_index": (run / "metrics/pointcloud_frame_index.json").is_file(),
    "resource_timelines": all(
        (run / "metrics/diagnostic_timeline/resources" / f"{algorithm}.csv").is_file()
        for algorithm in algorithms
    ),
}
```

If only some resource CSVs exist, include the existing files in `optional_files` but set `resource_timelines=False` so the manifest discloses incomplete coverage.

- [ ] **Step 4: Run focused tests and verify GREEN**

Expected: all Task 2 tests pass and Task 1 tests remain green.

- [ ] **Step 5: Commit**

```bash
git add evaluators/freeze_experiment.py tests/test_freeze_experiment.py
git commit -m "feat: validate freeze source evidence"
```

---

### Task 3: Prepare a non-overwriting INCOMPLETE frozen workspace with provenance

**Files:**
- Modify: `evaluators/freeze_experiment.py`
- Modify: `tests/test_freeze_experiment.py`

**Interfaces:**
- Consumes: `discover_freeze_sources`, `sha256_path`, `freeze_directory_name`, `write_json_atomic`
- Produces: `resolve_git_identity(repo_root: Path) -> dict[str, str]`
- Produces: `prepare_freeze(run: Path, *, baseline: str, language: str, repo_root: Path, created_at: datetime | None = None) -> Path`
- Manifest schema version for this plan: integer `1`.

- [ ] **Step 1: Write RED tests for non-overwrite, source copying, dataset reference, and semantics**

```python
def test_prepare_freeze_creates_incomplete_bundle_and_copies_small_core_files(tmp_path, monkeypatch):
    run = make_core_run(tmp_path)
    monkeypatch.setattr(
        "freeze_experiment.resolve_git_identity",
        lambda _: {"branch": "feat/test", "commit": "0123456789abcdef", "short_sha": "01234567"},
    )
    created = dt.datetime(2026, 8, 30, 15, 40, 5, tzinfo=dt.timezone.utc)
    frozen = prepare_freeze(
        run,
        baseline="fast_livo2",
        language="zh-CN",
        repo_root=tmp_path,
        created_at=created,
    )
    payload = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["freeze_state"] == "INCOMPLETE"
    assert payload["metric_class"] == "relative-to-baseline/diagnostic/non-ground-truth"
    assert payload["ground_truth_available"] is False
    assert payload["source_run"]["run_id"] == "run-001"
    assert payload["algorithms"] == ["fast_livo2", "dlio"]
    assert (frozen / "source/manifest.json").is_file()
    assert (frozen / "source/standardized/trajectories/dlio.csv").is_file()
    assert not (frozen / "source/bag").exists()
    assert payload["dataset_source"]["path"].endswith("/bag")
    assert payload["dataset_source"]["sha256"]


def test_prepare_freeze_never_overwrites_same_identity(tmp_path, monkeypatch):
    run = make_core_run(tmp_path)
    monkeypatch.setattr(
        "freeze_experiment.resolve_git_identity",
        lambda _: {"branch": "feat/test", "commit": "0123456789abcdef", "short_sha": "01234567"},
    )
    created = dt.datetime(2026, 8, 30, 15, 40, 5, tzinfo=dt.timezone.utc)
    kwargs = dict(baseline="fast_livo2", language="en", repo_root=tmp_path, created_at=created)
    prepare_freeze(run, **kwargs)
    with pytest.raises(FileExistsError):
        prepare_freeze(run, **kwargs)
```

- [ ] **Step 2: Run tests and verify RED**

Expected: `prepare_freeze`/`resolve_git_identity` missing.

- [ ] **Step 3: Implement provenance and workspace preparation**

`resolve_git_identity` must call:

```python
subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, text=True)
subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True)
```

and return `branch`, full `commit`, and first 8 characters as `short_sha`.

`prepare_freeze` must:

1. resolve `run` and call `discover_freeze_sources(run)` before creating output;
2. read `run_id`/`state` from `metadata/run_status.json`;
3. choose `created_at = datetime.now(timezone.utc)` when not injected;
4. build `<run>/frozen/<identity>` and call `mkdir(parents=True, exist_ok=False)`;
5. create `source/`, `viewer/`, `evidence/`, `report/`;
6. copy every required run-contained file preserving its relative path below `source/` using `shutil.copy2`;
7. copy every existing optional run-contained JSON/CSV listed by discovery, also preserving its relative path;
8. hash each copied source file from the original and record `source_path`, `bundle_path`, `size_bytes`, `sha256`;
9. read `dataset.bag_dir` from the run manifest, require that it exists, and record it as `dataset_source` with absolute path, aggregate byte size, and `sha256_path` digest without copying it;
10. store algorithm provenance from `manifest["algorithms"]` for the selected diagnostic algorithms without removing failed/truncated entries;
11. compute `ground_truth_available` from `manifest["evaluation"]["ground_truth_available"]` when present, otherwise `bool(manifest["dataset"].get("ground_truth"))`;
12. write `freeze_manifest.json` with `freeze_state="INCOMPLETE"` using `write_json_atomic`.

Manifest top-level keys must be exactly sufficient for later plans:

```python
{
    "schema_version": 1,
    "freeze_state": "INCOMPLETE",
    "created_at_utc": created_at.isoformat(),
    "completed_at_utc": None,
    "source_run": {"path": str(run), "run_id": run_id, "state": run_state},
    "benchmark": git_identity,
    "baseline": baseline,
    "language": language,
    "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
    "ground_truth_available": ground_truth_available,
    "algorithms": algorithms,
    "algorithm_provenance": {...},
    "optional_evidence": optional_evidence,
    "dataset_source": {...},
    "source_artifacts": [...],
    "generated_artifacts": [],
}
```

- [ ] **Step 4: Run all freeze-core tests and verify GREEN**

Expected: all current tests pass.

- [ ] **Step 5: Commit**

```bash
git add evaluators/freeze_experiment.py tests/test_freeze_experiment.py
git commit -m "feat: prepare immutable freeze workspace"
```

---

### Task 4: Register generated artifacts and enforce atomic COMPLETE promotion

**Files:**
- Modify: `evaluators/freeze_experiment.py`
- Modify: `tests/test_freeze_experiment.py`

**Interfaces:**
- Consumes: prepared bundle from `prepare_freeze`
- Produces: `register_generated_artifact(frozen: Path, relative_path: str, role: str) -> dict[str, Any]`
- Produces: `finalize_freeze(frozen: Path, *, required_generated_paths: tuple[str, ...], completed_at: datetime | None = None) -> dict[str, Any]`

- [ ] **Step 1: Write RED lifecycle tests**

```python
def test_register_generated_artifact_records_relative_hash(tmp_path, monkeypatch):
    run = make_core_run(tmp_path)
    monkeypatch.setattr(
        "freeze_experiment.resolve_git_identity",
        lambda _: {"branch": "feat/test", "commit": "0123456789abcdef", "short_sha": "01234567"},
    )
    frozen = prepare_freeze(run, baseline="fast_livo2", language="en", repo_root=tmp_path)
    generated = frozen / "viewer/diagnostic.rrd"
    generated.write_bytes(b"rrd")
    record = register_generated_artifact(frozen, "viewer/diagnostic.rrd", "native_rerun_recording")
    assert record["path"] == "viewer/diagnostic.rrd"
    assert record["size_bytes"] == 3
    manifest = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert manifest["freeze_state"] == "INCOMPLETE"
    assert manifest["generated_artifacts"] == [record]


def test_finalize_freeze_requires_every_declared_generated_artifact(tmp_path, monkeypatch):
    run = make_core_run(tmp_path)
    monkeypatch.setattr(
        "freeze_experiment.resolve_git_identity",
        lambda _: {"branch": "feat/test", "commit": "0123456789abcdef", "short_sha": "01234567"},
    )
    frozen = prepare_freeze(run, baseline="fast_livo2", language="en", repo_root=tmp_path)
    with pytest.raises(FileNotFoundError, match="viewer/diagnostic.rrd"):
        finalize_freeze(frozen, required_generated_paths=("viewer/diagnostic.rrd",))
    payload = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert payload["freeze_state"] == "INCOMPLETE"


def test_finalize_freeze_promotes_only_after_hash_verification(tmp_path, monkeypatch):
    run = make_core_run(tmp_path)
    monkeypatch.setattr(
        "freeze_experiment.resolve_git_identity",
        lambda _: {"branch": "feat/test", "commit": "0123456789abcdef", "short_sha": "01234567"},
    )
    frozen = prepare_freeze(run, baseline="fast_livo2", language="en", repo_root=tmp_path)
    path = frozen / "viewer/diagnostic.rrd"
    path.write_bytes(b"rrd")
    register_generated_artifact(frozen, "viewer/diagnostic.rrd", "native_rerun_recording")
    completed = dt.datetime(2026, 8, 30, 16, 0, tzinfo=dt.timezone.utc)
    payload = finalize_freeze(
        frozen,
        required_generated_paths=("viewer/diagnostic.rrd",),
        completed_at=completed,
    )
    assert payload["freeze_state"] == "COMPLETE"
    assert payload["completed_at_utc"] == completed.isoformat()
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Expected: missing `register_generated_artifact`/`finalize_freeze`.

- [ ] **Step 3: Implement registration and finalization**

`register_generated_artifact` must reject absolute paths and `..` traversal, require the target to stay under `frozen`, hash it with `sha256_path`, replace any prior record with the same relative path rather than duplicate it, keep `freeze_state=INCOMPLETE`, and atomically rewrite the manifest.

`finalize_freeze` must:

```python
for relative in required_generated_paths:
    target = (frozen / relative).resolve()
    if not target.is_file():
        raise FileNotFoundError(relative)
    current_sha, current_size = sha256_path(target)
    record = next((r for r in manifest["generated_artifacts"] if r["path"] == relative), None)
    if record is None:
        raise ValueError(f"generated artifact is not registered: {relative}")
    if record["sha256"] != current_sha or record["size_bytes"] != current_size:
        raise ValueError(f"generated artifact changed after registration: {relative}")
```

Only after every required path verifies may it set:

```python
manifest["freeze_state"] = "COMPLETE"
manifest["completed_at_utc"] = completed_at.astimezone(dt.timezone.utc).isoformat()
write_json_atomic(frozen / "freeze_manifest.json", manifest)
```

Calling `register_generated_artifact` or `finalize_freeze` on an already `COMPLETE` bundle must raise `ValueError("frozen bundle is already COMPLETE")`.

- [ ] **Step 4: Run all freeze tests and verify GREEN**

```bash
PYTHONPATH="$PWD/evaluators:$PWD/benchmark_base" \
python3 -m pytest -q tests/test_freeze_experiment.py
```

Expected: all freeze-core tests pass.

- [ ] **Step 5: Run nearby regression tests**

```bash
PYTHONPATH="$PWD/evaluators:$PWD/benchmark_base" \
python3 -m pytest -q \
  tests/test_current_run_report.py \
  tests/test_rerun_diagnostic_viewer.py \
  tests/test_postprocess.py \
  tests/test_entry.py
```

Expected: existing Native viewer/report/orchestration tests remain green; no WebViewer behavior is required by this plan.

- [ ] **Step 6: Commit**

```bash
git add evaluators/freeze_experiment.py tests/test_freeze_experiment.py
git commit -m "feat: finalize immutable freeze manifests"
```

---

## Plan Self-Review

- **Spec coverage for this sub-project:** covers snapshot identity, non-overwrite, core/optional evidence policy, run/algorithm provenance, bag reference/hash, source-copy policy, `INCOMPLETE -> COMPLETE`, generated-artifact hashes, no-GT metric semantics, and source-run immutability.
- **Intentionally deferred to later plans:** Native `.rrd` generation, `report_data.json`, static evidence, HTML, PDF, final `lio-benchmark freeze` CLI, `open`, and `export`.
- **No placeholders:** every task names exact files, functions, test commands, and expected behavior.
- **Type/interface consistency:** later tasks consume the exact `Path`/dict interfaces introduced earlier; `finalize_freeze` requires explicit generated paths so later plans define final completeness without changing lifecycle semantics.
