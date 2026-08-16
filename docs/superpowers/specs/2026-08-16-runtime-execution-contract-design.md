# Runtime Execution Contract Design

## 1. Purpose

The benchmark must freeze the exact executable, replay window, and effective configuration that produced each algorithm result. Runtime identity is a scientific experiment fact, not an environment detail to reconstruct later.

This design adds an explicit executable override path for machines where an algorithm is built outside the benchmark workspace, while preserving the existing registry-default execution path.

The immediate motivating case is FAST-LIO2, whose green-house smoke used a locally built executable while the registry currently declares a ROS2 port implementation. The benchmark must record that fact explicitly rather than silently treating the runtime binary as the registry-declared implementation.

## 2. Goals

1. Allow an experiment to explicitly select a concrete executable for a selected algorithm.
2. Freeze the resolved binary identity before estimator startup.
3. Freeze replay rate, start offset, and duration in the run manifest and pass the same values to every consumer.
4. Make runtime provenance consume run-time frozen facts first and use post-run reconstruction only for legacy runs.
5. Preserve existing manifests and registry-default execution behavior when no override is configured.
6. Fail closed when an explicit override cannot be executed.
7. Keep algorithm identity, runtime implementation identity, and scientific evaluation status as separate concepts.

## 3. Non-goals

This phase does not add:

- arbitrary binary discovery under `$HOME`, `$WORKSPACE/build`, or other guessed locations;
- Docker/container abstraction;
- automatic upstream source edits;
- automatic conversion between algorithm implementations;
- Relative SE(3) comparison;
- calibration correction or optimization;
- runtime executable download/build/install;
- silent fallback from a broken explicit override to a registry default.

Relative SE(3) comparison is the next dependent phase after runtime identity is reliable.

## 4. Experiment Configuration

A V2 source manifest may add two optional top-level blocks:

```json
{
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
}
```

### 4.1. `execution_overrides`

`execution_overrides` is optional.

Each key MUST be an algorithm selected by the manifest `algorithms` list. An override for an unselected algorithm is invalid.

The first supported override field is:

```text
executable: absolute or `~`-expandable filesystem path
```

The path is local-machine execution configuration. It is frozen into the run manifest and runtime identity artifact, but it does not mutate the global algorithm registry.

A configured executable MUST:

- exist;
- be a regular file;
- be executable by the current user;
- resolve successfully through `realpath` semantics.

If any condition fails, execution is blocked. The benchmark MUST NOT silently use another binary.

### 4.2. `replay`

`replay` is optional and has these defaults:

```json
{
  "rate": 1.0,
  "start_offset_s": 0.0,
  "duration_s": null
}
```

Contract:

- `rate` MUST be finite and greater than zero.
- `start_offset_s` MUST be finite and non-negative.
- `duration_s` is either null or a finite positive number.

`duration_s = null` means replay to the end of the bag.

The replay block becomes part of the frozen run manifest during `lio-benchmark init`.

## 5. Execution Resolution

Runtime executable resolution has exactly two allowed paths:

```text
1. EXPLICIT_EXECUTABLE_OVERRIDE
2. REGISTRY_DEFAULT_EXECUTION
```

No third discovery path exists.

### 5.1. Explicit override

If `execution_overrides.<algorithm>.executable` exists, it always wins.

Resolution result:

```text
resolution_method = EXPLICIT_EXECUTABLE_OVERRIDE
```

If the override is invalid, return a blocking execution result. Do not inspect the registry for a fallback executable.

### 5.2. Registry default

If no override is configured, use the existing registry-declared runner/package/launch behavior.

Resolution result:

```text
resolution_method = REGISTRY_DEFAULT_EXECUTION
```

This preserves existing deployments and allows algorithms that are properly installed as ROS packages to keep their existing launch path.

## 6. Runtime Identity Artifact

Immediately before starting the estimator process, the benchmark writes:

```text
metadata/algorithms/<algorithm_id>/runtime_identity.json
```

The file represents run-time facts and is immutable evidence for that run. Re-running an already completed algorithm must not silently overwrite a prior runtime identity without the existing run-overwrite policy explicitly permitting it.

Minimum schema:

```json
{
  "schema_version": 1,
  "algorithm_id": "fast_lio2",
  "captured_at": "...",
  "identity_status": "FROZEN",
  "resolution_method": "EXPLICIT_EXECUTABLE_OVERRIDE",
  "requested_executable": "/home/yangxuan/RM-NAV/build/fast_lio/fastlio_mapping",
  "resolved_executable": "/home/yangxuan/RM-NAV/build/fast_lio/fastlio_mapping",
  "executable_sha256": "...",
  "executable_size_bytes": 0,
  "executable_mtime_ns": 0,
  "ros_package": "fast_lio",
  "ros_package_prefix": null,
  "source": {
    "path": null,
    "git_root": null,
    "remote_origin": null,
    "commit": null,
    "branch": null,
    "dirty": null
  },
  "registry_execution_implementation": {},
  "provenance_relationship": "EXPLICIT_OVERRIDE",
  "launch_mode": "DIRECT_EXECUTABLE",
  "effective_command": [],
  "effective_config": {
    "path": null,
    "sha256": null
  },
  "environment": {
    "ros_distro": "humble",
    "workspace": "/path/to/workspace"
  },
  "dataset": {
    "bag_dir": "/path/to/bag"
  },
  "replay": {
    "rate": 1.0,
    "start_offset_s": 0.0,
    "duration_s": 15.0
  }
}
```

Optional values remain null when they cannot be proven. Unknown values are never guessed.

## 7. Identity and Provenance Status

Two separate status dimensions are required.

### 7.1. `identity_status`

Allowed values:

```text
FROZEN
BLOCKED_EXECUTION
```

`FROZEN` means the actual launch identity was captured sufficiently to start the estimator.

`BLOCKED_EXECUTION` means the requested execution contract cannot be satisfied; the estimator must not start.

### 7.2. `provenance_relationship`

Allowed initial values:

```text
REGISTRY_MATCH
EXPLICIT_OVERRIDE
UNKNOWN_SOURCE
```

These are descriptive, not accuracy grades.

`EXPLICIT_OVERRIDE` is valid by design. It does not mean the run is scientifically invalid; it means the run did not use the registry-default implementation identity and therefore the exact runtime binary must be cited from `runtime_identity.json`.

## 8. Binary Fingerprint

For direct executable overrides, freeze at minimum:

```text
resolved realpath
SHA256
file size
mtime_ns
```

SHA256 is the primary binary identity. File modification time is diagnostic metadata only.

The benchmark must compute the fingerprint before estimator startup so the artifact describes the file that execution resolution selected.

If hashing or stat fails, execution is blocked rather than recording an incomplete identity and continuing.

## 9. Source Provenance Discovery

Source discovery is best-effort metadata after the executable itself has been identified.

Possible evidence sources include:

1. ROS package prefix when available;
2. colcon workspace package source mapping;
3. a known registry local source hint;
4. a git repository containing a resolved source candidate.

The benchmark may record git root, remote, commit, branch, and dirty state when provable.

Failure to map an executable back to source code does not erase the binary fingerprint. Such a run can remain:

```text
identity_status = FROZEN
provenance_relationship = UNKNOWN_SOURCE or EXPLICIT_OVERRIDE
```

This distinction is important for standalone locally built executables.

## 10. FAST-LIO2 Direct Override Contract

When FAST-LIO2 has an explicit executable override, the runner launches the selected binary directly instead of invoking the ROS launch file.

Effective form:

```bash
"$BENCHMARK_RESOLVED_EXECUTABLE" \
  --ros-args \
  --params-file "$CONFIG"
```

The generated benchmark YAML remains run-local.

The runtime identity must record both:

```text
resolved executable + SHA256
generated config path + SHA256
```

When no FAST-LIO2 executable override is configured, the existing registry-default ROS2 launch path remains unchanged.

The runner must not contain a list of guessed fallback binary paths.

## 11. Runner Environment Contract

`execute_algorithm()` resolves execution before invoking the runner and exports explicit runtime environment values, including:

```text
BENCHMARK_EXECUTION_RESOLUTION_METHOD
BENCHMARK_RESOLVED_EXECUTABLE          # set for direct override
BENCHMARK_REPLAY_RATE
BENCHMARK_REPLAY_START_OFFSET_S
BENCHMARK_REPLAY_DURATION_S            # empty/unset for full remaining bag
```

Existing variables such as `WORKSPACE`, `BENCHMARK_RUN_DIR`, and `BENCHMARK_GENERATED_CONFIG_DIR` remain supported.

Runners consume these values; they do not independently reinterpret the source manifest.

## 12. Replay Contract

All benchmark runners use the same frozen replay configuration.

Equivalent ROS2 bag play semantics:

```text
rate            -> ros2 bag play --rate
start_offset_s  -> ros2 bag play --start-offset
optional duration -> stop playback after the configured replay interval
```

The implementation may use ROS2 CLI duration support if the installed ROS2 version provides the required semantics, or a benchmark-controlled timeout/termination mechanism. Whichever method is used must be deterministic, visible in the effective command/metadata, and tested.

The scientific contract is the frozen interval, not a particular shell implementation.

## 13. Common Scan Manifest Coupling

The common scan manifest must consume the frozen replay window from the run manifest by default.

For a smoke run:

```text
replay.start_offset_s = 0
replay.duration_s = 15
```

map sampling must not use the remaining hundreds of seconds of the source bag as unmatched scans.

CLI scan-window overrides may remain available for explicit derived diagnostics, but they must be labeled as overrides and must not silently replace the frozen run replay contract.

## 14. Runtime Provenance Audit

For new runs, provenance evidence order is:

```text
runtime_identity.json
        ↓
trajectory frame audit
        ↓
post-run environment/source checks
        ↓
provenance verdict
```

The audit treats run-time frozen identity as the highest-confidence evidence for which executable actually ran.

For legacy runs without `runtime_identity.json`, current post-run reconstruction remains available and must be labeled:

```text
LEGACY_RECONSTRUCTED
```

The audit must not rewrite historical run identities.

## 15. Frame Contract Relationship

Runtime executable identity and frame semantics remain separate gates.

Example:

```text
binary identity = FROZEN / EXPLICIT_OVERRIDE
frame audit      = odom -> sensor
registry frame   = camera_init -> body
```

This remains a frame-contract mismatch even though the executable itself is now known exactly.

Freezing the binary lets the mismatch be investigated against the correct implementation instead of against an assumed upstream source.

## 16. Run Status and Failure Semantics

A failed explicit execution contract must not be reported as an algorithm failure.

Recommended execution blocker:

```text
BLOCKED_EXECUTION
```

Examples:

- configured executable path missing;
- executable not a regular file;
- executable permission missing;
- realpath cannot resolve;
- binary hash/stat cannot be captured.

This is distinct from:

```text
FAIL_ALGORITHM
BLOCKED_CALIBRATION
BLOCKED_INPUT
BLOCKED_DEPENDENCY
```

## 17. Diagnostic Bundle Integration

`lio-benchmark bundle` should include any existing:

```text
metadata/algorithms/<algorithm>/runtime_identity.json
```

by default because it is small, high-value provenance evidence.

No raw executable binary is copied into the diagnostic bundle.

## 18. Backward Compatibility

### Existing source manifests

Manifests without `execution_overrides` or `replay` remain valid.

They resolve to:

```text
registry-default execution
rate = 1.0
start_offset_s = 0.0
duration_s = null
```

### Existing frozen runs

Existing runs do not gain invented runtime identities.

Post-run provenance continues to work through the legacy reconstruction path and is explicitly labeled as reconstructed evidence.

### Existing runners

Algorithms other than those explicitly adapted for direct executable override retain their current registry-default launch behavior.

## 19. Security and Safety Boundaries

The executable override is an explicit local execution request. The benchmark does not download executables or discover arbitrary files.

The implementation should avoid shell-string execution for the override itself. Construct argv explicitly and preserve the resolved executable as one argument.

Runtime identity capture is read-only with respect to the executable and source tree.

## 20. Testing Contract

### Manifest tests

- old V2 manifests remain valid;
- valid replay blocks are accepted;
- invalid replay values fail closed;
- override keys must reference selected algorithms;
- malformed executable override shape fails validation.

### Execution resolution tests

- explicit override wins over registry default;
- missing explicit executable returns `BLOCKED_EXECUTION`;
- non-executable override returns `BLOCKED_EXECUTION`;
- explicit override never falls back silently;
- no-override path preserves registry-default execution.

### Runtime identity tests

- realpath is frozen;
- SHA256 is deterministic;
- file size/mtime are recorded;
- generated config hash is recorded when present;
- unknown source provenance stays unknown rather than guessed;
- artifact is written before estimator process execution.

### FAST-LIO2 runner tests

- override produces the direct executable command;
- no override keeps the existing ROS launch path;
- no guessed build-path fallback is present;
- generated configuration remains run-local.

### Replay tests

- replay rate reaches runner;
- start offset reaches runner;
- optional duration reaches runner;
- full-bag default remains backward compatible;
- common scan manifest defaults to the same frozen replay interval.

### Provenance tests

- new run audit prefers `runtime_identity.json` over post-run discovery;
- frame mismatch remains visible even with frozen binary identity;
- legacy run without identity uses `LEGACY_RECONSTRUCTED` path.

### Bundle tests

- runtime identity is included when present;
- missing identity is recorded as missing evidence without failing the bundle.

## 21. Acceptance Criteria

The phase is complete when all of the following are demonstrated:

1. A source manifest can explicitly configure the local FAST-LIO2 executable.
2. `lio-benchmark init` freezes the override and replay settings into a run.
3. Preflight blocks an invalid explicit executable without fallback.
4. Before FAST-LIO2 starts, the run contains a binary fingerprint with realpath and SHA256.
5. FAST-LIO2 direct override runs through the selected executable and run-local YAML.
6. The same frozen replay window is used by the estimator runner and common scan manifest.
7. Runtime provenance reports the actual frozen runtime identity rather than assuming the registry-declared implementation.
8. The observed FAST-LIO2 frame labels remain independently auditable.
9. Legacy runs remain readable and explicitly use reconstructed provenance.
10. `lio-benchmark bundle` includes runtime identity evidence.
11. Full unit/contract CI remains green.

## 22. Follow-on Phase

After this contract is implemented and validated on a fresh three-algorithm smoke, the next phase is Relative SE(3) Motion Benchmarking:

```text
verified runtime identity
+ verified tracked physical frame
+ canonical static transform
        ↓
common tracked-frame trajectory
        ↓
ΔT(t) = T(t0)^-1 T(t)
        ↓
pairwise translational + SO(3) disagreement
```

That phase must remain diagnostic-only wherever calibration is still unconfirmed.
