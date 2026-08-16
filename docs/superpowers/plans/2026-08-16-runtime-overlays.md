# Runtime Overlays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze and apply per-algorithm ROS runtime overlays so preflight and estimator execution use the same declared overlay stack and KISS-ICP runs from a fresh shell without manual sourcing.

**Architecture:** Add schema-v2 `runtime_overlays` normalization in the manifest layer, then build the formal ROS environment from `/opt/ros/<distro>`, the benchmark workspace, and the selected algorithm's frozen overlays in order. CLI preflight probes that constructed environment, runners source exactly the same frozen overlay list emitted by `emit_runtime_env.py`, and runtime identity fingerprints each sourced setup script while continuing to record the final ROS package prefix separately.

**Tech Stack:** Python 3.10 standard library, Bash, ROS 2 Humble environment conventions, Ament resource index, `unittest`, GitHub Actions.

## Global Constraints

- Only per-algorithm overlays are supported; do not add global overlays.
- `runtime_overlays` is optional and keyed only by algorithms selected in the schema-v2 manifest.
- Each algorithm value is an ordered non-empty list of unique non-empty absolute setup-script paths.
- Source-manifest validation validates declaration shape; formal target-machine preflight validates existence, regular-file status, source success, and final runtime package availability.
- Formal preflight and formal execution must source in exact order: `/opt/ros/<distro>/setup.bash`, `<workspace>/install/setup.bash` when present, then frozen per-algorithm overlays in manifest order.
- Formal execution must not rely on algorithm-specific overlays previously sourced in the caller's interactive shell.
- No filesystem scanning, automatic clone/build/install, `/tmp` fallback, or inferred overlay path is allowed.
- Runtime identity remains immutable and records each overlay setup path, SHA-256, and size; final runtime ROS package prefix remains a separate existing field.
- The greenhouse KISS overlay is `/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash`.
- FAST-LIVO2 and FAST-LIO2 behavior must remain unchanged except for consuming shared overlay-contract infrastructure.
- Repository CI remains ROS-independent.

---

### Task 1: Manifest Contract and Frozen Greenhouse Configuration

**Files:**
- Modify: `benchmark_base/lib/manifest.py`
- Modify: `benchmark_base/tests/test_cli_manifest.py`
- Modify: `benchmark_base/config/green_house_three_runtime_smoke.json`

**Interfaces:**
- Produces: `normalized_runtime_overlays(manifest: dict[str, Any], selected_algorithms: list[str] | tuple[str, ...]) -> dict[str, list[str]]`
- Produces: resolved schema-v2 manifests containing a normalized `runtime_overlays` object.

- [ ] **Step 1: Write failing manifest tests**

Add tests that assert ordered absolute overlays are frozen and malformed declarations fail closed:

```python
def test_v2_runtime_overlays_are_validated_and_frozen_in_order(self) -> None:
    manifest = self._v2_manifest()
    manifest["runtime_overlays"] = {
        "fast_livo2": ["/opt/vendor/a/setup.bash", "/opt/vendor/b/setup.bash"]
    }
    self.assertEqual([], validate_manifest(manifest, registry=Registry(), check_paths=False))
    resolved = resolve_manifest(manifest, Registry())
    self.assertEqual(
        ["/opt/vendor/a/setup.bash", "/opt/vendor/b/setup.bash"],
        resolved["runtime_overlays"]["fast_livo2"],
    )


def test_v2_rejects_invalid_runtime_overlays(self) -> None:
    cases = (
        ({"kiss_icp": ["/opt/kiss/setup.bash"]}, "references an unselected algorithm"),
        ({"fast_livo2": []}, "must be a non-empty list"),
        ({"fast_livo2": ["relative/setup.bash"]}, "must be absolute"),
        ({"fast_livo2": ["/a/setup.bash", "/a/setup.bash"]}, "duplicate overlay path"),
        ({"fast_livo2": [""]}, "must be a non-empty string"),
    )
```

Extend the greenhouse smoke contract test to require:

```python
self.assertEqual(
    ["/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash"],
    resolved["runtime_overlays"]["kiss_icp"],
)
```

- [ ] **Step 2: Run the manifest tests and verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_cli_manifest -v
```

Expected: FAIL because `runtime_overlays` is not normalized/frozen and the greenhouse config lacks the KISS overlay declaration.

- [ ] **Step 3: Implement minimal manifest normalization**

Add `normalized_runtime_overlays()` beside `normalized_execution_overrides()` with exact validation rules from the spec. In `resolve_manifest()` set:

```python
resolved["runtime_overlays"] = normalized_runtime_overlays(manifest, algorithm_refs)
```

Do not check filesystem existence in this normalization function.

Update `green_house_three_runtime_smoke.json` with:

```json
"runtime_overlays": {
  "kiss_icp": [
    "/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash"
  ]
}
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_cli_manifest -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/manifest.py benchmark_base/tests/test_cli_manifest.py benchmark_base/config/green_house_three_runtime_smoke.json
git commit -m "feat: freeze per-algorithm runtime overlays"
```

---

### Task 2: Formal Runtime Environment Construction for Preflight

**Files:**
- Modify: `benchmark_base/lib/ros_workspace.py`
- Modify: `benchmark_base/bin/lio-benchmark`
- Create: `benchmark_base/tests/test_runtime_overlays.py`

**Interfaces:**
- Consumes: frozen `manifest["runtime_overlays"]` from Task 1.
- Produces: `runtime_overlays_for_algorithm(manifest: dict[str, Any], algorithm_id: str) -> tuple[Path, ...]`
- Produces: `capture_sourced_environment(*, workspace: Path, ros_distro: str, overlays: tuple[Path, ...], base_env: Mapping[str, str] | None = None) -> dict[str, str]`
- Produces: `RuntimeEnvironmentError` for missing/non-file setup scripts or failed source commands.

- [ ] **Step 1: Write failing environment tests**

Create `test_runtime_overlays.py` using temporary fake setup scripts. Cover exact order and fail-closed behavior without ROS:

```python
def test_capture_sourced_environment_applies_workspace_then_overlays_in_order(self) -> None:
    # fake ros setup sets ORDER=ros; workspace appends :workspace;
    # two overlay setup scripts append :overlay_a and :overlay_b
    env = capture_sourced_environment(...)
    self.assertEqual("ros:workspace:overlay_a:overlay_b", env["ORDER"])


def test_missing_declared_overlay_fails_closed(self) -> None:
    with self.assertRaisesRegex(RuntimeEnvironmentError, "runtime overlay does not exist"):
        capture_sourced_environment(...)


def test_overlay_source_failure_fails_closed(self) -> None:
    # overlay contains `return 7`
    with self.assertRaisesRegex(RuntimeEnvironmentError, "failed to source runtime overlay"):
        capture_sourced_environment(...)
```

Also test `runtime_overlays_for_algorithm()` returns an empty tuple for algorithms without overlays and preserves frozen order for algorithms with overlays.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_runtime_overlays -v
```

Expected: FAIL because the runtime environment APIs do not exist.

- [ ] **Step 3: Implement shared environment construction**

Extend `ros_workspace.py` with standard-library-only helpers. `capture_sourced_environment()` must build a clean formal shell chain from the supplied base environment, explicitly source the requested ROS setup, optional workspace setup, and each overlay, then emit `env -0`. It must check each declared overlay is a regular file before invoking Bash and report a deterministic `RuntimeEnvironmentError` on shell failure.

Keep existing `build_sourced_python_command()` behavior compatible; add an optional `overlays: tuple[Path, ...] = ()` parameter so ROS-backed evaluators can use the same ordering when needed.

- [ ] **Step 4: Wire CLI preflight and execution preflight to the constructed environment**

Add one local helper in `lio-benchmark`:

```python
def runtime_preflight(run, manifest, algorithm_id, allow_diagnostic_calibration):
    overlays = runtime_overlays_for_algorithm(manifest, algorithm_id)
    try:
        env = capture_sourced_environment(
            workspace=Path(manifest["workspace"]).expanduser().resolve(),
            ros_distro=resolve_ros_distro(run),
            overlays=overlays,
        )
    except RuntimeEnvironmentError as exc:
        return AdapterStatus(
            algorithm_id=algorithm_id,
            status="BLOCKED_ENVIRONMENT",
            runnable=False,
            diagnostic_only=False,
            reasons=(str(exc),),
            checks={"runtime_overlays": [str(path) for path in overlays]},
        )
    return preflight_algorithm(
        manifest,
        algorithm_id,
        benchmark_root=MODULE_ROOT,
        allow_diagnostic_calibration=allow_diagnostic_calibration,
        runtime_env=env,
    )
```

Use this helper from both `cmd_preflight()` and `execute_algorithm()` so they evaluate the same formal environment rather than the caller's ambient Ament state. Pass the same environment semantics into `prepare_algorithm()` if preparation re-runs preflight.

- [ ] **Step 5: Run focused and full tests**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_runtime_overlays benchmark_base.tests.test_runtime_package_preflight -v
python3 -m unittest discover -s benchmark_base/tests -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add benchmark_base/lib/ros_workspace.py benchmark_base/bin/lio-benchmark benchmark_base/tests/test_runtime_overlays.py
git commit -m "feat: preflight frozen ROS overlay stacks"
```

---

### Task 3: Shell-Safe Overlay Emission and Runner Application

**Files:**
- Modify: `evaluators/emit_runtime_env.py`
- Create: `evaluators/source_runtime_overlays.sh`
- Modify: `evaluators/run_fast_livo_test.sh`
- Modify: `evaluators/run_fast_lio2_test.sh`
- Modify: `evaluators/run_kiss_icp_test.sh`
- Modify: `benchmark_base/tests/test_execution_contract.py`
- Modify: `benchmark_base/tests/test_runtime_overlays.py`

**Interfaces:**
- Consumes: frozen normalized overlay lists.
- Produces shell assignments: `BENCHMARK_RUNTIME_OVERLAY_COUNT`, `BENCHMARK_RUNTIME_OVERLAY_0`, `BENCHMARK_RUNTIME_OVERLAY_1`, ... in exact frozen order.
- Produces sourced helper behavior that exits non-zero when a declared setup file is missing/not regular or sourcing fails.

- [ ] **Step 1: Write failing emission and runner structure tests**

Add tests that invoke `emit_runtime_env.py` on a synthetic frozen manifest and assert the emitted assignments preserve order. Add runner structure assertions:

```python
for runner in (...):
    text = ...
    self.assertIn("source_runtime_overlays.sh", text)
    self.assertLess(text.index("source_runtime_overlays.sh"), text.index("freeze_runtime_identity.py"))
```

For KISS, also assert the runner does not contain the persistent absolute setup path; it must come only from the manifest.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_runtime_overlays benchmark_base.tests.test_execution_contract -v
```

Expected: FAIL because overlay assignments/helper sourcing are absent.

- [ ] **Step 3: Extend `emit_runtime_env.py`**

Load normalized overlays for `args.algorithm` from the frozen manifest and emit:

```text
BENCHMARK_RUNTIME_OVERLAY_COUNT=2
BENCHMARK_RUNTIME_OVERLAY_0=/first/setup.bash
BENCHMARK_RUNTIME_OVERLAY_1=/second/setup.bash
```

using the existing `assignment()`/`shlex.quote()` mechanism. Emit count `0` for algorithms without overlays.

- [ ] **Step 4: Add shared Bash source helper and wire all three smoke runners**

`source_runtime_overlays.sh` must iterate indexed variables with Bash indirect expansion:

```bash
for ((i=0; i<BENCHMARK_RUNTIME_OVERLAY_COUNT; i++)); do
  var="BENCHMARK_RUNTIME_OVERLAY_${i}"
  overlay="${!var:-}"
  [[ -f "$overlay" ]] || { echo "runtime overlay is missing or not a regular file: $overlay" >&2; return 65 2>/dev/null || exit 65; }
  source "$overlay" || { echo "failed to source runtime overlay: $overlay" >&2; return 65 2>/dev/null || exit 65; }
done
```

Each runner sources this helper immediately after `emit_runtime_env.py` assignments are loaded/exported and before `freeze_runtime_identity.py` or estimator startup.

- [ ] **Step 5: Run tests and shell syntax verification**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_runtime_overlays benchmark_base.tests.test_execution_contract -v
bash -n evaluators/source_runtime_overlays.sh evaluators/run_fast_livo_test.sh evaluators/run_fast_lio2_test.sh evaluators/run_kiss_icp_test.sh
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add evaluators/emit_runtime_env.py evaluators/source_runtime_overlays.sh evaluators/run_fast_livo_test.sh evaluators/run_fast_lio2_test.sh evaluators/run_kiss_icp_test.sh benchmark_base/tests/test_execution_contract.py benchmark_base/tests/test_runtime_overlays.py
git commit -m "feat: source frozen overlays in estimator runners"
```

---

### Task 4: Runtime Identity Overlay Fingerprints

**Files:**
- Modify: `benchmark_base/lib/execution_contract.py`
- Modify: `evaluators/freeze_runtime_identity.py`
- Modify: `benchmark_base/tests/test_execution_contract.py`

**Interfaces:**
- Produces: `fingerprint_runtime_overlays(paths: Iterable[str | Path]) -> list[dict[str, Any]]`
- Extends `build_runtime_identity(..., runtime_overlays: list[dict[str, Any]] | None = None)` and payload field `runtime_overlays`.

- [ ] **Step 1: Write failing identity tests**

Add a test with two setup files containing distinct bytes:

```python
evidence = fingerprint_runtime_overlays([setup_a, setup_b])
self.assertEqual([str(setup_a.resolve()), str(setup_b.resolve())], [row["setup_path"] for row in evidence])
self.assertEqual(hashlib.sha256(setup_a.read_bytes()).hexdigest(), evidence[0]["setup_sha256"])
self.assertEqual(setup_a.stat().st_size, evidence[0]["setup_size_bytes"])
```

Extend runtime identity test to assert the exact evidence list is preserved separately from `runtime_package_prefix`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_execution_contract -v
```

Expected: FAIL because overlay fingerprint APIs/identity field do not exist.

- [ ] **Step 3: Implement overlay fingerprinting and freeze integration**

`fingerprint_runtime_overlays()` must resolve each file strictly, require a regular readable file, hash it with existing `sha256_file()`, and return records in input order:

```python
{
    "setup_path": str(resolved),
    "setup_sha256": sha256_file(resolved),
    "setup_size_bytes": int(resolved.stat().st_size),
}
```

Raise `ExecutionContractError("BLOCKED_EXECUTION: ...")` if fingerprinting fails after a runner has entered the identity-freeze boundary.

In `freeze_runtime_identity.py`, read the selected algorithm's frozen overlays, fingerprint them immediately before `build_runtime_identity()`, and pass the evidence into the payload. Do not infer overlays from current shell state.

- [ ] **Step 4: Run focused and full tests**

Run:

```bash
python3 -m unittest benchmark_base.tests.test_execution_contract -v
python3 -m unittest discover -s benchmark_base/tests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/execution_contract.py evaluators/freeze_runtime_identity.py benchmark_base/tests/test_execution_contract.py
git commit -m "feat: fingerprint runtime overlay setup files"
```

---

### Task 5: Documentation, Fresh Verification, and Target-Machine Acceptance Commands

**Files:**
- Modify: `README.md`
- Modify: `benchmark_base/docs/V2_WORKFLOW.md`
- Create: `docs/verification/runtime_overlays_verification.md`

**Interfaces:**
- Documents the user-facing source-manifest field and the exact target-machine fresh-shell acceptance sequence.

- [ ] **Step 1: Update workflow documentation**

Document the greenhouse manifest fragment:

```json
"runtime_overlays": {
  "kiss_icp": [
    "/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash"
  ]
}
```

State explicitly that runtime overlays are frozen per algorithm, sourced after ROS/workspace setup, and must not be replaced by ad-hoc manual shell sourcing.

- [ ] **Step 2: Add verification note**

Record repository-side checks and leave target-machine acceptance as pending until actual output is supplied. The target fresh-shell sequence must begin with only:

```bash
cd /home/yangxuan/lio_benchmark_tools
git pull --ff-only
source /opt/ros/humble/setup.bash
```

It must intentionally **not** source `kiss_icp_ws/install/setup.bash` before `lio-benchmark preflight` or `lio-benchmark run`.

- [ ] **Step 3: Run final fresh repository verification**

Run on the final implementation HEAD:

```bash
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall benchmark_base evaluators reporting visualization
bash -n evaluators/*.sh
python3 benchmark_base/bin/registry-smoke
```

Expected: all unit tests PASS, compileall completes without syntax errors, all shell files parse, and registry smoke passes.

- [ ] **Step 4: Confirm GitHub Actions for the final HEAD**

Verify the `Core Contracts` workflow for the exact final commit SHA is `completed/success` and all core steps are successful. Do not use an earlier workflow run as completion evidence.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md benchmark_base/docs/V2_WORKFLOW.md docs/verification/runtime_overlays_verification.md
git commit -m "docs: verify frozen runtime overlay workflow"
```

- [ ] **Step 6: Target-machine acceptance after user pulls final HEAD**

From a fresh shell that has not sourced the KISS workspace, create a new run id, run `preflight --allow-diagnostic-calibration`, and require:

```text
FAST-LIVO2 -> BLOCKED_CALIBRATION, runnable=true, diagnostic_only=true
FAST-LIO2  -> BLOCKED_CALIBRATION, runnable=true, diagnostic_only=true
KISS-ICP   -> PASS, runnable=true
preflight rc=0
```

Then execute KISS and inspect `runtime_identity.json` for the persistent setup path/fingerprint plus `runtime_package_prefix=/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/kiss_icp`. Only after this acceptance succeeds should the three-algorithm fresh smoke proceed.
