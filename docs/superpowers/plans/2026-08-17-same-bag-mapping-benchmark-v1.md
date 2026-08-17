# Same-Bag Mapping Benchmark V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add repository-side full-bag benchmark contracts, per-run CPU/RSS/wall-time evidence, and a read-only Algorithm I/O + map/performance summarizer, stopping before the target machine replays the 622.99 s bag.

**Architecture:** Extend the existing execution path rather than creating a second supervisor. A small pure-Python runtime measurement module wraps one estimator runner process session and writes one immutable JSON record; a separate pure-Python same-bag summary module reads frozen run artifacts and emits CSV/Markdown/JSON views. The existing trajectory, strict common-map, Inspector, Report and Demo pipelines remain unchanged.

**Tech Stack:** Python 3 standard library, Linux `/proc` process-session sampling, argparse CLI, existing JSON/CSV artifact contracts, unittest/GitHub Actions.

## Global Constraints

- Work on `feat/lio-baseline-suite`, not `main`.
- Preserve Representative Window V1 and Failure-Mode Audit V1 artifacts and semantics.
- V1 algorithms are exactly `fast_livo2`, `fast_lio2`, `kiss_icp`.
- Full replay is exactly rate `1.0`, start `0.0 s`, duration `622.99 s`.
- Profile semantics are `DEFAULT_ADAPTED`; no greenhouse-specific algorithm tuning.
- Run estimators sequentially.
- Do not force optional Native Map publication if it changes runtime cost.
- Unified Map remains `STRICT_COMMON_INTERSECTION`.
- No ground-truth/map-accuracy claim and no overall heterogeneous-modality ranking.
- Runtime evidence is single-run descriptive evidence; no repeated full-bag trials in V1.
- No new third-party Python dependency for resource metrics.
- Do not run the full bag during repository implementation.

---

### Task 1: Freeze the full-bag experiment contract

**Files:**
- Create: `benchmark_base/tests/test_same_bag_full_config.py`
- Create: `benchmark_base/config/green_house_three_full_bag_v1.json`

**Interfaces:**
- Consumes: current `green_house_three_runtime_smoke.json` runtime paths, overlays and standardization values.
- Produces: a frozen full-bag config selected by the target-machine verification workflow.

- [ ] **Step 1: Write the failing config-contract test**

Test must load both smoke and full-bag configs and assert the full config does not yet exist or, after implementation, that:

```python
assert full["algorithms"] == ["fast_livo2", "fast_lio2", "kiss_icp"]
assert full["workspace"] == smoke["workspace"]
assert full["execution_overrides"] == smoke["execution_overrides"]
assert full["runtime_overlays"] == smoke["runtime_overlays"]
assert full["standardization"] == smoke["standardization"]
assert full["replay"] == {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 622.99}
```

Also assert the experiment name is `green_house_three_full_bag_v1`.

- [ ] **Step 2: Run the test and verify RED**

```bash
python3 -m unittest benchmark_base.tests.test_same_bag_full_config -v
```

Expected: failure because `green_house_three_full_bag_v1.json` does not exist.

- [ ] **Step 3: Add the minimal full-bag config**

Copy only accepted runtime/overlay/standardization settings and change name + duration.

- [ ] **Step 4: Verify GREEN**

Run the focused test and existing manifest tests.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/tests/test_same_bag_full_config.py benchmark_base/config/green_house_three_full_bag_v1.json
git commit -m "feat: freeze same-bag full benchmark config"
```

---

### Task 2: Capture per-algorithm runtime performance without changing algorithm semantics

**Files:**
- Create: `benchmark_base/tests/test_runtime_performance.py`
- Create: `benchmark_base/lib/runtime_performance.py`
- Modify: `benchmark_base/bin/lio-benchmark-core`

**Interfaces:**
- Produces:
  - `run_process_with_metrics(command, *, cwd, env, log_path, algorithm_id, output_path) -> int`
  - JSON schema `lio_benchmark_runtime_performance/v1`
  - `metrics/runtime/<algorithm>.json`
- Consumes: exact command/env already constructed by `execute_algorithm`.

- [ ] **Step 1: Write failing pure-Python tests**

Cover at minimum:

```python
result = run_process_with_metrics(
    [sys.executable, "-c", "x=sum(range(100000)); print(x)"],
    cwd=tmp_path,
    env=os.environ.copy(),
    log_path=tmp_path / "run.log",
    algorithm_id="synthetic",
    output_path=tmp_path / "metrics.json",
)
assert result == 0
payload = json.loads((tmp_path / "metrics.json").read_text())
assert payload["schema"] == "lio_benchmark_runtime_performance/v1"
assert payload["algorithm_id"] == "synthetic"
assert payload["measurement_method"] == "LINUX_PROC_PROCESS_SESSION_V1"
assert payload["wall_time_s"] > 0
assert payload["cpu_total_s"] is None or payload["cpu_total_s"] >= 0
assert payload["max_rss_kib"] is None or payload["max_rss_kib"] > 0
assert payload["returncode"] == 0
assert payload["status"] == "PASS"
```

Add a non-zero child test and immutability/refuse-overwrite test.

- [ ] **Step 2: Verify RED**

Expected: import failure for `benchmark_base.lib.runtime_performance`.

- [ ] **Step 3: Implement minimal Linux process-session sampler**

Use `subprocess.Popen(..., start_new_session=True)` and standard-library `/proc/<pid>/stat` scanning. Sample the launched session while alive, aggregate user/system ticks and RSS for processes whose session id equals the leader PID, and retain maxima/cumulative terminal evidence. Convert ticks using `os.sysconf("SC_CLK_TCK")` and pages using `SC_PAGE_SIZE`. If `/proc` is unavailable or individual process records race with exit, keep the run alive and emit `null` metrics plus limitation text rather than fabricating zero.

The output writer must refuse an existing metrics file.

- [ ] **Step 4: Replace only the blocking `subprocess.run` in `execute_algorithm`**

Use the new helper with:

```python
output_path = run / "metrics" / "runtime" / f"{algorithm_id}.json"
```

Preserve log path, command, cwd, env and return-code classification.

- [ ] **Step 5: Verify GREEN and regressions**

Run focused runtime tests plus execution-contract/run-outcome tests.

- [ ] **Step 6: Commit**

```bash
git add benchmark_base/tests/test_runtime_performance.py benchmark_base/lib/runtime_performance.py benchmark_base/bin/lio-benchmark-core
git commit -m "feat: capture estimator runtime performance"
```

---

### Task 3: Generate the Algorithm I/O, performance and map-artifact inventory

**Files:**
- Create: `benchmark_base/tests/test_same_bag_summary.py`
- Create: `benchmark_base/lib/same_bag_summary.py`
- Create: `evaluators/summarize_same_bag.py`

**Interfaces:**
- Produces: `summarize_same_bag(run: Path) -> dict[str, Any]`.
- Writes exactly:
  - `reports/algorithm_io_matrix.csv`
  - `reports/algorithm_io_matrix.md`
  - `metrics/runtime_performance.csv`
  - `reports/same_bag_mapping_v1.json`
- Reads frozen manifest, runtime/run status, standardized trajectories, Native/Unified Map metadata, runtime metrics and existing strict common-map/coverage evidence.

- [ ] **Step 1: Write RED tests with a synthetic run**

Create a manifest containing FAST-LIVO2, FAST-LIO2 and KISS-ICP records plus synthetic runtime identities/status/metrics and map metadata. Assert exactly three rows in manifest order and fields for modalities/topics/artifact states/performance.

Explicit assertions:

```python
assert rows[0]["algorithm_id"] == "fast_livo2"
assert rows[0]["effective_modalities"] == "lidar+imu"
assert kiss["effective_modalities"] == "lidar"
assert kiss["native_map_status"] == "NOT_PROVIDED"
assert row["unified_map_status"] in {"AVAILABLE", "MISSING"}
assert "map_accuracy" not in row
```

Test missing evidence maps to `MISSING`/`UNKNOWN`/null, never numeric zero.

- [ ] **Step 2: Verify RED**

Expected import failure for `same_bag_summary`.

- [ ] **Step 3: Implement the minimal read-only summarizer**

Prefer frozen manifest algorithm records over live registry data. Runtime identity and artifact metadata are optional evidence. Native-map status must honor explicit registry/frozen declarations and actual files; KISS-ICP local map must not be mislabeled global Native Map.

Unified map point count comes from existing map metadata `point_count`; strict matched scan counts/ratio come from its timestamp-matching metadata or common-map metadata.

- [ ] **Step 4: Add the thin evaluator**

`evaluators/summarize_same_bag.py --run <path>` calls the pure library and prints the summary JSON path/result.

- [ ] **Step 5: Verify GREEN**

Run focused tests and compile the evaluator.

- [ ] **Step 6: Commit**

```bash
git add benchmark_base/tests/test_same_bag_summary.py benchmark_base/lib/same_bag_summary.py evaluators/summarize_same_bag.py
git commit -m "feat: summarize same-bag mapping artifacts"
```

---

### Task 4: Expose the additive CLI contract

**Files:**
- Create: `benchmark_base/tests/test_same_bag_summary_cli.py`
- Modify: `benchmark_base/bin/lio-benchmark`

**Interfaces:**
- Produces:

```bash
benchmark_base/bin/lio-benchmark summarize same-bag --run <run>
```

- [ ] **Step 1: Write RED parser/handler tests**

Assert `build_parser()` accepts the command, the handler exists, and the handler invokes only `evaluators/summarize_same_bag.py` for an existing run. It must not invoke estimator runner, rosbag replay or map reconstruction.

- [ ] **Step 2: Verify RED**

Expected argparse invalid-choice / missing handler failure.

- [ ] **Step 3: Implement the additive CLI branch**

Add `summarize` root parser, `same-bag` child parser and route in `main()`.

- [ ] **Step 4: Verify GREEN**

Run focused CLI tests plus historical CLI manifest tests.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/tests/test_same_bag_summary_cli.py benchmark_base/bin/lio-benchmark
git commit -m "feat: expose same-bag summary cli"
```

---

### Task 5: Freeze predecessor conclusion and target-machine verification

**Files:**
- Create: `docs/results/2026-08-17-representative-window-v1-conclusion.md`
- Create: `docs/verification/same_bag_mapping_v1_verification.md`

**Interfaces:**
- Produces the exact Codex target-machine runbook and stop condition.

- [ ] **Step 1: Record the accepted predecessor results**

Document Representative Window V1 12/12 and Failure-Mode Audit V1 two `DESCRIPTIVE_DIVERGENCE_FIRST` observations, explicitly preserving no-ground-truth/non-causal language.

- [ ] **Step 2: Write target-machine runbook**

Runbook must:

1. assert expected Git HEAD and clean/safely understood worktree
2. validate/init a new immutable run id from `green_house_three_full_bag_v1.json`
3. snapshot + preflight
4. run algorithms sequentially
5. standardize trajectories using existing `trajectory-from-run`
6. execute existing timestamp/frame/runtime-provenance audits
7. build strict common-map manifest
8. reconstruct each Unified Map
9. run `summarize same-bag`
10. show Inspector/Report/Demo commands without requiring GUI acceptance for the machine contract
11. print one target contract PASS only after all artifact checks succeed

The runbook must forbid overwriting any existing run and must not reuse Representative Window child runs as full-bag output.

- [ ] **Step 3: Repository verification**

```bash
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 benchmark_base/bin/lio-benchmark list algorithms
```

- [ ] **Step 4: Commit docs**

```bash
git add docs/results/2026-08-17-representative-window-v1-conclusion.md docs/verification/same_bag_mapping_v1_verification.md
git commit -m "docs: add same-bag full benchmark verification"
```

---

## Final repository stop condition

Stop before executing any 622.99 s bag replay when all of the following are true:

```text
SAME_BAG_MAPPING_V1_REPOSITORY_ACCEPTANCE=PASS
SAME_BAG_MAPPING_V1_TARGET_MACHINE_ACCEPTANCE=PENDING
```

At that point hand the exact target-machine runbook/prompt to Codex. Do not add Point-LIO/DLIO/Leg-KILO yet and do not run the full bag from the repository-side session.
