# MID360 Bag Intake V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed, auditable intake path that turns a local ROS 2 Livox MID360 bag into an immutable `inspection.json` + registry-compatible `dataset.json`, and lets existing schema-v2 experiment manifests consume that external dataset through `dataset_file` without editing the tracked registry.

**Architecture:** Keep ROS-dependent bag reading isolated in a thin evaluator/shared reader, while bag identity, role/layout classification, freeze validation, calibration profile resolution, IMU unit semantics, and manifest loading remain pure Python and unit-testable in GitHub Actions. Reuse the current dataset schema and calibration convention; do not add Suite Orchestrator, estimator execution, map generation, or new adapters.

**Tech Stack:** Python 3.10, ROS 2 Humble/`rosbag2_py` only on target-machine probe path, `unittest`, existing `Registry`, `manifest`, `calibration`, CLI dispatcher, SHA-256 via stdlib `hashlib`.

## Global Constraints

- Branch: `feat/lio-baseline-suite`.
- Strict RED -> GREEN for every implementation task.
- Probe is read-only and exposes only `--bag` and optional `--output`.
- Freeze is non-overwritable and atomic; output contains exactly `inspection.json` and `dataset.json`.
- Do not infer MID360 physical model from topic names or Livox message layout.
- Do not infer IMU units from signal magnitude; unit labels are explicit CLI choices.
- V1 LiDAR freeze path accepts `livox_ros_driver2/msg/CustomMsg`; generic `PointCloud2` must fail closed because point-time semantics are unresolved.
- Calibration profiles are exactly `mid360-internal`, `mid360-user-extrinsic`, and `unknown-lidar-imu`.
- `mid360-internal` uses the already accepted manufacturer-spec canonical `LIDAR_TO_IMU` transform.
- `mid360-user-extrinsic` is `USER_PROVIDED`, never automatically upgraded to verified.
- `unknown-lidar-imu` stores visible identity/zero placeholders with `status=UNKNOWN`, `usable_for_lidar_imu_benchmark=false`, and `placeholder_transform=true`.
- Existing registry-ID manifests remain backward compatible.
- An experiment specifies exactly one of `dataset` or `dataset_file`.
- No estimator, trajectory, map, Relative SE(3), report, demo, or new algorithm adapter is executed in P1 acceptance.

---

## File Structure

- Create `benchmark_base/lib/bag_probe.py` — pure bag content identity, topic evidence normalization, role/layout classification, probe-schema validation.
- Create `benchmark_base/lib/dataset_intake.py` — pure freeze validation/profile resolution/atomic writer.
- Create `benchmark_base/lib/rosbag_inspection.py` — ROS-aware shared reader extracted from current `evaluators/analyze_bag.py`.
- Modify `evaluators/analyze_bag.py` — use shared inspection reader, preserve existing output contract.
- Create `evaluators/probe_dataset.py` — thin ROS-aware probe writer using shared reader + pure `bag_probe` helpers.
- Create `evaluators/freeze_dataset.py` — thin pure-Python CLI around `dataset_intake.freeze_dataset()`.
- Modify `benchmark_base/lib/registry.py` — expose public reusable dataset-record validation.
- Modify `benchmark_base/lib/manifest.py` — additive `dataset_file` resolution with manifest-relative paths and frozen SHA-256 provenance.
- Modify `benchmark_base/bin/lio-benchmark-core` — pass config path/base directory into schema-v2 resolution so relative `dataset_file` works during validate/init.
- Modify `benchmark_base/bin/lio-benchmark` — additive `dataset probe` / `dataset freeze` public CLI.
- Create tests: `test_bag_probe.py`, `test_dataset_intake.py`, `test_manifest_dataset_file.py`, `test_dataset_intake_cli.py`, `test_rosbag_inspection_contract.py`.
- Create `docs/verification/mid360_bag_intake_v1_verification.md` — exact target-machine Codex acceptance runbook.

---

### Task 1: Pure bag identity and conservative probe classification

**Files:**
- Create: `benchmark_base/lib/bag_probe.py`
- Test: `benchmark_base/tests/test_bag_probe.py`

**Interfaces:**
- Produces: `sha256_file(path: Path) -> str`
- Produces: `build_bag_identity(bag_dir: Path) -> dict[str, Any]`
- Produces: `normalize_topic_evidence(raw_topics: dict[str, Any]) -> list[dict[str, Any]]`
- Produces: `classify_candidate_roles(topics: list[dict[str, Any]]) -> dict[str, Any]`
- Produces: `classify_sensor_layout(topics: list[dict[str, Any]]) -> list[dict[str, Any]]`
- Produces: `validate_probe_payload(payload: dict[str, Any]) -> None`

- [ ] **Step 1: Write failing bag-identity and classification tests**

Tests must construct temporary bag directories with `metadata.yaml` plus multiple `.db3`/`.mcap` files and assert:

```python
identity_a = build_bag_identity(bag_a)
identity_b = build_bag_identity(moved_copy)
self.assertEqual(identity_a["bag_content_sha256"], identity_b["bag_content_sha256"])
self.assertEqual(
    [row["relative_path"] for row in identity_a["storage_files"]],
    sorted(row["relative_path"] for row in identity_a["storage_files"]),
)
```

Also assert one CustomMsg + one Imu yields `UNAMBIGUOUS`, two LiDAR candidates yield `AMBIGUOUS`, topic names do not affect classification, and Livox layout is only `LIVOX_CUSTOM_LAYOUT`.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_bag_probe -v
```

Expected: import/module failures because `bag_probe.py` does not exist.

- [ ] **Step 3: Implement minimal pure helpers**

Bag identity must hash only `metadata.yaml` when present and sorted regular storage files matching `*.db3` or `*.mcap`. Aggregate hash input must be canonical JSON of `(relative_path,size_bytes,sha256)` rows, not absolute paths.

Candidate types:

```python
LIDAR_TYPES = {
    "livox_ros_driver2/msg/CustomMsg",
    "sensor_msgs/msg/PointCloud2",
}
IMU_TYPE = "sensor_msgs/msg/Imu"
```

Probe validation must require schema `lio_benchmark_dataset_probe/v1`, source bag path, bag identity with non-empty storage files and SHA, topics list, candidate roles, timestamp/IMU evidence containers, sensor-layout candidates, and limitations list.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m unittest benchmark_base.tests.test_bag_probe -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/bag_probe.py benchmark_base/tests/test_bag_probe.py
git commit -m "feat: add mid360 bag probe contracts"
```

---

### Task 2: Reuse one ROS bag inspection implementation for analyze and probe

**Files:**
- Create: `benchmark_base/lib/rosbag_inspection.py`
- Modify: `evaluators/analyze_bag.py`
- Create: `evaluators/probe_dataset.py`
- Test: `benchmark_base/tests/test_rosbag_inspection_contract.py`

**Interfaces:**
- Produces: `inspect_ros2_bag(bag: Path) -> dict[str, Any]`
- Consumes Task 1 helpers to create final probe JSON.

- [ ] **Step 1: Write static RED contract test**

The test must not import ROS packages. It reads source text and requires both evaluators to import `inspect_ros2_bag` from the shared module, requires `probe_dataset.py` to call `build_bag_identity`, `normalize_topic_evidence`, and candidate classifiers, and forbids a second `rosbag2_py.SequentialReader()` implementation in either evaluator.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_rosbag_inspection_contract -v
```

Expected: FAIL because shared module/evaluator do not exist.

- [ ] **Step 3: Extract current reader logic**

Move the current read-only scanning logic from `evaluators/analyze_bag.py` into `benchmark_base/lib/rosbag_inspection.py` with the same observed facts: topic type/count, recorded/header time series summaries, frame IDs, point fields, IMU statistics, and nearest LiDAR/IMU header timing. `analyze_bag.py` becomes a thin wrapper preserving its existing JSON output behavior.

`probe_dataset.py` must:

```text
resolve bag path
refuse missing/non-directory bag
refuse existing output
call inspect_ros2_bag()
build deterministic bag identity
normalize topic evidence
classify roles/layout
write schema lio_benchmark_dataset_probe/v1
```

Default output is `<bag-parent>/<bag-name>.lio_benchmark_probe.json`.

- [ ] **Step 4: Run GREEN + compile**

```bash
python3 -m unittest benchmark_base.tests.test_rosbag_inspection_contract -v
python3 -m compileall -q benchmark_base evaluators
```

Expected: PASS without importing ROS during unit tests.

- [ ] **Step 5: Commit**

```bash
git add benchmark_base/lib/rosbag_inspection.py evaluators/analyze_bag.py evaluators/probe_dataset.py benchmark_base/tests/test_rosbag_inspection_contract.py
git commit -m "feat: add shared rosbag dataset probe reader"
```

---

### Task 3: Freeze immutable dataset contracts with explicit profile and IMU semantics

**Files:**
- Create: `benchmark_base/lib/dataset_intake.py`
- Create: `evaluators/freeze_dataset.py`
- Modify: `benchmark_base/lib/registry.py`
- Test: `benchmark_base/tests/test_dataset_intake.py`
- Test: `benchmark_base/tests/test_registry.py`

**Interfaces:**
- Registry produces: `validate_dataset_record(record: dict[str, Any], expected_id: str | None = None) -> None`
- Intake produces: `freeze_dataset(...)->Path`
- Intake consumes `validate_probe_payload`, `build_bag_identity`, `RigidTransform`, and public dataset validation.

- [ ] **Step 1: Write RED tests for registry-valid internal profile**

Build a synthetic probe pointing to a temporary bag and call:

```python
output = freeze_dataset(
    probe_path=probe_path,
    dataset_id="unit_mid360",
    lidar_topic="/lidar",
    imu_topic="/imu",
    profile="mid360-internal",
    imu_angular_velocity_unit="rad_s",
    imu_linear_acceleration_unit="g_like_raw",
    output_dir=root / "frozen",
)
```

Assert byte-identical `inspection.json`, registry-valid `dataset.json`, exact Livox timestamp contract, explicit unit labels/source, `MANUFACTURER_SPEC`, Mid-360 sensor provenance `EXPLICIT_PROFILE_SELECTION`, and copied inspection SHA.

Also add failures for changed bag bytes after probe, missing/wrong topics, PointCloud2, timestamp regressions, invalid dataset id/unit, existing output, and partial-output cleanup.

- [ ] **Step 2: Write RED tests for user/unknown calibration profiles**

`mid360-user-extrinsic` must require 9+3 finite values and `calibration_source`; it writes `USER_PROVIDED`. Add rotation plausibility checks: row norms approximately 1, row dot products approximately 0, determinant approximately +1 within `1e-3`.

`unknown-lidar-imu` writes identity/zero placeholders with explicit blocking flags and `sensor_model=UNKNOWN`.

- [ ] **Step 3: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_dataset_intake benchmark_base.tests.test_registry -v
```

Expected: FAIL because public validator/intake do not exist.

- [ ] **Step 4: Expose public dataset validation**

Refactor current private dataset validator so `Registry.load_dataset()` still validates filename/record identity while external records can call:

```python
def validate_dataset_record(record, expected_id=None):
    expected = expected_id or str(record.get("dataset_id", ""))
    Registry._validate_dataset(record, expected)
```

Do not weaken existing schema requirements.

- [ ] **Step 5: Implement freeze validation and atomic writer**

Use a temporary sibling directory named from output plus random UUID, copy probe bytes directly, write `dataset.json`, validate it, then `Path.replace()`/atomic rename into final output. Clean staging on every exception.

Internal transform is exactly:

```text
R = [1,0,0, 0,1,0, 0,0,1]
t = [-0.011, -0.02329, 0.04412]
manufacturer_imu_origin_in_lidar_m = [0.011, 0.02329, -0.04412]
```

- [ ] **Step 6: Implement pure evaluator wrapper**

`evaluators/freeze_dataset.py` parses all frozen V1 arguments and contains no `rclpy`, `rosbag2_py`, `ros2 bag`, estimator, map, or report execution code.

- [ ] **Step 7: Run GREEN**

```bash
python3 -m unittest benchmark_base.tests.test_dataset_intake benchmark_base.tests.test_registry -v
python3 -m compileall -q benchmark_base evaluators
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add benchmark_base/lib/dataset_intake.py evaluators/freeze_dataset.py benchmark_base/lib/registry.py benchmark_base/tests/test_dataset_intake.py benchmark_base/tests/test_registry.py
git commit -m "feat: freeze auditable mid360 dataset contracts"
```

---

### Task 4: Add external `dataset_file` manifest bridge without breaking registry IDs

**Files:**
- Modify: `benchmark_base/lib/manifest.py`
- Modify: `benchmark_base/bin/lio-benchmark-core`
- Test: `benchmark_base/tests/test_manifest_dataset_file.py`
- Test: `benchmark_base/tests/test_cli_manifest.py`

**Interfaces:**
- `resolve_manifest(manifest, registry=None, *, manifest_dir: Path | None = None) -> dict[str, Any]`
- `validate_manifest(..., manifest_dir: Path | None = None) -> list[str]`
- Resolved external manifests expose `dataset_file_ref`, `dataset_file_sha256`, and frozen `dataset` content.

- [ ] **Step 1: Write RED manifest tests**

Cover absolute and manifest-relative `dataset_file`, registry-ID backward compatibility, both-fields rejection, neither-fields rejection, missing file, malformed JSON, schema-invalid record, and SHA/content frozen into resolved result.

Expected resolved fields for external dataset:

```python
self.assertEqual(str(dataset_path.resolve()), resolved["dataset_file_ref"])
self.assertEqual(sha256_file(dataset_path), resolved["dataset_file_sha256"])
self.assertEqual(dataset_payload, resolved["dataset"])
```

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_manifest_dataset_file benchmark_base.tests.test_cli_manifest -v
```

Expected: FAIL because schema-v2 currently requires `dataset` registry ID.

- [ ] **Step 3: Implement mutually-exclusive dataset source resolution**

For schema-v2, accept exactly one of:

```text
dataset = registry id
dataset_file = external JSON path
```

Relative paths resolve against `manifest_dir`; without `manifest_dir`, relative `dataset_file` is rejected rather than resolved against process CWD.

External content is loaded, publicly dataset-validated, copied into resolved manifest, and SHA-256 frozen.

- [ ] **Step 4: Wire config path into core validate/init**

`resolve_config(path, ...)` must call `validate_manifest(..., manifest_dir=path.parent)` and `resolve_manifest(..., manifest_dir=path.parent)`. Existing callers that use registry IDs retain current behavior.

- [ ] **Step 5: Run GREEN and regression set**

```bash
python3 -m unittest benchmark_base.tests.test_manifest_dataset_file benchmark_base.tests.test_cli_manifest benchmark_base.tests.test_registry -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add benchmark_base/lib/manifest.py benchmark_base/bin/lio-benchmark-core benchmark_base/tests/test_manifest_dataset_file.py benchmark_base/tests/test_cli_manifest.py
git commit -m "feat: allow frozen external dataset files"
```

---

### Task 5: Public CLI contract, repository acceptance, and target-machine runbook

**Files:**
- Modify: `benchmark_base/bin/lio-benchmark`
- Create: `benchmark_base/tests/test_dataset_intake_cli.py`
- Create: `docs/verification/mid360_bag_intake_v1_verification.md`

**Interfaces:**
- Public commands:
  - `lio-benchmark dataset probe --bag <bag> [--output <probe>]`
  - `lio-benchmark dataset freeze --probe ... --dataset-id ... --lidar-topic ... --imu-topic ... --profile ... --imu-angular-velocity-unit ... --imu-linear-acceleration-unit ... --output ... [user-extrinsic args]`

- [ ] **Step 1: Write RED CLI tests**

Parser test must prove probe accepts only `--bag`/`--output`; reject `--lidar-topic`, `--profile`, `--overwrite`, `--fix`.

Freeze must expose required V1 args and optional `--rotation-lidar-to-imu` (9 floats), `--translation-lidar-to-imu` (3 floats), `--calibration-source`; reject `--overwrite`, `--autodetect-calibration`, and unrelated algorithm args.

Handler test must prove freeze invokes only `evaluators/freeze_dataset.py`; probe invokes only `evaluators/probe_dataset.py`. Static evaluator test must confirm only probe contains ROS dependency.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest benchmark_base.tests.test_dataset_intake_cli -v
```

Expected: FAIL because `dataset` CLI group does not exist.

- [ ] **Step 3: Add public CLI group and dispatch**

Add `dataset` root subparser with `probe` and `freeze`. Do not add Suite Orchestrator behavior. Use direct subprocess evaluator dispatch; target operator must source the ROS/workspace environment needed to deserialize Livox CustomMsg before `dataset probe`.

- [ ] **Step 4: Run GREEN + full Core Contracts equivalent locally where possible**

```bash
python3 -m unittest benchmark_base.tests.test_dataset_intake_cli -v
python3 -m unittest benchmark_base.tests.test_registry -v
python3 -m unittest discover -s benchmark_base/tests -v
python3 -m compileall -q benchmark_base evaluators visualization reporting
find evaluators -maxdepth 1 -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 benchmark_base/bin/lio-benchmark list algorithms
python3 benchmark_base/bin/lio-benchmark show algorithm leg_kilo2_lidar_imu >/dev/null
```

Expected: all PASS.

- [ ] **Step 5: Write exact target-machine verification runbook**

The runbook must freeze one exact repository HEAD and use the already-characterized greenhouse bag as target acceptance input. It must source ROS2 Humble plus the workspace that provides `livox_ros_driver2/msg/CustomMsg`, create unique probe/output paths, use actual topics `/agt/sensors/lidar/custom` and `/agt/sensors/imu/data`, profile `mid360-internal`, units `rad_s` and `g_like_raw`, then verify:

```text
probe schema and bag SHA
storage-file SHA evidence
selected topic/type evidence
byte-identical copied inspection
registry-valid dataset.json
exact Livox timestamp semantics
explicit IMU units
MANUFACTURER_SPEC calibration
Mid-360 explicit-profile provenance
intake inspection/bag SHA lineage
dataset_file manifest validation and resolution
current source bag identity still matches probe
```

It prints only after all assertions:

```text
MID360_BAG_INTAKE_V1_TARGET_CONTRACT=PASS
```

No estimator is run.

- [ ] **Step 6: Commit**

```bash
git add benchmark_base/bin/lio-benchmark benchmark_base/tests/test_dataset_intake_cli.py docs/verification/mid360_bag_intake_v1_verification.md
git commit -m "feat: expose mid360 bag intake workflow"
```

- [ ] **Step 7: Exact-head repository acceptance**

Wait for the GitHub Actions `Core Contracts` workflow at the final exact HEAD and require all steps `success`. Freeze:

```text
MID360_BAG_INTAKE_V1_REPOSITORY_ACCEPTANCE = PASS
MID360_BAG_INTAKE_V1_TARGET_MACHINE_ACCEPTANCE = PENDING
```

Stop implementation here and hand the exact HEAD + verification runbook to Codex on the target machine.

---

## Plan self-review

- Spec coverage: probe evidence, immutable freeze, three profiles, explicit units, Livox timestamp-only V1, external dataset file, CLI restrictions, repository CI, and target acceptance are each assigned to a task.
- No Suite Orchestrator or adapter expansion is included.
- ROS dependency is isolated from GitHub unit-test imports.
- Existing registry-ID manifests and current accepted greenhouse benchmark configuration remain backward compatible.
- No placeholder implementation steps remain.
