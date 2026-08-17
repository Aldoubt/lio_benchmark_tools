# Mid-360 Factory Extrinsic Semantics & Provenance Closure Design

## 1. Purpose

Close the remaining LiDAR/IMU extrinsic ambiguity for the Livox Mid-360 benchmark without performing a new calibration experiment. The Mid-360 LiDAR and IMU in this dataset are the internal sensors of the same factory-integrated unit, so the benchmark shall freeze the manufacturer-defined internal geometry, make the transform direction explicit, and force every consumer to use one canonical transform.

This change is a semantic/provenance correction. It does not create ground truth, does not alter historical run artifacts, and does not justify accuracy or ATE claims.

## 2. Coordinate notation

Use the convention

`T_AB` maps coordinates expressed in frame `B` into frame `A`:

`p_A = R_AB * p_B + t_AB`.

Frames:

- `L`: Mid-360 LiDAR / point-cloud frame.
- `I`: Mid-360 internal IMU frame.

The benchmark canonical transform is **LiDAR to IMU**:

`T_IL` with

`p_I = R_IL * p_L + t_IL`.

This equation is part of the data contract and must be stored explicitly so field names are never interpreted from prose alone.

## 3. Manufacturer geometry and canonical transform

The manufacturer geometry is recorded independently as the internal IMU origin expressed in the LiDAR frame:

`^L p_I = [+0.011, +0.02329, -0.04412] m`.

The LiDAR and internal IMU axes are treated as aligned for this Mid-360 factory geometry:

`R_LI = I`.

Therefore the benchmark canonical inverse transform is:

`R_IL = I`

`t_IL = [-0.011, -0.02329, +0.04412] m`.

The registry must preserve both facts:

1. manufacturer-reported point-location evidence: `manufacturer_imu_origin_in_lidar_m = [+0.011, +0.02329, -0.04412]`;
2. canonical executable transform: `translation_lidar_to_imu_m = [-0.011, -0.02329, +0.04412]`.

The two vectors are negatives only because the rotation is identity. Code must continue to use a general rigid-transform inverse rather than encode a sign-flip shortcut.

## 4. Provenance status

Introduce calibration status:

`MANUFACTURER_SPEC`

It means:

- sensor identity is a factory-integrated Mid-360 LiDAR plus its internal IMU;
- geometry comes from the Mid-360 manufacturer specification and the official FAST-LIO Mid-360 configuration/definition;
- no per-device re-estimation is required for this benchmark contract;
- online extrinsic estimation remains disabled;
- the transform is scientifically usable as a fixed sensor specification, not a diagnostic placeholder.

`MANUFACTURER_SPEC` joins `CONFIRMED` and `VERIFIED` as a usable calibration status for preflight and physical-frame normalization.

It is intentionally not named `VERIFIED`: the source category remains visible and distinguishes a manufacturer-defined integrated-sensor transform from a separately estimated experimental calibration.

## 5. Dataset registry contract

`benchmark_base/registry/datasets/green_house_mid360.json` shall carry:

- `canonical_convention`: `LIDAR_TO_IMU`
- `canonical_equation`: `p_I = R_IL * p_L + t_IL`
- `rotation_lidar_to_imu_row_major`: identity
- `translation_lidar_to_imu_m`: `[-0.011, -0.02329, +0.04412]`
- `manufacturer_imu_origin_in_lidar_m`: `[+0.011, +0.02329, -0.04412]`
- `status`: `MANUFACTURER_SPEC`
- `source_type`: `MANUFACTURER_SPEC`
- `sensor_model`: `Livox Mid-360`
- `imu_relation`: `INTERNAL_IMU`
- `online_extrinsic_estimation`: `false`
- source references identifying the Livox Mid-360 specification and the official hku-mars FAST-LIO Mid-360 extrinsic convention/configuration.

The old legacy statement that the numeric calibration is unverified for this bag must be removed from the active dataset registry. Historical frozen manifests keep their original status and values unchanged.

## 6. Consumer contracts

### 6.1 FAST-LIO2

FAST-LIO2 declares `extrinsic_convention = LIDAR_TO_IMU` and receives canonical `T_IL` directly.

Generated FAST-LIO2 configuration must contain:

- `extrinsic_est_en: false`
- `extrinsic_T: [-0.011, -0.02329, +0.04412]`
- identity `extrinsic_R`.

### 6.2 FAST-LIVO2

FAST-LIVO2 also declares `extrinsic_convention = LIDAR_TO_IMU` and must receive the same canonical `T_IL` directly.

The benchmark must not rely on the external `agt_navigation_v2` package's default Mid-360 YAML because that file currently contains the old positive vector. The benchmark shall generate a run-local FAST-LIVO2 parameter file from benchmark-owned configuration/template data, inject the frozen canonical transform, and launch `fast_livo2_mapping.launch.py` with an explicit `params_file:=...` argument.

This avoids modifying the external runtime repository and makes the effective extrinsic part of run-local benchmark evidence.

Required values:

- fixed/disabled online extrinsic estimation if the runtime exposes such a switch;
- `extrinsic_T: [-0.011, -0.02329, +0.04412]`;
- identity `extrinsic_R`.

### 6.3 KISS-ICP

KISS-ICP remains LiDAR-only and keeps `extrinsic_convention = NONE` during estimator execution.

Its trajectory represents the LiDAR frame. Whenever a comparison requires `IMU_BODY`, the benchmark physical-frame normalizer uses canonical `T_IL` and its mathematical inverse as required by pose composition.

### 6.4 Relative SE(3)

For a LiDAR-tracked world pose `T_WL`, the desired IMU pose is:

`T_WI = T_WL * T_LI = T_WL * inverse(T_IL)`.

The existing Relative SE(3) composition rule is retained; fixing the canonical registry sign makes the lever-arm correction correct.

Relative SE(3) remains:

- target physical frame `IMU_BODY`;
- no estimator-to-estimator fitting;
- `PAIRWISE_DISAGREEMENT` terminology;
- ground truth `NONE`.

With usable manufacturer-spec calibration and all engineering gates passing, pair rows may be labeled `DESCRIPTIVE_NO_GROUND_TRUTH` rather than calibration-driven `DIAGNOSTIC_ONLY`.

### 6.5 Unified Map

For IMU-tracked trajectories, LiDAR scan points are converted as:

`p_I = R_IL * p_L + t_IL`.

Therefore Unified Map reconstruction must consume the same negative canonical translation. KISS maps remain LiDAR-tracked and use identity scan-frame conversion before trajectory/world placement.

P2 strict common-scan intersection remains unchanged.

## 7. Calibration helper contract

`benchmark_base/lib/calibration.py` remains the only canonical rigid-transform resolver.

Requirements:

- `MANUFACTURER_SPEC` is a usable calibration status;
- `canonical_lidar_to_imu()` returns `T_IL` exactly as defined above;
- `invert_transform()` remains the sole generic inverse implementation;
- generated calibration evidence records canonical convention/equation, source type, sensor model, internal-IMU relation, and manufacturer point-location evidence when available;
- `diagnostic_only=false` for `MANUFACTURER_SPEC`.

Preflight must reuse the shared usable-status constant rather than maintain a second hard-coded `{CONFIRMED, VERIFIED}` set.

## 8. Historical-run immutability

All existing run directories and bundles produced before this correction are historical evidence and must not be edited, regenerated in place, or semantically relabeled.

In particular, previous Relative SE(3) values involving KISS and previous Unified Maps were generated under the old canonical sign and remain diagnostic historical artifacts.

After implementation, the three-algorithm comparison must start from a **fresh run** with a new frozen manifest.

## 9. Regression evidence

Unit/contracts must prove at least:

1. green-house registry canonical `T_IL` is identity + `[-0.011, -0.02329, +0.04412]`;
2. manufacturer point-location evidence remains `[+0.011, +0.02329, -0.04412]`;
3. inverse `T_LI` returns the positive vector;
4. `MANUFACTURER_SPEC` passes LIO preflight without `--allow-diagnostic-calibration`;
5. resolved FAST-LIO2 and FAST-LIVO2 calibration is negative `T_IL` and not diagnostic-only;
6. FAST-LIO2 generated YAML contains the negative vector and fixed extrinsic estimation;
7. FAST-LIVO2 benchmark-owned run-local YAML contains the negative vector, and its runner explicitly passes that file;
8. Unified Map LiDAR→IMU point conversion uses negative `t_IL`;
9. Relative SE(3) LiDAR trajectory normalization right-multiplies `inverse(T_IL)`, yielding positive `T_LI` for this Mid-360 geometry;
10. historical run files are never rewritten by this implementation.

## 10. Fresh unified comparison acceptance

After exact-head CI passes, a fresh target-machine run shall execute:

- FAST-LIVO2
- FAST-LIO2
- KISS-ICP

with no diagnostic-calibration override required for the two LIO algorithms.

The acceptance must freeze and report:

- dataset calibration status/source and canonical equation;
- canonical `T_IL` and inverse `T_LI`;
- each algorithm's generated/effective extrinsic convention and values;
- runtime identity/provenance/frame gates;
- trajectory coverage;
- strict common scan manifest;
- three strict Unified Maps;
- Relative SE(3) outputs;
- trajectory and common-manifest immutability;
- diagnostic bundle.

The new comparison supersedes prior sign-ambiguous numerical comparison for future analysis, but does not delete or overwrite the old results.

## 11. Scientific boundary after closure

Successful closure removes **calibration ambiguity** as the reason for `DIAGNOSTIC_ONLY`.

It does not add ground truth. Therefore:

- allowed: descriptive trajectory/map comparison, pairwise disagreement, relative behavior analysis;
- not allowed without GT: accuracy ranking, ATE/RPE truth claims, or statements that one estimator is objectively more accurate.
