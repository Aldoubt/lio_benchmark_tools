# Runtime Execution Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the exact runtime executable, replay window, and effective configuration for each benchmark algorithm run, with explicit executable overrides and fail-closed provenance.

**Architecture:** Keep algorithm identity in the registry and machine-specific execution choices in the experiment manifest. Add one ROS-independent execution-contract module that validates overrides, resolves an executable, fingerprints it, and writes immutable `runtime_identity.json`; the CLI freezes replay/override settings into the run and exports them to runners. Runtime provenance and scan sampling consume the frozen run facts first, while legacy runs retain reconstructed fallback behavior.

**Tech Stack:** Python 3.10, argparse, dataclasses, pathlib, hashlib, subprocess, ROS 2 Humble shell adapters, unittest, GitHub Actions.

## Global Constraints

- Resolution has exactly two paths: `EXPLICIT_EXECUTABLE_OVERRIDE` and `REGISTRY_DEFAULT_EXECUTION`.
- Never scan `$HOME`, `$WORKSPACE/build`, or guessed binary paths.
- A broken explicit override returns `BLOCKED_EXECUTION`; it never falls back to a registry default.
- Replay defaults are `rate=1.0`, `start_offset_s=0.0`, `duration_s=null`.
- Frozen run manifest replay settings are authoritative; shell variables are derived compatibility values only.
- `runtime_identity.json` is written before estimator startup and must not be silently overwritten.
- Binary identity freezes realpath, SHA256, size, and mtime before launch.
- Unknown source provenance remains unknown; do not guess.
- Existing source manifests and legacy frozen runs remain readable.
- Relative SE(3) comparison is explicitly out of scope for this plan.

---

## File Structure

- Create `benchmark_base/lib/execution_contract.py` — replay parsing, override resolution, binary fingerprinting, runtime identity construction/writing.
- Create `benchmark_base/tests/test_execution_contract.py` — unit contract for replay, override precedence, blocking failures, fingerprints, immutable identity writes.
- Modify `benchmark_base/lib/manifest.py` — validate/resolve `execution_overrides` and `replay`, preserve defaults in frozen V2 runtime structure.
- Modify `benchmark_base/tests/test_cli_manifest.py` — source-manifest validation and init freeze coverage.
- Modify `benchmark_base/bin/lio-benchmark` — freeze replay/overrides at init, resolve execution before runner, export derived environment, write runtime identity, expose `BLOCKED_EXECUTION` correctly.
- Modify `benchmark_base/lib/adapters.py` and `benchmark_base/tests/test_adapters.py` — preflight explicit executable override without registry fallback.
- Modify `evaluators/run_fast_lio2_test.sh` — direct executable path for explicit override; registry ROS launch path remains unchanged.
- Modify `evaluators/build_scan_manifest.py` and `benchmark_base/tests/test_scan_window.py` — consume frozen `replay` by default; retain explicit CLI-derived override labeling.
- Modify `evaluators/audit_runtime_provenance.py`, `benchmark_base/lib/runtime_provenance.py`, and `benchmark_base/tests/test_runtime_provenance.py` — prefer `runtime_identity.json`, label fallback `LEGACY_RECONSTRUCTED`, keep frame mismatch independent.
- Modify `benchmark_base/lib/diagnostic_bundle.py` and `benchmark_base/tests/test_diagnostic_bundle.py` — include runtime identity evidence by default.
- Modify `benchmark_base/config/green_house_v2_test.json`, `benchmark_base/docs/V2_WORKFLOW.md`, `README.md` — document explicit FAST-LIO2 executable and frozen replay flow without hardcoding it into the registry.

---

### Task 1: Manifest Replay and Execution Override Contract

**Files:**
- Modify: `benchmark_base/lib/manifest.py`
- Test: `benchmark_base/tests/test_cli_manifest.py`

**Interfaces:**
- Produces: `normalized_replay(manifest: dict[str, Any]) -> dict[str, float | None]`
- Produces: resolved V2 manifests containing `execution_overrides` as an object and normalized `replay` values.
- Consumes: existing `resolve_manifest()` and `validate_manifest()`.

- [ ] **Step 1: Write failing manifest tests**

Add tests equivalent to:

```python
def test_v2_replay_defaults_are_frozen(self):
    manifest = self.example_v2_manifest()
    resolved = resolve_manifest(manifest, self.registry)
    self.assertEqual(
        {"rate": 1.0, "start_offset_s": 0.0, "duration_s": None},
        resolved["replay"],
    )


def test_v2_accepts_selected_algorithm_executable_override(self):
    manifest = self.example_v2_manifest()
    manifest["execution_overrides"] = {
        manifest["algorithms"][0]: {"executable": "/tmp/fastlio_mapping"}
    }
    errors = validate_manifest(
        manifest,
        registry=self.registry,
        check_paths=False,
        module_root=MODULE_ROOT,
    )
    self.assertEqual([], errors)


def test_v2_rejects_override_for_unselected_algorithm(self):
    manifest = self.example_v2_manifest()
    manifest["execution_overrides"] = {"kiss_icp": {"executable": "/tmp/kiss"}}
    errors = validate_manifest(manifest, registry=self.registry, check_paths=False)
    self.assertIn("execution_overrides.kiss_icp references an unselected algorithm", errors)


def test_v2_rejects_invalid_replay_values(self):
    for replay in (
        {"rate": 0.0},
        {"start_offset_s": -1.0},
        {"duration_s": 0.0},
    ):
        manifest = self.example_v2_manifest()
        manifest["replay"] = replay
        self.assertTrue(validate_manifest(manifest, registry=self.registry, check_paths=False))
```

- [ ] **Step 2: Run the manifest tests and verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_cli_manifest -v
```

Expected: new replay/default/override assertions fail because V2 resolution does not yet normalize these fields.

- [ ] **Step 3: Implement normalization and validation**

Add a helper with these exact semantics:

```python
def normalized_replay(manifest: dict[str, Any]) -> dict[str, float | None]:
    raw = manifest.get("replay", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("replay must be an object")
    rate = float(raw.get("rate", 1.0))
    start = float(raw.get("start_offset_s", 0.0))
    duration_raw = raw.get("duration_s")
    duration = None if duration_raw is None else float(duration_raw)
    if not math.isfinite(rate) or rate <= 0.0:
        raise ValueError("replay.rate must be finite and > 0")
    if not math.isfinite(start) or start < 0.0:
        raise ValueError("replay.start_offset_s must be finite and >= 0")
    if duration is not None and (not math.isfinite(duration) or duration <= 0.0):
        raise ValueError("replay.duration_s must be null or finite and > 0")
    return {"rate": rate, "start_offset_s": start, "duration_s": duration}
```

Validate `execution_overrides` as an object whose keys are selected algorithm IDs and whose only supported initial shape is `{ "executable": <non-empty string> }`. In `resolve_manifest()`, copy normalized overrides and `normalized_replay(manifest)` into the resolved frozen structure.

- [ ] **Step 4: Run manifest tests and full unit discovery**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_cli_manifest -v
python3 -m unittest discover -s benchmark_base/tests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/manifest.py benchmark_base/tests/test_cli_manifest.py
git commit -m "feat: freeze replay and execution override manifest contract"
```

---

### Task 2: Runtime Execution Resolution and Binary Identity

**Files:**
- Create: `benchmark_base/lib/execution_contract.py`
- Create: `benchmark_base/tests/test_execution_contract.py`

**Interfaces:**
- Produces: `ReplayContract(rate: float, start_offset_s: float, duration_s: float | None)`.
- Produces: `ExecutionResolution(algorithm_id: str, resolution_method: str, requested_executable: str | None, resolved_executable: Path | None)`.
- Produces: `resolve_execution(manifest, algorithm_id) -> ExecutionResolution`.
- Produces: `fingerprint_executable(path: Path) -> dict[str, Any]`.
- Produces: `build_runtime_identity(...) -> dict[str, Any]`.
- Produces: `write_runtime_identity(run, algorithm_id, payload) -> Path`.

- [ ] **Step 1: Write RED execution-contract tests**

Cover exact behaviors:

```python
def test_explicit_override_wins_and_resolves_realpath(self):
    binary = self.make_executable("fastlio_mapping", b"binary-v1")
    manifest = self.manifest_with_override("fast_lio2", binary)
    result = resolve_execution(manifest, "fast_lio2")
    self.assertEqual("EXPLICIT_EXECUTABLE_OVERRIDE", result.resolution_method)
    self.assertEqual(binary.resolve(), result.resolved_executable)


def test_missing_override_blocks_without_fallback(self):
    manifest = self.manifest_with_override("fast_lio2", self.root / "missing")
    with self.assertRaisesRegex(ExecutionContractError, "BLOCKED_EXECUTION"):
        resolve_execution(manifest, "fast_lio2")


def test_fingerprint_contains_sha_size_and_mtime(self):
    binary = self.make_executable("algo", b"abc")
    value = fingerprint_executable(binary)
    self.assertEqual(hashlib.sha256(b"abc").hexdigest(), value["sha256"])
    self.assertEqual(3, value["size_bytes"])
    self.assertIsInstance(value["mtime_ns"], int)


def test_existing_frozen_identity_is_not_overwritten(self):
    path = write_runtime_identity(self.run, "fast_lio2", {"identity_status": "FROZEN"})
    with self.assertRaisesRegex(ExecutionContractError, "already exists"):
        write_runtime_identity(self.run, "fast_lio2", {"identity_status": "FROZEN"})
```

Also test no-override returns `REGISTRY_DEFAULT_EXECUTION` with `resolved_executable=None`.

- [ ] **Step 2: Run the new test and verify RED**

```bash
python3 -m unittest benchmark_base.tests.test_execution_contract -v
```

Expected: import/module failure because `execution_contract.py` does not exist.

- [ ] **Step 3: Implement the ROS-independent execution contract**

Implement explicit-path checks in this order: expand user, resolve strict, regular file, `os.access(path, os.X_OK)`, stat, SHA256. Raise:

```python
class ExecutionContractError(ValueError):
    pass
```

with messages prefixed by `BLOCKED_EXECUTION:` for all explicit override failures.

`write_runtime_identity()` writes to:

```text
metadata/algorithms/<algorithm_id>/runtime_identity.json
```

using atomic temp-file + replace only when the target does not already exist. Do not overwrite an existing target.

- [ ] **Step 4: Run execution-contract and full tests**

```bash
python3 -m unittest benchmark_base.tests.test_execution_contract -v
python3 -m unittest discover -s benchmark_base/tests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/execution_contract.py benchmark_base/tests/test_execution_contract.py
git commit -m "feat: add immutable runtime execution identity"
```

---

### Task 3: Preflight and CLI Runtime Identity Integration

**Files:**
- Modify: `benchmark_base/lib/adapters.py`
- Modify: `benchmark_base/tests/test_adapters.py`
- Modify: `benchmark_base/bin/lio-benchmark`
- Modify: `benchmark_base/tests/test_cli_manifest.py`

**Interfaces:**
- Consumes: `resolve_execution()`, `fingerprint_executable()`, `build_runtime_identity()`, `write_runtime_identity()` from Task 2.
- Produces runner environment variables `BENCHMARK_EXECUTION_RESOLUTION_METHOD`, `BENCHMARK_RESOLVED_EXECUTABLE`, `BENCHMARK_REPLAY_RATE`, `BENCHMARK_REPLAY_START_OFFSET_S`, `BENCHMARK_REPLAY_DURATION_S`.

- [ ] **Step 1: Add failing adapter/CLI tests**

Add adapter tests asserting invalid explicit executable produces:

```python
self.assertEqual("BLOCKED_EXECUTION", result.status)
self.assertFalse(result.runnable)
```

and does not report `BLOCKED_ENVIRONMENT` from a missing registry source hint first.

Add a CLI/init test that initializes a V2 run and asserts frozen `manifest.json` contains:

```python
self.assertEqual(source["execution_overrides"], frozen["execution_overrides"])
self.assertEqual(source["replay"], frozen["replay"])
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python3 -m unittest benchmark_base.tests.test_adapters benchmark_base.tests.test_cli_manifest -v
```

Expected: explicit execution path is not yet part of preflight/runner environment.

- [ ] **Step 3: Integrate execution resolution into preflight**

Add `BLOCKED_EXECUTION` to blocking statuses. In `preflight_algorithm()`, call `resolve_execution()` before source-path enforcement. For explicit overrides, binary availability is authoritative; registry source absence must not block the run. Preserve existing source checks for registry-default execution.

- [ ] **Step 4: Freeze runtime identity before subprocess startup**

In `execute_algorithm()`:

1. resolve execution;
2. prepare run-local configuration;
3. construct the effective command contract;
4. fingerprint direct executable if present;
5. hash generated config when available;
6. write `runtime_identity.json`;
7. only then invoke the runner subprocess.

Export:

```python
env.update({
    "BENCHMARK_EXECUTION_RESOLUTION_METHOD": resolution.resolution_method,
    "BENCHMARK_RESOLVED_EXECUTABLE": str(resolution.resolved_executable or ""),
    "BENCHMARK_REPLAY_RATE": str(manifest["replay"]["rate"]),
    "BENCHMARK_REPLAY_START_OFFSET_S": str(manifest["replay"]["start_offset_s"]),
    "BENCHMARK_REPLAY_DURATION_S": "" if manifest["replay"]["duration_s"] is None else str(manifest["replay"]["duration_s"]),
    # compatibility variables are derived from the same frozen values
    "BAG_PLAY_RATE": str(manifest["replay"]["rate"]),
    "BAG_START_OFFSET": str(manifest["replay"]["start_offset_s"]),
    "BAG_DURATION": "" if manifest["replay"]["duration_s"] is None else str(manifest["replay"]["duration_s"]),
})
```

Do not allow existing shell environment values to override those frozen fields.

- [ ] **Step 5: Run tests and compile CLI**

```bash
python3 -m unittest benchmark_base.tests.test_adapters benchmark_base.tests.test_cli_manifest benchmark_base.tests.test_execution_contract -v
python3 -m compileall benchmark_base
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add benchmark_base/lib/adapters.py benchmark_base/tests/test_adapters.py benchmark_base/bin/lio-benchmark benchmark_base/tests/test_cli_manifest.py
git commit -m "feat: freeze runtime identity before algorithm launch"
```

---

### Task 4: FAST-LIO2 Direct Executable Override and Frozen Replay

**Files:**
- Modify: `evaluators/run_fast_lio2_test.sh`
- Test: `benchmark_base/tests/test_execution_contract.py`

**Interfaces:**
- Consumes: `BENCHMARK_EXECUTION_RESOLUTION_METHOD`, `BENCHMARK_RESOLVED_EXECUTABLE`, and frozen replay environment from Task 3.
- Preserves: current `ros2 launch fast_lio mapping.launch.py ...` behavior for registry-default execution.

- [ ] **Step 1: Add a failing shell-contract test**

Read the runner source in the unit test and assert it contains both modes:

```python
self.assertIn('EXPLICIT_EXECUTABLE_OVERRIDE', text)
self.assertIn('"$BENCHMARK_RESOLVED_EXECUTABLE"', text)
self.assertIn('ros2 launch fast_lio mapping.launch.py', text)
self.assertNotIn('/home/yangxuan/RM-NAV/build', text)
```

Also assert replay arguments are assembled from `BENCHMARK_REPLAY_*` rather than guessed globals.

- [ ] **Step 2: Run the shell-contract test and verify RED**

```bash
python3 -m unittest benchmark_base.tests.test_execution_contract -v
```

Expected: runner-source assertions fail.

- [ ] **Step 3: Implement two launch modes**

Use a branch equivalent to:

```bash
if [[ "${BENCHMARK_EXECUTION_RESOLUTION_METHOD:-REGISTRY_DEFAULT_EXECUTION}" == "EXPLICIT_EXECUTABLE_OVERRIDE" ]]; then
  [[ -n "${BENCHMARK_RESOLVED_EXECUTABLE:-}" ]] || { echo "missing BENCHMARK_RESOLVED_EXECUTABLE" >&2; exit 65; }
  "$BENCHMARK_RESOLVED_EXECUTABLE" --ros-args --params-file "$CONFIG" \
    >"$OUTPUT_DIR/fast_lio2.log" 2>&1 &
else
  ros2 launch fast_lio mapping.launch.py \
    config_path:="$BENCHMARK_GENERATED_CONFIG_DIR" \
    config_file:=benchmark.yaml rviz:=false use_sim_time:=true \
    >"$OUTPUT_DIR/fast_lio2.log" 2>&1 &
fi
```

Build `ros2 bag play` argv as an array:

```bash
play_args=("$BAG_DIR" --rate "$BENCHMARK_REPLAY_RATE" --clock 100.0)
if [[ "$BENCHMARK_REPLAY_START_OFFSET_S" != "0" && "$BENCHMARK_REPLAY_START_OFFSET_S" != "0.0" ]]; then
  play_args+=(--start-offset "$BENCHMARK_REPLAY_START_OFFSET_S")
fi
```

For finite duration, use a benchmark-controlled termination strategy that is deterministic on Humble and leaves the exact mechanism visible in logs; do not introduce guessed CLI flags without testing them on the target ROS distro.

- [ ] **Step 4: Run tests and shell syntax**

```bash
python3 -m unittest benchmark_base.tests.test_execution_contract -v
bash -n evaluators/run_fast_lio2_test.sh
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluators/run_fast_lio2_test.sh benchmark_base/tests/test_execution_contract.py
git commit -m "feat: support explicit FAST-LIO2 executable override"
```

---

### Task 5: Replay-Window Coupling for Common Scan Manifest

**Files:**
- Modify: `evaluators/build_scan_manifest.py`
- Modify: `benchmark_base/tests/test_scan_window.py`

**Interfaces:**
- Consumes: frozen run `manifest["replay"]`.
- Preserves: CLI `--start-offset-s` and `--duration-s` as explicit derived overrides.

- [ ] **Step 1: Write RED replay-source tests**

Test a pure helper extracted from the evaluator:

```python
def test_scan_window_defaults_to_frozen_replay(self):
    replay = {"rate": 1.0, "start_offset_s": 3.0, "duration_s": 15.0}
    window, source = resolve_scan_window(replay, None, None)
    self.assertEqual(3.0, window.start_offset_s)
    self.assertEqual(15.0, window.duration_s)
    self.assertEqual("RUN_MANIFEST_REPLAY", source)


def test_cli_scan_window_is_labeled_override(self):
    replay = {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 15.0}
    window, source = resolve_scan_window(replay, 2.0, 5.0)
    self.assertEqual("CLI_OVERRIDE", source)
```

- [ ] **Step 2: Run test and verify RED**

```bash
python3 -m unittest benchmark_base.tests.test_scan_window -v
```

Expected: helper/label does not yet exist; current evaluator reads legacy `replay_window`.

- [ ] **Step 3: Implement frozen replay coupling**

Replace `replay_window` default consumption with `manifest["replay"]`. Keep legacy `replay_window` only as a fallback for old frozen runs, labeled `LEGACY_REPLAY_WINDOW`. Metadata source values become one of:

```text
RUN_MANIFEST_REPLAY
CLI_OVERRIDE
LEGACY_REPLAY_WINDOW
FULL_BAG_DEFAULT
```

- [ ] **Step 4: Run tests**

```bash
python3 -m unittest benchmark_base.tests.test_scan_window -v
python3 -m unittest discover -s benchmark_base/tests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluators/build_scan_manifest.py benchmark_base/tests/test_scan_window.py
git commit -m "feat: couple map sampling to frozen replay window"
```

---

### Task 6: Runtime Provenance Prefers Frozen Identity

**Files:**
- Modify: `benchmark_base/lib/runtime_provenance.py`
- Modify: `evaluators/audit_runtime_provenance.py`
- Modify: `benchmark_base/tests/test_runtime_provenance.py`

**Interfaces:**
- Consumes: `metadata/algorithms/<algorithm>/runtime_identity.json` when present.
- Produces: `identity_evidence_source = RUNTIME_IDENTITY | LEGACY_RECONSTRUCTED`.
- Preserves: independent `frame_contract_status` and frame mismatch verdict.

- [ ] **Step 1: Write RED provenance tests**

Add tests equivalent to:

```python
def test_frozen_runtime_identity_wins_over_post_run_discovery(self):
    identity = {
        "identity_status": "FROZEN",
        "resolution_method": "EXPLICIT_EXECUTABLE_OVERRIDE",
        "resolved_executable": "/tmp/actual",
        "executable_sha256": "abc",
    }
    row = build_runtime_provenance_record(
        algorithm=self.algorithm,
        frame_audit=self.matching_frame_audit,
        ros_package_prefix="/wrong/prefix",
        source_state={"remote_origin": "https://github.com/wrong/repo.git"},
        runtime_identity=identity,
    )
    self.assertEqual("RUNTIME_IDENTITY", row["identity_evidence_source"])
    self.assertEqual("EXPLICIT_EXECUTABLE_OVERRIDE", row["resolution_method"])


def test_legacy_run_is_explicitly_reconstructed(self):
    row = build_runtime_provenance_record(
        algorithm=self.algorithm,
        frame_audit=self.matching_frame_audit,
        ros_package_prefix="/tmp/install/pkg",
        source_state=self.matching_source,
        runtime_identity=None,
    )
    self.assertEqual("LEGACY_RECONSTRUCTED", row["identity_evidence_source"])
```

- [ ] **Step 2: Run provenance tests and verify RED**

```bash
python3 -m unittest benchmark_base.tests.test_runtime_provenance -v
```

Expected: function does not yet accept/use `runtime_identity`.

- [ ] **Step 3: Implement identity-first provenance**

Add optional `runtime_identity` input. When present and `identity_status == FROZEN`, copy binary identity/resolution fields from it and never replace them with post-run guesses. Post-run package/source checks may enrich missing source fields only. Frame contract classification still uses frame audit + registry trajectory contract and can remain `FRAME_CONTRACT_MISMATCH`.

In evaluator, load runtime identity from the algorithm metadata path; if absent, run current package/source reconstruction and label `LEGACY_RECONSTRUCTED`.

- [ ] **Step 4: Run tests**

```bash
python3 -m unittest benchmark_base.tests.test_runtime_provenance -v
python3 -m unittest discover -s benchmark_base/tests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/runtime_provenance.py evaluators/audit_runtime_provenance.py benchmark_base/tests/test_runtime_provenance.py
git commit -m "feat: prefer frozen runtime identity in provenance audit"
```

---

### Task 7: Diagnostic Bundle Includes Runtime Identity

**Files:**
- Modify: `benchmark_base/lib/diagnostic_bundle.py`
- Modify: `benchmark_base/tests/test_diagnostic_bundle.py`

**Interfaces:**
- Consumes: per-algorithm runtime identity artifact.
- Produces: default diagnostic archive containing any existing `runtime_identity.json`, with missing evidence recorded but non-fatal.

- [ ] **Step 1: Write RED bundle test**

Add an identity file to the fixture and assert:

```python
self.assertIn(
    "metadata/algorithms/fast_lio2/runtime_identity.json",
    selection.included,
)
```

Add a fixture with no identity and assert the same path appears in `selection.missing` without bundle creation failure.

- [ ] **Step 2: Run bundle tests and verify RED**

```bash
python3 -m unittest benchmark_base.tests.test_diagnostic_bundle -v
```

Expected: runtime identity is not in current selection.

- [ ] **Step 3: Add runtime identity to per-algorithm bundle candidates**

Extend the existing per-algorithm tuple with:

```python
f"metadata/algorithms/{algorithm_id}/runtime_identity.json"
```

Do not include executable binaries.

- [ ] **Step 4: Run tests**

```bash
python3 -m unittest benchmark_base.tests.test_diagnostic_bundle -v
python3 -m unittest discover -s benchmark_base/tests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/diagnostic_bundle.py benchmark_base/tests/test_diagnostic_bundle.py
git commit -m "feat: bundle frozen runtime identities"
```

---

### Task 8: Example Configuration, Documentation, and Full Verification

**Files:**
- Modify: `benchmark_base/config/green_house_v2_test.json`
- Modify: `benchmark_base/docs/V2_WORKFLOW.md`
- Modify: `README.md`
- Modify if needed: `.github/workflows/core-python.yml`

**Interfaces:**
- Documents the exact public workflow created by Tasks 1-7.

- [ ] **Step 1: Update example configuration**

Use a smoke example that demonstrates both blocks without moving machine-specific paths into the algorithm registry:

```json
"execution_overrides": {
  "fast_lio2": {
    "executable": "/home/yangxuan/RM-NAV/build/fast_lio/fastlio_mapping"
  }
},
"replay": {
  "rate": 1.0,
  "start_offset_s": 0.0,
  "duration_s": 15.0
}
```

If `green_house_v2_test.json` is intended as a portable multi-user example rather than the local smoke config, create/document the override in a dedicated local-example snippet instead of making the default config unusable elsewhere.

- [ ] **Step 2: Document runtime execution evidence flow**

Document:

```text
source manifest
  -> frozen run manifest
  -> execution resolution
  -> runtime_identity.json before launch
  -> runner
  -> frame audit
  -> runtime provenance
  -> diagnostic bundle
```

State that `EXPLICIT_EXECUTABLE_OVERRIDE` is a valid execution method, not an accuracy grade, and that frame mismatch remains a separate gate.

- [ ] **Step 3: Run fresh full verification**

```bash
python3 -m unittest benchmark_base.tests.test_registry -v
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall benchmark_base evaluators reporting visualization
for f in evaluators/*.sh; do bash -n "$f"; done
benchmark_base/bin/lio-benchmark list algorithms >/dev/null
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit documentation/config changes**

```bash
git add benchmark_base/config/green_house_v2_test.json benchmark_base/docs/V2_WORKFLOW.md README.md .github/workflows/core-python.yml
git commit -m "docs: document frozen runtime execution workflow"
```

- [ ] **Step 5: Record implementation verification note**

Create `docs/verification/runtime_execution_contract_verification.md` with the implemented contract, exact verification commands/results, known remaining target-machine validation, and the next smoke commands. Commit it separately:

```bash
git add docs/verification/runtime_execution_contract_verification.md
git commit -m "docs: verify runtime execution contract"
```

---

## Post-Implementation Target-Machine Gate

After code/CI is green, update the local checkout and create a **new run ID** rather than overwriting `green_house_three_smoke_004`. The new three-algorithm smoke must prove:

```text
FAST-LIVO2 runtime identity frozen
FAST-LIO2 explicit executable realpath + SHA256 frozen
KISS-ICP runtime identity frozen
same replay interval for all three
same Common Scan Manifest interval
frame audit remains independent
runtime provenance consumes RUNTIME_IDENTITY
```

Only after that gate should the repository begin the separate Relative SE(3) Motion Benchmark implementation.
