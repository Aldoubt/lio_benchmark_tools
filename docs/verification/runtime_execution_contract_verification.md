# Runtime Execution Contract Verification

## 1. Scope

This verification covers the repository-side Runtime Execution Contract implemented from:

```text
docs/superpowers/specs/2026-08-16-runtime-execution-contract-design.md
docs/superpowers/plans/2026-08-16-runtime-execution-contract.md
```

It verifies source-manifest replay/executable overrides, fail-closed execution resolution, immutable runtime identity artifacts, FAST-LIO2 direct executable execution, three-algorithm frozen replay wiring, Common Scan Manifest coupling, identity-first provenance, and diagnostic bundle integration.

This document does **not** claim that the new contract has already passed a fresh real-machine three-algorithm replay. That target-machine gate remains pending and must use a new run ID.

## 2. Repository contract status

Status:

```text
REPOSITORY_CONTRACT_VERIFIED
TARGET_MACHINE_SMOKE_PENDING
```

The latest repository verification before this note was GitHub Actions workflow:

```text
Core Contracts
run id: 31928004641
head: f7136db53e457a6a1aad0133d0af930284539150
conclusion: success
```

Successful steps:

```text
Baseline suite registry contract
Unit contracts
Compile Python sources
Shell adapter syntax
Registry smoke
```

A fresh CI run is still required after this verification note commit before declaring the branch implementation complete.

## 3. Frozen source-manifest contract

Schema-v2 experiment manifests now accept optional:

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

Resolution rules:

```text
EXPLICIT_EXECUTABLE_OVERRIDE
REGISTRY_DEFAULT_EXECUTION
```

No guessed `$HOME` / `$WORKSPACE/build` discovery path exists.

Invalid explicit executable paths are classified as:

```text
BLOCKED_EXECUTION
```

and are not silently replaced by a registry-default binary.

Existing manifests without the new blocks remain valid with:

```text
execution_overrides = {}
replay.rate = 1.0
replay.start_offset_s = 0.0
replay.duration_s = null
```

## 4. Runtime identity contract

New helper:

```text
benchmark_base/lib/execution_contract.py
```

The contract freezes a direct executable using:

```text
strict realpath
SHA256
file size
mtime_ns
```

and writes one immutable artifact per algorithm/run:

```text
metadata/algorithms/<algorithm>/runtime_identity.json
```

A frozen identity records separate dimensions for:

```text
identity_status
blocking_reason
resolution_method
requested/resolved executable
binary fingerprint
registry package
runtime package / package prefix
source git evidence
source_relationship
effective command
effective config + SHA256
workspace / ROS distro
dataset bag
replay interval
```

`source_relationship` is descriptive and independent from execution resolution:

```text
REGISTRY_MATCH
REGISTRY_MISMATCH
UNKNOWN_SOURCE
```

An explicit binary override can therefore be exactly reproducible without pretending it is the registry-default implementation.

An existing runtime identity blocks silent same-run reruns. A new run ID is required.

## 5. Runner-side freeze point

Runtime identity is frozen inside the algorithm runner after ROS/workspace setup and before estimator startup.

Helpers:

```text
evaluators/emit_runtime_env.py
evaluators/freeze_runtime_identity.py
```

This avoids relying on a later shell to reconstruct `ros2 pkg prefix` or package/source state.

The first finite-replay target-machine migration covers:

```text
FAST-LIVO2
FAST-LIO2
KISS-ICP
```

Each runner consumes frozen:

```text
BENCHMARK_REPLAY_RATE
BENCHMARK_REPLAY_START_OFFSET_S
BENCHMARK_REPLAY_DURATION_S
```

Compatibility `BAG_*` values are derived from the same frozen contract rather than overriding it.

Other baseline adapters must not be described as finite-replay verified until their runner migration is completed and tested.

## 6. FAST-LIO2 explicit executable path

For:

```text
resolution_method = EXPLICIT_EXECUTABLE_OVERRIDE
```

FAST-LIO2 runs the frozen binary directly:

```text
<resolved executable> --ros-args --params-file <run-local benchmark.yaml>
```

The adapter no longer contains guessed paths such as:

```text
/home/yangxuan/RM-NAV/build/...
$WORKSPACE/build/fast_lio/...
```

The machine-specific path lives only in the experiment config and frozen run manifest.

The generated FAST-LIO2 YAML also preserves numeric extrinsic values as floating-point YAML scalars (`1.0`, `0.0`, etc.), matching the behavior required by the working local smoke path.

## 7. Replay and Common Scan Manifest coupling

`benchmark_base/lib/map_sampling.py` now resolves scan windows with explicit evidence source:

```text
RUN_MANIFEST_REPLAY
CLI_OVERRIDE
LEGACY_REPLAY_WINDOW
FULL_BAG_DEFAULT
```

`evaluators/build_scan_manifest.py` consumes the frozen run replay by default.

Therefore a 15-second smoke no longer requires a manual `--duration-s 15` command to avoid using the rest of a 623-second source bag as the unmatched denominator.

Explicit CLI scan-window arguments remain derived diagnostics and are labeled `CLI_OVERRIDE`.

## 8. Identity-first runtime provenance

New-run evidence order:

```text
runtime_identity.json
        ↓
trajectory frame audit
        ↓
post-run source/package enrichment
        ↓
provenance verdict
```

New run:

```text
identity_evidence_source = RUNTIME_IDENTITY
```

Historical run without runtime identity:

```text
identity_evidence_source = LEGACY_RECONSTRUCTED
```

Frame semantics remain independent. A frozen FAST-LIO2 binary does not make an observed `odom -> sensor` frame label equal to the registry-declared `camera_init -> body` contract.

## 9. Diagnostic bundle integration

The default diagnostic bundle now includes existing:

```text
metadata/algorithms/<algorithm>/runtime_identity.json
```

Missing identities are recorded as missing evidence without failing bundle creation.

Executable binaries are never copied into the bundle.

## 10. Target-machine smoke configuration

Dedicated configuration:

```text
benchmark_base/config/green_house_three_runtime_smoke.json
```

It freezes:

```text
workspace: /home/yangxuan/agt_navigation_v2
output root: /home/yangxuan/lio_benchmark_runs/green_house
dataset: green_house_mid360
algorithms: fast_livo2, fast_lio2, kiss_icp
FAST-LIO2 explicit executable: /home/yangxuan/RM-NAV/build/fast_lio/fastlio_mapping
replay: 15 seconds at 1.0x
```

The manifest contract test validates this config without pretending CI has the target machine paths.

## 11. Required target-machine validation

Use a new run ID, for example:

```bash
cd /home/yangxuan/lio_benchmark_tools

CONFIG=benchmark_base/config/green_house_three_runtime_smoke.json
RUN_ID=green_house_runtime_contract_smoke_001

benchmark_base/bin/lio-benchmark validate --config "$CONFIG"
benchmark_base/bin/lio-benchmark init --config "$CONFIG" --run-id "$RUN_ID"
RUN=/home/yangxuan/lio_benchmark_runs/green_house/$RUN_ID

for ALG in fast_livo2 fast_lio2 kiss_icp; do
  benchmark_base/bin/lio-benchmark run \
    --run "$RUN" \
    --algorithm "$ALG" \
    --allow-diagnostic-calibration || break
done

benchmark_base/bin/lio-benchmark standardize scan-manifest --run "$RUN"

benchmark_base/bin/lio-benchmark audit trajectory-frames \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp

benchmark_base/bin/lio-benchmark audit runtime-provenance \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp

for ALG in fast_livo2 fast_lio2 kiss_icp; do
  benchmark_base/bin/lio-benchmark standardize map \
    --run "$RUN" --algorithm "$ALG"
done

benchmark_base/bin/lio-benchmark bundle --run "$RUN"
```

Target gate:

```text
3 runtime identity artifacts exist
FAST-LIO2 resolution_method = EXPLICIT_EXECUTABLE_OVERRIDE
FAST-LIO2 resolved executable and SHA256 are non-empty
all three runtime identities record replay.duration_s = 15.0
Common Scan Manifest source = RUN_MANIFEST_REPLAY
runtime provenance uses RUNTIME_IDENTITY when identity is available
frame audit remains an independent verdict
no historical run is overwritten
```

Because the green-house LiDAR–IMU calibration is still `BLOCKED_CALIBRATION`, this smoke remains diagnostic-only and cannot become an accuracy ranking.

## 12. Next phase gate

Relative SE(3) Motion Benchmark implementation starts only after the fresh target-machine bundle is reviewed.

Required inputs for that phase:

```text
frozen runtime identity
known tracked physical frame
canonical static LiDAR↔IMU transform
fresh three-algorithm trajectories
```

Then the benchmark can derive:

```text
common physical tracked frame
ΔT(t) = T(t0)^-1 T(t)
pairwise translation disagreement
SO(3) geodesic disagreement
event onset / peak diagnostics
```

This must remain diagnostic-only wherever calibration is unconfirmed.
