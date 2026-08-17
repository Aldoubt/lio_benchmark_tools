# MID360 Bag Intake V1 Design

Date: 2026-08-17
Branch: `feat/lio-baseline-suite`

## 1. Purpose

`MID360 Bag Intake V1` turns an arbitrary local ROS 2 bag containing Livox MID360 LiDAR data and IMU data into an auditable dataset contract that can be consumed by the existing LIO Benchmark Tools V2 workflow without manually editing a tracked dataset registry file.

The feature is intentionally limited to dataset intake. It does not run estimators, create benchmark runs, reconstruct maps, generate reports, or add new algorithm adapters.

The desired user flow is:

```bash
lio-benchmark dataset probe \
  --bag /absolute/path/to/my_mid360_bag

lio-benchmark dataset freeze \
  --probe /absolute/path/to/probe.json \
  --dataset-id my_mid360_dataset \
  --lidar-topic /livox/lidar \
  --imu-topic /livox/imu \
  --profile mid360-internal \
  --output /absolute/path/to/datasets/my_mid360_dataset
```

The resulting directory is directly usable as dataset evidence for a later Suite Orchestrator phase:

```text
datasets/my_mid360_dataset/
├── inspection.json
└── dataset.json
```

## 2. Non-goals

V1 explicitly does not implement:

- `suite run`, `suite resume`, or benchmark stage orchestration;
- estimator execution;
- automatic algorithm selection;
- Point-LIO, DLIO, Leg-KILO, LIO-SAM, GLIM, or other new runtime acceptance work;
- automatic sensor extrinsic calibration;
- automatic topic remapping;
- bag rewriting or conversion;
- automatic correction of IMU units;
- camera intake;
- ROS 1 bag support;
- MCAP-specific support beyond what the existing ROS 2 bag reader can open;
- committing generated machine-local dataset records into `benchmark_base/registry/datasets/`;
- any ground-truth or map-accuracy evaluation.

## 3. Existing code to preserve and reuse

The implementation must reuse existing project boundaries rather than create a parallel framework.

### 3.1 Existing bag evidence reader

`evaluators/analyze_bag.py` already performs read-only ROS 2 bag inspection and records:

- topic names and message types;
- message counts;
- rosbag recorded timestamps;
- header timestamps;
- timestamp reversals;
- frame IDs;
- PointCloud2 fields or sampled Livox `CustomMsg` point semantics;
- IMU acceleration and angular velocity statistics;
- LiDAR-to-nearest-IMU header-time difference.

MID360 Bag Intake V1 must extract/reuse the underlying read-only inspection logic rather than maintain a second rosbag parser.

### 3.2 Existing dataset registry schema

The current `Registry._validate_dataset()` contract requires schema v2 dataset records to expose at least:

```text
dataset_id
bag_dir
environment
acquisition
topics.lidar
topics.imu
types.lidar
types.imu
timestamp.point_time_field
timestamp.point_time_unit
calibration.rotation_lidar_to_imu_row_major[9]
calibration.translation_lidar_to_imu_m[3]
```

The frozen dataset artifact produced by Intake V1 must remain compatible with this semantic shape so later benchmark manifests can consume it without introducing a competing dataset model.

## 4. Core design choice

V1 separates three concepts that must never be silently conflated:

```text
Observed bag evidence
        ↓
Candidate interpretation
        ↓
Frozen user-approved dataset contract
```

`probe` only records evidence and conservative candidates.

`freeze` converts a probe into an immutable dataset contract only after required ambiguous choices are explicit.

No candidate inference can silently become verified truth.

## 5. Command 1 — `dataset probe`

### 5.1 CLI

```bash
lio-benchmark dataset probe \
  --bag /absolute/path/to/bag \
  [--output /absolute/path/to/inspection.json]
```

Only these inputs are allowed in V1:

```text
--bag
--output (optional)
```

The probe command must not accept:

```text
--lidar-topic
--imu-topic
--extrinsic
--profile
--fix
--rewrite
--overwrite
```

Topic selection and calibration belong to `freeze`, not evidence collection.

### 5.2 Read-only behavior

`probe` must:

1. resolve the bag path to an absolute path;
2. verify the path exists and is a ROS 2 bag directory readable by the existing bag reader;
3. inspect all topics;
4. compute deterministic bag identity evidence;
5. write exactly one new JSON file;
6. refuse to overwrite an existing output file;
7. never modify the source bag.

If `--output` is omitted, default to:

```text
<bag-parent>/<bag-name>.lio_benchmark_probe.json
```

The default path must still be non-overwritable.

### 5.3 Bag identity

The probe must freeze an auditable bag identity without hashing terabytes of unrelated filesystem content.

For a ROS 2 bag directory, record:

```json
{
  "bag_dir": "/absolute/path/to/bag",
  "storage_files": [
    {
      "relative_path": "green-house_0.db3",
      "size_bytes": 123,
      "sha256": "..."
    }
  ],
  "metadata_yaml": {
    "relative_path": "metadata.yaml",
    "size_bytes": 123,
    "sha256": "..."
  },
  "bag_content_sha256": "..."
}
```

`bag_content_sha256` is a deterministic aggregate hash computed from the ordered `(relative_path, size_bytes, sha256)` records for rosbag storage files plus `metadata.yaml` when present.

It is not a hash of the absolute directory name, so moving an unchanged bag does not change content identity.

V1 supports the storage files actually present in the ROS 2 bag metadata/directory; it must not assume there is exactly one `.db3` file.

### 5.4 Probe output schema

The probe artifact uses:

```text
schema = lio_benchmark_dataset_probe/v1
```

Required top-level fields:

```text
schema
created_at
source
bag_identity
topics
candidate_roles
timestamp_evidence
imu_evidence
sensor_candidates
limitations
```

`source` includes the resolved bag path and records that the artifact is read-only evidence.

### 5.5 Topic evidence

For every topic record:

```text
name
type
message_count
recorded_first_s
recorded_last_s
recorded_dt_median_s
recorded_rate_hz
recorded_time_reversal_count
header_first_s
header_last_s
header_dt_median_s
header_rate_hz
header_time_reversal_count
frame_ids
point_fields
```

Rates are descriptive and may be null when insufficient samples exist.

### 5.6 Candidate role classification

Candidate role classification is deterministic and conservative.

LiDAR candidates:

```text
livox_ros_driver2/msg/CustomMsg
sensor_msgs/msg/PointCloud2
```

IMU candidates:

```text
sensor_msgs/msg/Imu
```

The probe records all candidates and a recommendation only when there is exactly one unambiguous candidate for a role.

Examples:

```json
"candidate_roles": {
  "lidar": {
    "candidates": ["/livox/lidar"],
    "recommended": "/livox/lidar",
    "status": "UNAMBIGUOUS"
  },
  "imu": {
    "candidates": ["/livox/imu"],
    "recommended": "/livox/imu",
    "status": "UNAMBIGUOUS"
  }
}
```

If two LiDAR topics exist:

```text
status = AMBIGUOUS
recommended = null
```

The tool must not choose based on topic-name popularity such as `/livox/lidar`.

### 5.7 MID360 candidate classification

The probe may identify a sensor as a `MID360_CANDIDATE` only from observable message/layout evidence such as Livox `CustomMsg` plus expected sampled fields/time semantics.

Allowed status values:

```text
MID360_CANDIDATE
LIVOX_CUSTOM_CANDIDATE
POINTCLOUD2_LIDAR_CANDIDATE
UNKNOWN
```

The probe must not claim `MID360_VERIFIED` based only on bag message layout.

## 6. Command 2 — `dataset freeze`

### 6.1 CLI

```bash
lio-benchmark dataset freeze \
  --probe /absolute/path/to/inspection.json \
  --dataset-id my_mid360_dataset \
  --lidar-topic /livox/lidar \
  --imu-topic /livox/imu \
  --profile mid360-internal \
  --output /absolute/path/to/datasets/my_mid360_dataset
```

Required inputs:

```text
--probe
--dataset-id
--lidar-topic
--imu-topic
--profile
--output
```

V1 profile set is exactly:

```text
mid360-internal
mid360-user-extrinsic
unknown-lidar-imu
```

Profile selection is explicit even when `probe` found unambiguous topics.

### 6.2 Output immutability

`freeze` writes exactly:

```text
<output>/inspection.json
<output>/dataset.json
```

Rules:

- `<output>` must not already exist;
- no `--overwrite` option exists;
- `inspection.json` is a byte-for-byte copy of the supplied probe artifact;
- `dataset.json` fingerprints the copied inspection artifact;
- failure must not leave a partially valid output directory; write through a temporary sibling/staging directory and atomically rename only after validation succeeds.

### 6.3 Dataset ID

`dataset_id` accepts only letters, numbers, underscore, and hyphen.

It must not depend on the bag filename and must be explicitly supplied by the user.

### 6.4 Topic gate

`freeze` verifies:

- requested LiDAR topic exists in the probe;
- requested IMU topic exists in the probe;
- topics are different;
- LiDAR type is one of the V1 supported LiDAR candidate types;
- IMU type is `sensor_msgs/msg/Imu`;
- each selected topic has at least one message;
- there are no recorded-time regressions in either selected topic;
- header-time evidence is available for both selected topics.

Header duplicate/regression evidence is preserved and classified; a non-monotonic selected timestamp source must fail closed rather than be sorted or repaired.

## 7. Calibration profiles

Calibration truth status is deliberately separate from sensor detection.

### 7.1 `mid360-internal`

This profile is only for a MID360 using its internal IMU geometry.

The dataset contract uses the already-established canonical project convention:

```text
canonical_convention = LIDAR_TO_IMU
p_I = R_IL * p_L + t_IL
```

and the repository's accepted manufacturer-spec MID360 internal LiDAR/IMU transform.

Status:

```text
MANUFACTURER_SPEC
```

The probe itself does not upgrade this status.

### 7.2 `mid360-user-extrinsic`

This profile requires explicit values:

```bash
--rotation-lidar-to-imu r00 r01 r02 r10 r11 r12 r20 r21 r22
--translation-lidar-to-imu tx ty tz
--calibration-source <free-text-label>
```

Status:

```text
USER_PROVIDED
```

V1 validates shape, finite numeric values, and rotation plausibility using the same mathematical standards already used by calibration helpers where possible.

It does not call a calibration solver and does not relabel the result as verified.

### 7.3 `unknown-lidar-imu`

This profile deliberately records unresolved calibration.

Because the current dataset schema requires a 9-value rotation and 3-value translation, V1 stores identity/zero placeholders only together with explicit blocking semantics:

```text
status = UNKNOWN
usable_for_lidar_imu_benchmark = false
placeholder_transform = true
```

Downstream preflight must continue to block LiDAR+IMU estimators until calibration becomes usable.

The placeholders must never be described as measured calibration.

## 8. Timestamp contract generation

V1 only auto-generates timestamp semantics when observable evidence and selected LiDAR message type support a known contract.

For Livox `CustomMsg`:

```text
point_time_field = offset_time
point_time_unit = ns_relative_to_timebase
scan_time_field = header.stamp
timebase_field = timebase
verified_from_bag = true
```

For generic `sensor_msgs/msg/PointCloud2`, V1 cannot assume the point-time field name/unit.

Therefore `freeze` with PointCloud2 must fail closed in V1 unless a later design adds an explicit timestamp override contract.

This keeps Intake V1 focused on the MID360/Livox CustomMsg path already used by the accepted greenhouse benchmark.

## 9. IMU unit semantics

The probe records raw numerical statistics but does not infer physical units from magnitude.

For `sensor_msgs/msg/Imu`, the frozen contract records ROS message semantic units:

```text
angular_velocity_unit = rad_s
linear_acceleration_unit = m_s2_message_semantics
```

If a known dataset or adapter uses non-standard raw scaling, that remains an explicit adapter/dataset-specific concern and must not be inferred by Intake V1 from a mean acceleration norm.

## 10. Frozen `dataset.json`

The generated artifact must remain compatible with registry dataset semantics and additionally records intake provenance.

Required structure includes:

```json
{
  "schema_version": 2,
  "dataset_id": "my_mid360_dataset",
  "bag_dir": "/absolute/path/to/bag",
  "sha256": "<bag_content_sha256>",
  "environment": "UNSPECIFIED",
  "acquisition": {
    "platform": "UNSPECIFIED",
    "route_type": "UNSPECIFIED",
    "camera_present": false
  },
  "topics": {
    "lidar": "/livox/lidar",
    "imu": "/livox/imu",
    "camera": null
  },
  "types": {
    "lidar": "livox_ros_driver2/msg/CustomMsg",
    "imu": "sensor_msgs/msg/Imu",
    "camera": null
  },
  "timestamp": {},
  "imu": {},
  "calibration": {},
  "intake": {
    "schema": "lio_benchmark_dataset_intake/v1",
    "profile": "mid360-internal",
    "inspection_sha256": "...",
    "bag_content_sha256": "...",
    "selected_topics_source": "EXPLICIT_USER_SELECTION"
  }
}
```

`environment` and acquisition context are `UNSPECIFIED` rather than guessed from directory names.

## 11. Consuming generated dataset contracts

P1 does not implement Suite Orchestrator, but the generated contract must be immediately consumable by the existing manifest-resolution layer without copying it into the repository registry.

V1 therefore adds one additive experiment-manifest path:

```json
{
  "dataset_file": "/absolute/path/to/datasets/my_mid360_dataset/dataset.json"
}
```

Rules:

- an experiment may specify either `dataset` (registry ID) or `dataset_file`, never both;
- `dataset_file` must be an absolute or manifest-relative JSON file;
- the loaded file must pass the same dataset schema validation as registry datasets;
- its `bag_dir` remains machine-local and is resolved exactly as frozen;
- the dataset file content and SHA256 are frozen into the run manifest at `init`;
- existing registry-ID manifests remain fully backward compatible.

This is the minimum bridge required for Intake V1 to be genuinely usable before Suite Orchestrator V1 exists.

## 12. Error and safety contract

Expected fail-closed categories/messages include:

```text
bag path missing
bag unreadable
probe output already exists
invalid probe schema
probe bag identity no longer matches current source bag
selected topic missing
selected topic type unsupported
ambiguous candidate requires explicit topic selection
non-monotonic selected timestamps
unsupported PointCloud2 point-time semantics
invalid dataset id
output directory already exists
invalid user extrinsic
unknown calibration blocks LiDAR+IMU use
both dataset and dataset_file specified
external dataset file fails schema validation
```

`freeze` must recompute current source bag content identity and compare it with the probe identity before writing the dataset contract. A probe made from an older version of the bag cannot silently freeze a changed bag.

## 13. Implementation boundaries

Expected focused units:

```text
benchmark_base/lib/bag_probe.py
    pure evidence normalization, hashing, candidate classification

benchmark_base/lib/dataset_intake.py
    freeze validation, profile resolution, dataset contract generation

benchmark_base/lib/registry.py
    expose reusable public dataset-record validation

benchmark_base/lib/manifest.py
    additive dataset_file resolution

 evaluators/probe_dataset.py
    ROS-aware thin reader entry point reusing/refactoring analyze_bag logic

 evaluators/freeze_dataset.py
    pure Python append/new-output writer; no ROS process execution

 benchmark_base/bin/lio-benchmark
    additive dataset probe/freeze CLI dispatch
```

Exact filenames may be adjusted in the implementation plan if existing module boundaries make a smaller change clearer, but the responsibilities must remain separated: ROS bag reading, pure evidence classification, contract freezing, and manifest consumption must not collapse into one large CLI function.

## 14. TDD contract

Implementation is strict RED -> GREEN.

Minimum test groups:

### 14.1 Pure probe classification tests

- one Livox CustomMsg + one IMU gives unambiguous candidates;
- multiple LiDAR candidates remain ambiguous;
- topic names do not influence role selection;
- aggregate bag identity is deterministic and independent of absolute directory path;
- storage-file order does not change aggregate hash;
- modified storage file changes bag identity.

### 14.2 Freeze tests

- valid `mid360-internal` probe writes a registry-valid dataset record;
- requested topic must exist and match type;
- changed source bag after probe is refused;
- existing output directory is refused;
- no partial output remains after a validation failure;
- copied inspection is byte-for-byte identical;
- dataset fingerprints the inspection;
- generated timestamp contract is exact for Livox CustomMsg;
- generic PointCloud2 freezes are refused in V1;
- user-provided extrinsic remains `USER_PROVIDED`;
- unknown calibration remains blocking and visibly placeholder-only.

### 14.3 Manifest bridge tests

- existing `dataset` registry ID remains supported;
- `dataset_file` works;
- specifying both fails;
- missing/invalid dataset file fails;
- external dataset is frozen into run manifest rather than referenced only by mutable path.

### 14.4 CLI tests

- `dataset probe` exposes only bag/output;
- `dataset freeze` exposes only frozen V1 arguments;
- no overwrite/fix/autodetect-calibration flags;
- freeze evaluator has no ROS dependency;
- probe path is the only ROS-aware intake path.

## 15. Repository acceptance

Repository-side acceptance requires the existing Core Contracts workflow to remain fully green at one exact HEAD, including:

```text
Baseline suite registry contract
Unit contracts
Python compile
Shell adapter syntax
Registry smoke
```

No target-machine PASS is claimed from CI because GitHub Actions does not contain the user's real MID360 bag/runtime environment.

## 16. Target-machine acceptance

Target acceptance is intentionally limited and does not execute any estimator.

Codex on the target machine must use a real local MID360 bag and perform:

```bash
lio-benchmark dataset probe --bag <real-mid360-bag> --output <new-probe>

lio-benchmark dataset freeze \
  --probe <new-probe> \
  --dataset-id mid360_intake_acceptance_<timestamp> \
  --lidar-topic <actual-lidar-topic> \
  --imu-topic <actual-imu-topic> \
  --profile mid360-internal \
  --output <new-dataset-dir>
```

The acceptance check must verify:

```text
probe schema = lio_benchmark_dataset_probe/v1
source bag absolute path matches target bag
bag storage files are SHA256 fingerprinted
bag_content_sha256 is present
selected LiDAR/IMU topics exist in probe
frozen inspection is byte-identical to probe
dataset schema_version = 2
dataset_id matches requested ID
LiDAR type = actual selected probe type
IMU type = sensor_msgs/msg/Imu
timestamp contract is Livox CustomMsg MID360 contract
calibration status = MANUFACTURER_SPEC
intake profile = mid360-internal
intake inspection SHA matches copied inspection
intake bag SHA matches probe bag identity
Registry dataset validation passes
an experiment manifest using dataset_file validates/resolves successfully
source bag files have not changed
```

Then print exactly:

```text
MID360_BAG_INTAKE_V1_TARGET_CONTRACT=PASS
```

No estimator, trajectory standardization, map reconstruction, Relative SE(3), report, or demo is run during P1 target acceptance.

## 17. Stop condition

After target acceptance PASS, stop this phase.

Do not begin `Benchmark Suite Orchestrator V1` in the same implementation task.

The next independent design begins only after MID360 Bag Intake V1 is frozen and accepted.
