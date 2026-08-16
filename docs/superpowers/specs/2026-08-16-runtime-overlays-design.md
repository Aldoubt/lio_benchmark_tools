# Runtime Overlays Design

## 1. Goal

Add a frozen per-algorithm ROS runtime overlay contract to `lio_benchmark_tools` so formal benchmark execution does not depend on whatever overlays the user happened to source in the interactive shell before launching the benchmark.

The immediate target is KISS-ICP, whose ROS2 wrapper is installed persistently at:

```text
/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash
```

The design must remain generic for any selected algorithm that needs one or more additional ROS overlays.

## 2. Scope

This change introduces only per-algorithm overlays. There is no global overlay list in this version.

Supported source-manifest shape:

```json
{
  "runtime_overlays": {
    "kiss_icp": [
      "/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash"
    ]
  }
}
```

The field is optional. Algorithms without an entry preserve their current execution behavior.

The change does not move KISS-ICP into `agt_navigation_v2`, does not clone or build dependencies automatically, and does not infer overlay paths by scanning the filesystem.

## 3. Manifest Contract

`runtime_overlays` is a top-level schema-v2 object keyed by selected algorithm id.

Each value is an ordered non-empty list of non-empty absolute setup-script paths.

Validation rules:

- every key must reference an algorithm selected by the manifest
- each overlay list must be a list
- each list entry must be a non-empty string
- each path must be absolute
- duplicate paths for one algorithm are rejected
- an empty list is rejected; omit the algorithm key instead
- source-manifest validation checks path shape, while target-machine execution/preflight checks that the file actually exists

Resolution freezes `runtime_overlays` into `run/manifest.json` alongside `execution_overrides` and `replay`.

For the current greenhouse smoke config, the intended frozen entry is:

```json
"runtime_overlays": {
  "kiss_icp": [
    "/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash"
  ]
}
```

## 4. Overlay Application Order

For an algorithm run, the runtime environment is constructed in this exact order:

```text
/opt/ros/<distro>/setup.bash
        ->
<workspace>/install/setup.bash, when present
        ->
runtime_overlays[algorithm][0]
        ->
runtime_overlays[algorithm][1]
        ->
...
        ->
preflight/runtime-package evidence
        ->
runtime identity freeze
        ->
estimator runner execution
```

Overlay order is scientifically relevant and must be preserved exactly as frozen in the run manifest.

The benchmark must not treat pre-existing interactive-shell `AMENT_PREFIX_PATH`, `CMAKE_PREFIX_PATH`, `LD_LIBRARY_PATH`, or `PATH` content as proof that an undeclared algorithm-specific overlay was part of the formal run. Formal preflight and formal execution rebuild the intended ROS environment from the frozen contract before resolving package identity.

## 5. Preflight Semantics

For algorithms using `REGISTRY_DEFAULT_EXECUTION`, runtime package availability remains the execution gate.

When `runtime_overlays[algorithm]` is declared, formal preflight must evaluate runtime package availability after sourcing:

1. ROS distro setup
2. benchmark workspace setup, when present
3. the algorithm's declared runtime overlays in frozen order

Fail closed as `BLOCKED_ENVIRONMENT` when:

- a declared overlay setup script does not exist
- a declared overlay path is not a regular file
- sourcing an overlay fails
- the registry-declared runtime ROS package is still unavailable after the frozen environment is constructed

A missing or stale `source.local_path_hint` remains provenance information and does not block ROS package execution when runtime package evidence is available.

Explicit executable overrides keep their existing execution semantics. Runtime overlays may still be declared for an explicit-executable algorithm if its process requires ROS package resources, but the explicit executable remains the authoritative execution binary.

## 6. Runner Contract

The algorithm-specific runner must not depend on the caller manually sourcing the extra overlay.

Before estimator startup, the runner obtains the frozen overlay list for its algorithm and sources it in order after the base ROS/workspace setup.

The current KISS runner therefore changes conceptually from:

```text
source /opt/ros/humble/setup.bash
source <workspace>/install/setup.bash
ros2 pkg prefix kiss_icp
```

to:

```text
source /opt/ros/humble/setup.bash
source <workspace>/install/setup.bash
source /home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash
ros2 pkg prefix kiss_icp
```

where the final path is read from the frozen manifest rather than hard-coded in the shell script.

No runner may scan `/home`, build trees, `/tmp`, or arbitrary workspaces to discover a fallback overlay.

## 7. Runtime Identity

`metadata/algorithms/<algorithm>/runtime_identity.json` is extended with the exact frozen runtime overlay evidence used by the estimator process.

Each declared setup script is fingerprinted immediately before estimator startup. The identity records, in frozen order:

```json
"runtime_overlays": [
  {
    "setup_path": "/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash",
    "setup_sha256": "<sha256>",
    "setup_size_bytes": 1234
  }
]
```

`setup_path` is the exact frozen setup-script path. `setup_sha256` and `setup_size_bytes` fingerprint the file that was actually sourced. A missing or unreadable setup file blocks before identity can be frozen as a successful execution identity.

The final registry-declared runtime package prefix continues to be recorded separately in the existing `runtime_package_prefix` field. This avoids guessing which individual overlay "owns" a package when multiple overlays are present.

The existing runtime identity source/provenance fields continue to resolve the final runtime package prefix back to its source workspace/git repository when possible. For the persistent KISS v1.3.0 workspace, this should recover the source checkout under `/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/src/kiss-icp` rather than relying on the stale registry `local_path_hint`.

Runtime identity remains immutable once written.

## 8. Environment Helper Boundary

Introduce one ROS-independent manifest helper for normalized overlay data, and one shell-safe emission path used by runners.

The existing `emit_runtime_env.py` is extended to emit the frozen overlay list for the selected algorithm in a shell-safe representation. Runners consume only that emitted frozen contract; they do not parse ad-hoc overlay variables supplied by the user.

Formal preflight uses the same normalized overlay list and the same base-environment ordering as formal execution. The implementation may use a small sourced-shell probe to obtain the resulting Ament package facts, but the core manifest/adapters modules remain importable in CI without ROS installed.

## 9. Error Handling

The contract uses explicit failure instead of fallback guessing.

Examples:

```text
runtime_overlays.kiss_icp[0] is relative
    -> manifest validation failure

runtime_overlays.kiss_icp references unselected algorithm
    -> manifest validation failure

frozen setup path no longer exists on target machine
    -> BLOCKED_ENVIRONMENT

overlay source command returns non-zero
    -> BLOCKED_ENVIRONMENT

overlay sources successfully but kiss_icp package is unavailable
    -> BLOCKED_ENVIRONMENT

runtime identity already exists
    -> existing immutable BLOCKED_EXECUTION behavior remains unchanged
```

No automatic clone, build, package installation, or alternative overlay discovery occurs inside benchmark execution.

## 10. Testing Strategy

All repository CI tests remain ROS-independent.

TDD coverage must include:

- manifest accepts a selected algorithm with one or multiple absolute runtime overlays
- manifest rejects overlays for unselected algorithms
- manifest rejects relative, empty, duplicate, and malformed overlay declarations
- resolution freezes overlay order exactly
- shell environment emission preserves overlay order and paths
- preflight and runner share the same normalized overlay order
- runner structure sources frozen overlays before runtime identity freeze and estimator startup
- missing frozen overlay is represented as a fail-closed environment condition
- runtime identity includes exact setup paths and setup-file fingerprints
- final runtime package prefix remains separately recorded
- algorithms without runtime overlays preserve current behavior
- current greenhouse smoke config freezes the persistent KISS v1.3.0 setup path

Target-machine acceptance is separate from CI and must verify from a fresh shell that does not manually source the KISS workspace:

```text
FAST-LIVO2 -> BLOCKED_CALIBRATION, runnable=true, diagnostic_only=true
FAST-LIO2  -> BLOCKED_CALIBRATION, runnable=true, diagnostic_only=true
KISS-ICP   -> PASS, runnable=true
preflight rc=0
```

Then a fresh run must prove KISS execution also succeeds without manually sourcing the KISS workspace in the invoking shell.

## 11. Non-Goals

This change does not:

- add global runtime overlays
- manage dependency installation
- automatically clone or build KISS-ICP
- move benchmark dependencies into the navigation workspace
- change estimator parameters
- change trajectory/frame/gauge semantics
- change calibration status
- add fallback source-tree scanning
- reuse the historical `/tmp/kiss-icp*` build/install paths

## 12. Acceptance Criteria

The feature is complete when all of the following are true:

1. The schema-v2 source manifest can freeze per-algorithm runtime overlays.
2. Formal preflight and formal execution construct the same declared ROS overlay stack.
3. KISS-ICP is runnable from a fresh shell without manually sourcing its workspace first.
4. Missing/broken declared overlays fail closed as `BLOCKED_ENVIRONMENT`.
5. Runtime identity records exact overlay setup path(s), setup-file fingerprints, and the existing final runtime package-prefix evidence.
6. FAST-LIVO2 and FAST-LIO2 behavior is unchanged except for consuming the shared normalized contract infrastructure.
7. Repository CI passes with no ROS installation required.
8. The greenhouse three-algorithm runtime smoke config points to the persistent KISS v1.3.0 overlay under `/home/yangxuan/lio_benchmark_dependencies`, never `/tmp`.
