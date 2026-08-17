# Mid-360 Factory Extrinsic Semantics & Provenance Verification

Date: 2026-08-17

Branch:

```text
feat/lio-baseline-suite
```

## Scope

This verification closes the benchmark-side ambiguity between:

```text
manufacturer point-location evidence:
^L p_I = [+0.011, +0.02329, -0.04412] m
```

and the canonical transform required by FAST-LIO-family LiDAR-to-IMU semantics:

```text
T_IL
p_I = R_IL * p_L + t_IL
R_IL = I
t_IL = [-0.011, -0.02329, +0.04412] m
```

The inverse used when converting a LiDAR-tracked world pose to an IMU-tracked world pose is:

```text
T_LI = inverse(T_IL)
t_LI = [+0.011, +0.02329, -0.04412] m
```

Calibration provenance is now:

```text
status       = MANUFACTURER_SPEC
source_type  = MANUFACTURER_SPEC
sensor_model = Livox Mid-360
imu_relation = INTERNAL_IMU
online_extrinsic_estimation = false
```

This is a fixed integrated-sensor specification, not a newly fitted calibration.

## Task 1 — canonical registry / preflight closure

RED commit:

```text
04194916c5fcd70e23590fac0942f2ffa56b26b7
```

The exact-head Core Contracts run failed because the active registry still contained the old positive vector under `LIDAR_TO_IMU`, lacked manufacturer evidence fields, and remained `BLOCKED_CALIBRATION`.

GREEN implementation HEAD:

```text
72c0906e3d9f6e081b9f3af743b1d336358c55ab
```

Exact-head Core Contracts run:

```text
31983509956 = completed / success
```

Verified contracts:

```text
canonical T_IL = identity + [-0.011,-0.02329,+0.04412]
manufacturer ^L p_I = [+0.011,+0.02329,-0.04412]
inverse T_LI = identity + [+0.011,+0.02329,-0.04412]
MANUFACTURER_SPEC is usable by preflight
LIO calibration is no longer diagnostic-only
manufacturer/source/sensor semantics propagate into generated calibration evidence
```

## Task 2 — FAST-LIVO2 effective run-local configuration

RED commit:

```text
027cfb57692b688fe3af79fe7c2e76a7116079cd
```

The runner did not yet generate or pass a benchmark-owned parameter file.

The implementation added:

```text
benchmark_base/config/templates/fast_livo2_mid360.yaml.in
evaluators/prepare_fast_livo2_config.py
```

and changed `run_fast_livo_test.sh` to generate:

```text
configs/generated/fast_livo2/runtime_params.yaml
configs/generated/fast_livo2/adapter_config_metadata.json
```

before runtime identity is frozen, then launch with an explicit:

```text
params_file:=<run-local runtime_params.yaml>
```

The first implementation exposed binary float expansion in YAML text; this was deliberately tightened so the effective extrinsic remains human-auditable.

Final Task 2 exact-head HEAD:

```text
7642e346a80841543624f77110385ed84f5299ee
```

Core Contracts run:

```text
31983678228 = completed / success
```

## Task 3 — downstream direction contracts

Directional regression commit:

```text
8e85a4334266193c102ed3559bde14eaaf442b59
```

This produced one intentional RED failure: FAST-LIO2 YAML still printed the mathematically correct negative vector as binary-expanded decimals.

The same run proved the existing downstream math was already directionally correct:

```text
Unified Map IMU_BODY conversion: PASS with negative canonical T_IL
Relative SE(3) KISS LiDAR->IMU pose conversion: PASS with positive inverse T_LI
```

FAST-LIO2 serialization was tightened without changing estimator math.

Final Task 3 HEAD:

```text
cb745ff636fdc3d9073e53cff0a07cb4a3bd9ab5
```

Core Contracts run:

```text
31983832797 = completed / success
```

## Bundle provenance closure

A new RED bundle contract required available run-local generated calibration/effective parameter files to be included as optional small evidence:

```text
689d7141c736180aa84654199992a0c504453dce
```

The implementation now includes, when present:

```text
configs/generated/<algorithm>/calibration.json
configs/generated/<algorithm>/adapter_config_metadata.json
configs/generated/<algorithm>/runtime_params.yaml
configs/generated/<algorithm>/benchmark.yaml
```

These files remain optional for historical runs and do not make old bundles incomplete.

Bundle implementation HEAD:

```text
eb17787291bcd1b8da3f7db9731fdd2ad32df5a1
```

Core Contracts run:

```text
31983938595 = completed / success
```

Large/raw artifacts remain excluded.

## FAST-LIVO2 effective-config runtime fingerprint closure

The run-local FAST-LIVO2 YAML is both the scientific parameter evidence and the actual launch input, so its contents must be frozen by runtime identity rather than only appearing as a path inside the effective command.

RED commit:

```text
e87553c772dfa2a0465ceb707fdc74b5d0674f58
```

The exact-head run had 246 unit contracts with one intended failure: the FAST-LIVO2 runner did not pass its run-local YAML to `freeze_runtime_identity.py --effective-config`.

GREEN implementation HEAD:

```text
dbc49485462d4a29530b4b3fa8b8512968ee0b46
```

Core Contracts run:

```text
31984190234 = core job completed / success
```

The runtime identity for a fresh FAST-LIVO2 run will now fingerprint the same `runtime_params.yaml` passed through `params_file:=...`, allowing its SHA256/size/path to be independently checked against the bundled generated config evidence.

## Historical-run rule

All previously frozen runs are immutable historical evidence.

Runs created before this closure used the old sign-ambiguous canonical value. Their runtime/provenance pipeline evidence remains valid for the state that was frozen at the time, but their KISS-to-IMU lever-arm corrected numerical comparisons and IMU-body Unified Map reconstructions are not promoted into the new baseline.

No historical `manifest.json`, Relative SE(3) artifact, map, bundle, or runtime identity is rewritten.

## Scientific interpretation

Successful factory-extrinsic closure removes `BLOCKED_CALIBRATION` as a blocker for this integrated Mid-360 dataset.

It does **not** create ground truth.

Therefore the fresh comparison remains:

```text
ground_truth = NONE
terminology = PAIRWISE_DISAGREEMENT
scientific interpretation = DESCRIPTIVE_NO_GROUND_TRUTH
```

It may support descriptive divergence, map consistency, runtime, temporal-coverage and robustness analysis, but not ATE/RPE truth claims or objective accuracy ranking.

## Fresh target-machine three-algorithm acceptance — PENDING

A fresh persistent run is mandatory. Do not reuse any pre-closure run.

Target acceptance must verify:

```text
repository exact HEAD is the final P3 documentation HEAD
frozen dataset calibration status = MANUFACTURER_SPEC
preflight PASS without --allow-diagnostic-calibration
FAST-LIVO2 effective config T_IL = [-0.011,-0.02329,+0.04412]
FAST-LIO2 effective config T_IL = [-0.011,-0.02329,+0.04412]
FAST-LIVO2 runtime identity effective-config SHA matches runtime_params.yaml
FAST-LIO2 runtime identity effective-config SHA matches benchmark.yaml
FAST-LIVO2/FAST-LIO2 online extrinsic estimation remains disabled/fixed
KISS remains LiDAR-only
runtime identity FROZEN x3
runtime provenance MATCH x3
frame contract MATCH x3
trajectory coverage evidence available
strict common matched scan manifest valid
strict Unified Maps use identical common scan population
Relative SE(3) rerun from fresh trajectories
diagnostic bundle contains generated config/calibration evidence
```

Acceptance state:

```text
FRESH_FACTORY_EXTRINSIC_ACCEPTANCE = PENDING
NEW_UNIFIED_THREE_ALGORITHM_BASELINE = PENDING
```
