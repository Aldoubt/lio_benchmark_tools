# Runtime Overlays Verification

## Scope

This note tracks the repository-side verification and target-machine acceptance gate for the frozen per-algorithm `runtime_overlays` contract.

The feature exists to make formal execution independent of algorithm-specific ROS overlays that happened to be sourced in the caller's interactive shell.

Current greenhouse KISS-ICP dependency:

```text
source checkout:
/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/src/kiss-icp

frozen setup script:
/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash

expected runtime package prefix:
/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/kiss_icp

KISS-ICP tag:
v1.3.0
```

No `/tmp` source/build/install path is part of the formal contract.

## Repository contract

A schema-v2 source manifest may declare ordered per-algorithm overlays:

```json
"runtime_overlays": {
  "kiss_icp": [
    "/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash"
  ]
}
```

The frozen execution environment is rebuilt in this order:

```text
/opt/ros/<distro>/setup.bash
        ->
<workspace>/install/setup.bash, when present
        ->
runtime_overlays[algorithm][0..N] in frozen order
        ->
runtime package evidence
        ->
runtime identity freeze
        ->
estimator startup
```

Before this chain is reconstructed, caller-owned ROS overlay path variables are removed so an undeclared ambient overlay cannot make formal preflight pass accidentally.

A declared overlay that is missing, not a regular file, fails to source, or still does not expose the registry-declared runtime ROS package is `BLOCKED_ENVIRONMENT`.

Runner exit code `65` is reserved for runtime-environment/overlay failure and is stored as `BLOCKED_ENVIRONMENT`, not `FAIL_ALGORITHM`.

## Runtime identity evidence

Immediately before estimator startup, every frozen setup script is fingerprinted and recorded in:

```text
metadata/algorithms/<algorithm>/runtime_identity.json
```

Expected overlay evidence shape:

```json
"runtime_overlays": [
  {
    "setup_path": "/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash",
    "setup_sha256": "<non-empty sha256>",
    "setup_size_bytes": 1
  }
]
```

The final registry-declared package prefix is recorded separately as `runtime_package_prefix`. The implementation does not guess which one of multiple overlays "owns" a package.

## Repository-side TDD evidence

The implementation was developed through RED/GREEN contract tests covering:

```text
manifest validation and frozen order
formal environment reconstruction
ambient overlay-path removal
missing/broken overlay fail-closed behavior
formal preflight package evidence
shell-safe overlay emission
runner source order
runtime identity setup-file fingerprints
runner exit-code 65 -> BLOCKED_ENVIRONMENT classification
```

The last implementation-only HEAD before documentation was:

```text
89b522e27c7de5ad3d8f54e73ea6a6462d2597f6
```

GitHub Actions `Core Contracts` run `31933933560` completed successfully for that exact SHA, including Unit Contracts, Python compile, shell adapter syntax, and registry smoke.

The user-facing documentation HEAD immediately before this verification note was updated was:

```text
1549f074fd6ac6ae509c8de23cfe283e115782a0
```

GitHub Actions `Core Contracts` run `31934101690` also completed successfully for that exact SHA, with all of the following successful:

```text
Baseline suite registry contract
Unit Contracts
Compile Python sources
Shell adapter syntax
Registry smoke
```

Because this verification note update creates one final documentation commit after `1549f074...`, the exact final repository HEAD must still receive one last successful `Core Contracts` run before repository-side completion is claimed.

## Target-machine acceptance — PENDING

Repository CI does not contain ROS2 Humble or the user's persistent KISS workspace. Therefore the following acceptance remains **PENDING** until it is run on the target machine and the resulting output is reviewed.

Start from a fresh shell and intentionally source only the base ROS distro:

```bash
cd /home/yangxuan/lio_benchmark_tools
git pull --ff-only
source /opt/ros/humble/setup.bash
```

Do **not** manually source either of these before formal preflight/run:

```text
/home/yangxuan/agt_navigation_v2/install/setup.bash
/home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash
```

Create a new run ID. Do not reuse an older debug/smoke run:

```bash
CONFIG=/home/yangxuan/lio_benchmark_tools/benchmark_base/config/green_house_three_runtime_smoke.json
RUN_ID="green_house_runtime_overlay_$(date +%Y%m%d_%H%M%S)"
RUN="/home/yangxuan/lio_benchmark_runs/green_house/$RUN_ID"
export RUN

benchmark_base/bin/lio-benchmark validate --config "$CONFIG"
benchmark_base/bin/lio-benchmark init --config "$CONFIG" --run-id "$RUN_ID"
benchmark_base/bin/lio-benchmark snapshot --run "$RUN"

benchmark_base/bin/lio-benchmark preflight \
  --run "$RUN" \
  --allow-diagnostic-calibration

echo "preflight rc=$?"
```

Required result:

```text
FAST-LIVO2 -> BLOCKED_CALIBRATION, runnable=true, diagnostic_only=true
FAST-LIO2  -> BLOCKED_CALIBRATION, runnable=true, diagnostic_only=true
KISS-ICP   -> PASS, runnable=true, diagnostic_only=false
preflight rc=0
```

Then run KISS-ICP only, still without manually sourcing its workspace:

```bash
benchmark_base/bin/lio-benchmark run \
  --run "$RUN" \
  --algorithm kiss_icp \
  --allow-diagnostic-calibration

echo "kiss run rc=$?"
```

Inspect the frozen identity:

```bash
python3 - <<'PY'
import json
import os
from pathlib import Path

run = Path(os.environ["RUN"])
path = run / "metadata/algorithms/kiss_icp/runtime_identity.json"
data = json.load(path.open())

print("identity_status =", data.get("identity_status"))
print("runtime_package =", data.get("runtime_package"))
print("runtime_package_prefix =", data.get("runtime_package_prefix"))
print("runtime_overlays =", json.dumps(data.get("runtime_overlays"), indent=2))
print("source =", json.dumps(data.get("source"), indent=2))
PY

cat "$RUN/metadata/run_kiss_icp.json"
find "$RUN/raw/kiss_icp" -maxdepth 2 -print
```

Required identity evidence:

```text
identity_status = FROZEN
runtime_package = kiss_icp
runtime_package_prefix = /home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/kiss_icp
runtime_overlays[0].setup_path = /home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash
runtime_overlays[0].setup_sha256 = non-empty
runtime_overlays[0].setup_size_bytes > 0
```

Only after this fresh-shell KISS acceptance succeeds should the full three-algorithm runtime smoke and `trajectory-from-run -> frame audit -> Common Scan Manifest -> Unified Map` chain be run.

## Scientific boundary

This feature changes only runtime-environment reproducibility and provenance. It does not change estimator parameters, calibration values, tracked-frame semantics, world gauge, trajectory standardization, display alignment, or accuracy scoring.

The greenhouse LiDAR-IMU calibration remains blocked/unconfirmed, so FAST-LIVO2 and FAST-LIO2 results from this smoke remain diagnostic-only even if runtime overlay acceptance succeeds.
