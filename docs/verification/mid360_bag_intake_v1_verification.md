# MID360 Bag Intake V1 Target-Machine Verification

Date: 2026-08-17
Branch: `feat/lio-baseline-suite`

## Scope

This runbook verifies only `MID360 Bag Intake V1` on the target ROS 2 machine.

It must stop after proving:

```text
real greenhouse ROS 2 bag
        ↓
read-only dataset probe
        ↓
explicit MID360/internal-IMU freeze
        ↓
inspection.json + dataset.json
        ↓
external dataset_file manifest resolution
```

It must **not** run any estimator, replay a benchmark suite, standardize a trajectory/map, compute Relative SE(3), generate a report/demo, add an algorithm adapter, or begin Suite Orchestrator V1.

The target acceptance marker is:

```text
MID360_BAG_INTAKE_V1_TARGET_CONTRACT=PASS
```

Do not claim target PASS unless that exact marker is printed by the machine contract in Section 7.

## Frozen target input

Use exactly:

```text
bag = /home/yangxuan/agt_navigation_v2/runtime/rosbag/green-house
LiDAR topic = /agt/sensors/lidar/custom
IMU topic = /agt/sensors/imu/data
profile = mid360-internal
IMU angular velocity unit = rad_s
IMU linear acceleration unit = g_like_raw
```

The profile selection is an explicit operator assertion that this bag uses the Livox Mid-360 internal IMU geometry. The probe itself does not infer the physical sensor model.

## 1. Exact repository HEAD gate

The handoff prompt must export the exact repository-accepted HEAD as `MID360_BAG_INTAKE_V1_EXPECTED_HEAD`.

```bash
set -euo pipefail
cd ~/lio_benchmark_tools

git switch feat/lio-baseline-suite
git pull --ff-only

test -n "${MID360_BAG_INTAKE_V1_EXPECTED_HEAD:-}" || {
  echo "missing MID360_BAG_INTAKE_V1_EXPECTED_HEAD"
  exit 1
}

HEAD=$(git rev-parse HEAD)
test "$HEAD" = "$MID360_BAG_INTAKE_V1_EXPECTED_HEAD" || {
  echo "unexpected HEAD: $HEAD"
  exit 1
}

if test -n "$(git status --short)"; then
  echo "working tree is not clean"
  git status --short
  exit 1
fi
```

Do not use `git reset --hard`, do not discard local changes, and do not continue from a different commit.

## 2. Exact ROS / message environment gate

The probe must be able to deserialize `livox_ros_driver2/msg/CustomMsg`.

Use the known target workspace only; do not search for substitute overlays.

```bash
test -f /opt/ros/humble/setup.bash || {
  echo "BLOCKED_ENVIRONMENT: missing /opt/ros/humble/setup.bash"
  exit 1
}

test -f /home/yangxuan/agt_navigation_v2/install/setup.bash || {
  echo "BLOCKED_ENVIRONMENT: missing agt_navigation_v2 install/setup.bash"
  exit 1
}

source /opt/ros/humble/setup.bash
source /home/yangxuan/agt_navigation_v2/install/setup.bash

test "${ROS_DISTRO:-}" = "humble" || {
  echo "BLOCKED_ENVIRONMENT: ROS_DISTRO=${ROS_DISTRO:-<unset>}"
  exit 1
}

ros2 interface show livox_ros_driver2/msg/CustomMsg >/dev/null || {
  echo "BLOCKED_ENVIRONMENT: livox_ros_driver2/msg/CustomMsg unavailable"
  exit 1
}
```

If this fails, report `BLOCKED_ENVIRONMENT`. Do not clone/build/source an unplanned replacement package during this acceptance.

## 3. Create unique intake artifact locations

The source bag is read-only input. Probe and frozen dataset outputs must be new and non-overwritable.

```bash
BAG=/home/yangxuan/agt_navigation_v2/runtime/rosbag/green-house

test -d "$BAG" || {
  echo "missing target bag: $BAG"
  exit 1
}

test -f "$BAG/metadata.yaml" || {
  echo "target bag missing metadata.yaml: $BAG"
  exit 1
}

STAMP=$(date +%Y%m%d_%H%M%S)
INTAKE_ROOT=/home/yangxuan/lio_benchmark_runs/green_house/mid360_intake_v1_${STAMP}
PROBE=$INTAKE_ROOT/greenhouse_probe.json
DATASET_DIR=$INTAKE_ROOT/dataset
DATASET_ID=greenhouse_mid360_intake_v1_${STAMP}
CONFIG=$INTAKE_ROOT/external_dataset_config.json

mkdir -p "$INTAKE_ROOT"

test ! -e "$PROBE"
test ! -e "$DATASET_DIR"
test ! -e "$CONFIG"

printf 'INTAKE_ROOT=%s\nPROBE=%s\nDATASET_DIR=%s\nDATASET_ID=%s\n' \
  "$INTAKE_ROOT" "$PROBE" "$DATASET_DIR" "$DATASET_ID"
```

Do not reuse an old probe or frozen dataset directory for target acceptance.

## 4. Read-only probe

Run exactly:

```bash
python3 benchmark_base/bin/lio-benchmark dataset probe \
  --bag "$BAG" \
  --output "$PROBE"
```

This command may read the complete bag and hash its storage files. It must not modify the bag.

Immediately verify the source bag still resolves to the same path:

```bash
test -f "$PROBE"
test -s "$PROBE"
```

Do not pass topic names, sensor profile, extrinsics, unit overrides, repair flags, or overwrite flags to `dataset probe`.

## 5. Explicit frozen dataset contract

Run exactly:

```bash
python3 benchmark_base/bin/lio-benchmark dataset freeze \
  --probe "$PROBE" \
  --dataset-id "$DATASET_ID" \
  --lidar-topic /agt/sensors/lidar/custom \
  --imu-topic /agt/sensors/imu/data \
  --profile mid360-internal \
  --imu-angular-velocity-unit rad_s \
  --imu-linear-acceleration-unit g_like_raw \
  --output "$DATASET_DIR"
```

Required immutable output:

```text
$DATASET_DIR/
├── inspection.json
└── dataset.json
```

Do not add optional user-extrinsic arguments to this target case.

## 6. Verify `dataset_file` is consumable by the existing manifest layer

Create one validation-only experiment config by copying the already accepted Same-Bag V1 experiment structure and replacing the tracked registry dataset ID with the newly frozen external `dataset_file`.

```bash
python3 - "$DATASET_DIR/dataset.json" "$CONFIG" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

repo = Path.cwd().resolve()
dataset = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
source = json.loads(
    (repo / "benchmark_base/config/green_house_three_full_bag_v1.json").read_text(
        encoding="utf-8"
    )
)
source.pop("dataset", None)
source["dataset_file"] = str(dataset)
source["name"] = "mid360_bag_intake_v1_dataset_file_gate"
output.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(output)
PY

python3 benchmark_base/bin/lio-benchmark validate --config "$CONFIG"
```

This validates configuration/dataset consumption only. Do **not** run `init`, `preflight`, `run`, or `run-all` in this P1 target acceptance.

## 7. Machine acceptance contract

Run this exact contract after Sections 1–6 succeed:

```bash
python3 - "$BAG" "$PROBE" "$DATASET_DIR" "$DATASET_ID" "$CONFIG" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

from benchmark_base.lib.bag_probe import build_bag_identity, sha256_file, validate_probe_payload
from benchmark_base.lib.manifest import load_json, resolve_manifest, validate_manifest
from benchmark_base.lib.registry import Registry, validate_dataset_record

bag = Path(sys.argv[1]).resolve()
probe_path = Path(sys.argv[2]).resolve()
dataset_dir = Path(sys.argv[3]).resolve()
dataset_id = sys.argv[4]
config_path = Path(sys.argv[5]).resolve()
repo = Path.cwd().resolve()

LIDAR = "/agt/sensors/lidar/custom"
IMU = "/agt/sensors/imu/data"
CUSTOM = "livox_ros_driver2/msg/CustomMsg"
IMU_TYPE = "sensor_msgs/msg/Imu"

assert bag.is_dir()
assert probe_path.is_file() and probe_path.stat().st_size > 0
assert dataset_dir.is_dir()
assert {p.name for p in dataset_dir.iterdir()} == {"inspection.json", "dataset.json"}

probe = json.loads(probe_path.read_text(encoding="utf-8"))
validate_probe_payload(probe)
assert probe["schema"] == "lio_benchmark_dataset_probe/v1"
assert Path(probe["source"]["bag_dir"]).resolve() == bag
assert probe["source"]["mode"] == "READ_ONLY_EVIDENCE"

identity = probe["bag_identity"]
assert Path(identity["bag_dir"]).resolve() == bag
assert identity["storage_files"], identity
paths = [row["relative_path"] for row in identity["storage_files"]]
assert paths == sorted(paths), paths
assert all(row["size_bytes"] > 0 for row in identity["storage_files"])
assert all(len(row["sha256"]) == 64 for row in identity["storage_files"])
assert len(identity["bag_content_sha256"]) == 64
if identity["metadata_yaml"] is not None:
    assert identity["metadata_yaml"]["relative_path"] == "metadata.yaml"
    assert identity["metadata_yaml"]["size_bytes"] > 0
    assert len(identity["metadata_yaml"]["sha256"]) == 64

current_identity = build_bag_identity(bag)
assert current_identity["bag_content_sha256"] == identity["bag_content_sha256"]
assert current_identity["storage_files"] == identity["storage_files"]
assert current_identity["metadata_yaml"] == identity["metadata_yaml"]

topics = {row["name"]: row for row in probe["topics"]}
assert LIDAR in topics, sorted(topics)
assert IMU in topics, sorted(topics)
lidar = topics[LIDAR]
imu = topics[IMU]
assert lidar["type"] == CUSTOM, lidar
assert imu["type"] == IMU_TYPE, imu
for role, row in (("lidar", lidar), ("imu", imu)):
    assert row["message_count"] > 0, (role, row)
    assert row["recorded_first_s"] is not None
    assert row["recorded_last_s"] is not None
    assert row["recorded_time_reversal_count"] == 0, (role, row)
    assert row["header_first_s"] is not None
    assert row["header_last_s"] is not None
    assert row["header_time_reversal_count"] == 0, (role, row)
    assert row["recorded_rate_hz"] is not None and row["recorded_rate_hz"] > 0
    assert row["header_rate_hz"] is not None and row["header_rate_hz"] > 0

assert LIDAR in probe["candidate_roles"]["lidar"]["candidates"]
assert IMU in probe["candidate_roles"]["imu"]["candidates"]
assert any(
    row["topic"] == LIDAR and row["layout"] == "LIVOX_CUSTOM_LAYOUT"
    for row in probe["sensor_layout_candidates"]
)
assert "MID360_VERIFIED" not in json.dumps(probe, ensure_ascii=False)

inspection_copy = dataset_dir / "inspection.json"
dataset_path = dataset_dir / "dataset.json"
assert inspection_copy.read_bytes() == probe_path.read_bytes()
assert sha256_file(inspection_copy) == sha256_file(probe_path)

dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
validate_dataset_record(dataset)
assert dataset["schema_version"] == 2
assert dataset["dataset_id"] == dataset_id
assert Path(dataset["bag_dir"]).resolve() == bag
assert dataset["sha256"] == identity["bag_content_sha256"]
assert dataset["environment"] == "UNSPECIFIED"
assert dataset["acquisition"] == {
    "platform": "UNSPECIFIED",
    "route_type": "UNSPECIFIED",
    "camera_present": False,
}
assert dataset["topics"]["lidar"] == LIDAR
assert dataset["topics"]["imu"] == IMU
assert dataset["types"]["lidar"] == CUSTOM
assert dataset["types"]["imu"] == IMU_TYPE

assert dataset["timestamp"] == {
    "point_time_field": "offset_time",
    "point_time_unit": "ns_relative_to_timebase",
    "scan_time_field": "header.stamp",
    "timebase_field": "timebase",
    "verified_from_bag": True,
    "header_time_audit": "FULL_SELECTED_TOPIC",
}
assert dataset["imu"]["angular_velocity_unit"] == "rad_s"
assert dataset["imu"]["linear_acceleration_unit"] == "g_like_raw"
assert dataset["imu"]["unit_source"] == "EXPLICIT_USER_SELECTION"

cal = dataset["calibration"]
assert cal["canonical_convention"] == "LIDAR_TO_IMU"
assert cal["canonical_equation"] == "p_I = R_IL * p_L + t_IL"
assert cal["rotation_lidar_to_imu_row_major"] == [
    1.0, 0.0, 0.0,
    0.0, 1.0, 0.0,
    0.0, 0.0, 1.0,
]
assert cal["translation_lidar_to_imu_m"] == [-0.011, -0.02329, 0.04412]
assert cal["manufacturer_imu_origin_in_lidar_m"] == [0.011, 0.02329, -0.04412]
assert cal["status"] == "MANUFACTURER_SPEC"
assert cal["source_type"] == "MANUFACTURER_SPEC"
assert cal["sensor_model"] == "Livox Mid-360"
assert cal["sensor_model_source"] == "EXPLICIT_PROFILE_SELECTION"
assert cal["imu_relation"] == "INTERNAL_IMU"
assert cal["online_extrinsic_estimation"] is False

intake = dataset["intake"]
assert intake["schema"] == "lio_benchmark_dataset_intake/v1"
assert intake["profile"] == "mid360-internal"
assert intake["inspection_sha256"] == sha256_file(probe_path)
assert intake["bag_content_sha256"] == identity["bag_content_sha256"]
assert intake["selected_topics_source"] == "EXPLICIT_USER_SELECTION"

source_manifest = load_json(config_path)
assert "dataset" not in source_manifest
assert Path(source_manifest["dataset_file"]).resolve() == dataset_path
errors = validate_manifest(
    source_manifest,
    registry=Registry(),
    check_paths=True,
    module_root=repo,
    manifest_dir=config_path.parent,
)
assert not errors, errors
resolved = resolve_manifest(
    source_manifest,
    Registry(),
    manifest_dir=config_path.parent,
)
assert resolved["dataset_file_ref"] == str(dataset_path.resolve())
assert resolved["dataset_file_sha256"] == sha256_file(dataset_path)
assert resolved["dataset"] == dataset
assert resolved["dataset"]["dataset_id"] == dataset_id

# Recompute once more after all freeze/manifest operations: source evidence is still identical.
final_identity = build_bag_identity(bag)
assert final_identity["bag_content_sha256"] == identity["bag_content_sha256"]

print("MID360_BAG_INTAKE_V1_TARGET_CONTRACT=PASS")
print("bag_content_sha256=", identity["bag_content_sha256"])
print("probe=", probe_path)
print("dataset_dir=", dataset_dir)
print("dataset_id=", dataset_id)
print("dataset_file_ref=", resolved["dataset_file_ref"])
print("dataset_file_sha256=", resolved["dataset_file_sha256"])
print("lidar_count=", lidar["message_count"], "lidar_rate_hz=", lidar["header_rate_hz"])
print("imu_count=", imu["message_count"], "imu_rate_hz=", imu["header_rate_hz"])
PY
```

## 8. Final target report and stop condition

After and only after Section 7 prints PASS, report:

```bash
echo "HEAD=$(git rev-parse HEAD)"
echo "PROBE=$PROBE"
echo "DATASET_DIR=$DATASET_DIR"
echo "CONFIG=$CONFIG"
cat "$DATASET_DIR/dataset.json"
git status --short
```

Expected final state:

```text
MID360_BAG_INTAKE_V1_REPOSITORY_ACCEPTANCE = PASS
MID360_BAG_INTAKE_V1_TARGET_MACHINE_ACCEPTANCE = PASS
```

Stop immediately. Do not run:

```text
lio-benchmark init
lio-benchmark preflight
lio-benchmark run
lio-benchmark run-all
trajectory standardization
map standardization
Relative SE(3)
report/demo
Point-LIO / DLIO / Leg-KILO adapter work
Benchmark Suite Orchestrator V1
```

## Failure policy

If probe/freeze/contract fails:

1. do not overwrite generated artifacts;
2. preserve the failed probe/dataset evidence;
3. diagnose the exact cause;
4. if it is a genuine implementation bug, add a regression RED test, apply the smallest fix, run Core Contracts, commit it, and use a **new unique** intake output path for the target retry;
5. do not change bag content, selected topics, MID360 manufacturer transform, unit labels, or acceptance assertions merely to make the target pass.
