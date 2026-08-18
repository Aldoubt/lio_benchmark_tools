# Benchmark Suite Orchestrator V1 Target-Machine Verification

Date: 2026-08-18
Branch: `feat/lio-baseline-suite`

## Scope

This runbook verifies only `Benchmark Suite Orchestrator V1` on the target ROS 2 machine.

It proves the real orchestration path:

```text
accepted frozen MID360 dataset
        ↓
45 s Same-Bag suite run
        ↓
SIGINT sent to suite parent during FAST-LIVO2 runtime
        ↓
FAST-LIVO2 stage completes and suite stops at stage boundary
        ↓
suite resume
        ↓
FAST-LIVO2 is not rerun
FAST-LIO2 + KISS-ICP + remaining post-processing complete
        ↓
second suite resume
        ↓
zero scientific stage re-execution
        ↓
SUITE PASS
```

This target acceptance does **not** start P3, add a new algorithm adapter, change estimator parameters, change calibration, change topics, change standardization, or claim ground-truth accuracy/ranking.

The only authoritative target marker is:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_CONTRACT=PASS
```

Do not claim target-machine PASS unless the machine contract in Section 10 prints that exact marker.

---

## 1. Exact repository and clean-tree gate

The handoff prompt must export the exact repository-accepted HEAD:

```bash
set -euo pipefail
cd ~/lio_benchmark_tools

git switch feat/lio-baseline-suite
git pull --ff-only

test -n "${BENCHMARK_SUITE_ORCHESTRATOR_V1_EXPECTED_HEAD:-}" || {
  echo "missing BENCHMARK_SUITE_ORCHESTRATOR_V1_EXPECTED_HEAD"
  exit 1
}

HEAD=$(git rev-parse HEAD)
test "$HEAD" = "$BENCHMARK_SUITE_ORCHESTRATOR_V1_EXPECTED_HEAD" || {
  echo "unexpected HEAD: $HEAD"
  exit 1
}

test -z "$(git status --short)" || {
  echo "working tree is not clean"
  git status --short
  exit 1
}
```

Do not use `git reset --hard`, do not discard local changes, and do not continue from another commit.

---

## 2. Frozen accepted P1 dataset gate

Use exactly:

```bash
P1_DATASET=/home/yangxuan/lio_benchmark_runs/green_house/mid360_intake_v1_20260818_073506/dataset/dataset.json
EXPECTED_DATASET_FILE_SHA=cbec05555e6468ac56014d53dcc17d2a95962d286654a218afe3cd595680c708
EXPECTED_BAG_CONTENT_SHA=26d3bb6e8897ab6e66cd6d3bba1ae43bddb21f33ec7f368c6d01ad099ce2b8a6

test -f "$P1_DATASET"
test "$(sha256sum "$P1_DATASET" | awk '{print $1}')" = "$EXPECTED_DATASET_FILE_SHA"

python3 - "$P1_DATASET" "$EXPECTED_BAG_CONTENT_SHA" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1]).resolve()
expected = sys.argv[2]
x = json.loads(path.read_text(encoding="utf-8"))
assert x["dataset_id"] == "greenhouse_mid360_intake_v1_20260818_073506"
assert x["bag_dir"] == "/home/yangxuan/agt_navigation_v2/runtime/rosbag/green-house"
assert x["sha256"] == expected
assert x["topics"]["lidar"] == "/agt/sensors/lidar/custom"
assert x["topics"]["imu"] == "/agt/sensors/imu/data"
assert x["timestamp"]["point_time_field"] == "offset_time"
assert x["timestamp"]["point_time_unit"] == "ns_relative_to_timebase"
assert x["imu"]["angular_velocity_unit"] == "rad_s"
assert x["imu"]["linear_acceleration_unit"] == "g_like_raw"
assert x["calibration"]["status"] == "MANUFACTURER_SPEC"
print("P2_ACCEPTED_P1_DATASET=PASS")
PY
```

Never edit or overwrite this P1 dataset directory.

---

## 3. ROS/runtime environment gate

Source only the accepted target environment first:

```bash
source /opt/ros/humble/setup.bash
source /home/yangxuan/agt_navigation_v2/install/setup.bash

ros2 interface show livox_ros_driver2/msg/CustomMsg >/dev/null

test -x /home/yangxuan/RM-NAV/build/fast_lio/fastlio_mapping
test -f /home/yangxuan/lio_benchmark_dependencies/kiss_icp_ws/install/setup.bash
```

If the existing algorithm preflight later reports a target environment issue, preserve that evidence. Do not auto-clone, auto-build, source an unknown overlay, or change the frozen execution contract to manufacture PASS.

---

## 4. Create one unique 45 s acceptance config outside the repository

Create a new acceptance root and unique suite run:

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
ACCEPT_ROOT=/home/yangxuan/lio_benchmark_runs/green_house/p2_suite_acceptance_$STAMP
RUN_ID=suite_orchestrator_v1_smoke_$STAMP
RUN=/home/yangxuan/lio_benchmark_runs/green_house/$RUN_ID
CONFIG=$ACCEPT_ROOT/suite_smoke_config.json
RUN_LOG=$ACCEPT_ROOT/suite_run.log

mkdir -p "$ACCEPT_ROOT"
test ! -e "$RUN"
test ! -e "$CONFIG"
```

Generate the config from the accepted full-bag config, changing only the experiment-local intake/replay fields required by this smoke acceptance:

```bash
python3 - \
  benchmark_base/config/green_house_three_full_bag_v1.json \
  "$P1_DATASET" \
  "$CONFIG" \
  "$RUN_ID" <<'PY'
import copy
import json
from pathlib import Path
import sys

source_path = Path(sys.argv[1]).resolve()
dataset_file = Path(sys.argv[2]).resolve()
output_path = Path(sys.argv[3]).resolve()
run_id = sys.argv[4]

source = json.loads(source_path.read_text(encoding="utf-8"))
assert source["algorithms"] == ["fast_livo2", "fast_lio2", "kiss_icp"]
assert source["replay"] == {
    "rate": 1.0,
    "start_offset_s": 0.0,
    "duration_s": 622.99,
}

x = copy.deepcopy(source)
x["name"] = run_id
x.pop("dataset", None)
x["dataset_file"] = str(dataset_file)
x["replay"] = {
    "rate": 1.0,
    "start_offset_s": 0.0,
    "duration_s": 45.0,
}
x["output_root"] = "/home/yangxuan/lio_benchmark_runs/green_house"

# Prove no frozen algorithm/standardization/execution contract was changed.
assert x["algorithms"] == source["algorithms"]
for key in ("execution_overrides", "standardization"):
    if key in source:
        assert x[key] == source[key]

output_path.write_text(json.dumps(x, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(output_path)
PY
```

Validate before suite execution:

```bash
python3 benchmark_base/bin/lio-benchmark validate --config "$CONFIG"

python3 - "$CONFIG" <<'PY'
import json
from pathlib import Path
import sys
x = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert "dataset" not in x
assert x["dataset_file"] == "/home/yangxuan/lio_benchmark_runs/green_house/mid360_intake_v1_20260818_073506/dataset/dataset.json"
assert x["algorithms"] == ["fast_livo2", "fast_lio2", "kiss_icp"]
assert x["replay"] == {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 45.0}
print("P2_SMOKE_CONFIG=PASS")
PY
```

---

## 5. Start suite and request a real stage-boundary stop

Launch only the suite parent in the background:

```bash
python3 benchmark_base/bin/lio-benchmark suite run \
  --config "$CONFIG" \
  --run-id "$RUN_ID" \
  >"$RUN_LOG" 2>&1 &
SUITE_PID=$!

echo "$SUITE_PID" > "$ACCEPT_ROOT/first_suite_pid.txt"
```

Wait for the immutable event proving the FAST-LIVO2 runtime actually started. This poll does not inspect estimator internals and does not modify the run:

```bash
python3 - "$RUN" "$SUITE_PID" <<'PY'
import json
import os
from pathlib import Path
import sys
import time

run = Path(sys.argv[1]).resolve()
pid = int(sys.argv[2])
events = run / "metadata/suite/events"

deadline = time.monotonic() + 180.0
while time.monotonic() < deadline:
    if not Path(f"/proc/{pid}").exists():
        raise SystemExit("suite parent exited before runtime/fast_livo2 STAGE_STARTED")
    if events.is_dir():
        for path in sorted(events.glob("*.json")):
            x = json.loads(path.read_text(encoding="utf-8"))
            if x.get("event_type") == "STAGE_STARTED" and x.get("stage_id") == "runtime/fast_livo2":
                print(path)
                raise SystemExit(0)
    time.sleep(0.2)
raise SystemExit("timed out waiting for runtime/fast_livo2 STAGE_STARTED")
PY
```

Send SIGINT to **only the suite parent PID**:

```bash
kill -INT "$SUITE_PID"

set +e
wait "$SUITE_PID"
FIRST_RC=$?
set -e

echo "$FIRST_RC" | tee "$ACCEPT_ROOT/first_invocation_rc.txt"
test "$FIRST_RC" -eq 130
```

Do not send SIGINT/SIGKILL to the estimator child or process group. V1 intentionally allows the active FAST-LIVO2 stage to finish before stopping.

Validate the first invocation boundary and capture immutable FAST-LIVO2 fingerprints before resume:

```bash
python3 - "$RUN" "$ACCEPT_ROOT/fast_livo2_before_resume.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

run = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

identity = run / "metadata/algorithms/fast_livo2/runtime_identity.json"
run_status = run / "metadata/run_fast_livo2.json"
runtime_perf = run / "metrics/runtime/fast_livo2.json"
assert identity.is_file() and run_status.is_file() and runtime_perf.is_file()
assert json.loads(identity.read_text())["identity_status"] == "FROZEN"
assert json.loads(run_status.read_text())["status"] == "PASS"

events = [json.loads(p.read_text()) for p in sorted((run / "metadata/suite/events").glob("*.json"))]
invocations = [x["invocation_id"] for x in events if x["event_type"] == "SUITE_INVOCATION_STARTED"]
assert len(invocations) == 1
first = invocations[0]
started = [x["stage_id"] for x in events if x["invocation_id"] == first and x["event_type"] == "STAGE_STARTED"]
assert "runtime/fast_livo2" in started
assert "runtime/fast_lio2" not in started
assert "runtime/kiss_icp" not in started
assert any(
    x["invocation_id"] == first and x["event_type"] == "SUITE_STOP_REQUESTED"
    for x in events
)
assert any(
    x["invocation_id"] == first
    and x["event_type"] == "SUITE_INVOCATION_FINISHED"
    and x.get("reason_code") == "INTERRUPTED_AT_STAGE_BOUNDARY"
    for x in events
)

payload = {
    "first_invocation_id": first,
    "runtime_identity_sha256": sha(identity),
    "run_status_sha256": sha(run_status),
    "stage_started_count": sum(x["event_type"] == "STAGE_STARTED" for x in events),
}
out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print("P2_FIRST_STAGE_BOUNDARY_STOP=PASS")
PY
```

---

## 6. First resume: complete only remaining work

Run:

```bash
python3 benchmark_base/bin/lio-benchmark suite resume --run "$RUN" \
  | tee "$ACCEPT_ROOT/first_resume.log"

python3 benchmark_base/bin/lio-benchmark suite status --run "$RUN" --json \
  > "$ACCEPT_ROOT/status_after_first_resume.json"
```

Validate final state and prove FAST-LIVO2 was not re-executed:

```bash
python3 - \
  "$RUN" \
  "$ACCEPT_ROOT/fast_livo2_before_resume.json" \
  "$ACCEPT_ROOT/status_after_first_resume.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

run = Path(sys.argv[1]).resolve()
before = json.loads(Path(sys.argv[2]).read_text())
status = json.loads(Path(sys.argv[3]).read_text())
assert status["state"] == "PASS"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

assert sha(run / "metadata/algorithms/fast_livo2/runtime_identity.json") == before["runtime_identity_sha256"]
assert sha(run / "metadata/run_fast_livo2.json") == before["run_status_sha256"]

events = [json.loads(p.read_text()) for p in sorted((run / "metadata/suite/events").glob("*.json"))]
invocations = [x["invocation_id"] for x in events if x["event_type"] == "SUITE_INVOCATION_STARTED"]
assert len(invocations) == 2
second = invocations[1]
started = [x["stage_id"] for x in events if x["invocation_id"] == second and x["event_type"] == "STAGE_STARTED"]
assert "runtime/fast_livo2" not in started
assert started.count("runtime/fast_lio2") == 1
assert started.count("runtime/kiss_icp") == 1
assert "same_bag_summary" in started
print("P2_FIRST_RESUME_NO_ESTIMATOR_REPEAT=PASS")
PY
```

---

## 7. Freeze pre-second-resume evidence

Before the no-op resume, freeze runtime evidence hashes and scientific-stage count outside the run:

```bash
python3 - "$RUN" "$ACCEPT_ROOT/before_second_resume.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

run = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
algs = ["fast_livo2", "fast_lio2", "kiss_icp"]

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

events = [json.loads(p.read_text()) for p in sorted((run / "metadata/suite/events").glob("*.json"))]
payload = {
    "stage_started_count": sum(x["event_type"] == "STAGE_STARTED" for x in events),
    "runtime_identity_sha256": {
        alg: sha(run / f"metadata/algorithms/{alg}/runtime_identity.json") for alg in algs
    },
    "run_status_sha256": {
        alg: sha(run / f"metadata/run_{alg}.json") for alg in algs
    },
}
out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
```

---

## 8. Second resume must be scientific no-op

Run:

```bash
python3 benchmark_base/bin/lio-benchmark suite resume --run "$RUN" \
  | tee "$ACCEPT_ROOT/second_resume.log"

python3 benchmark_base/bin/lio-benchmark suite status --run "$RUN" --json \
  > "$ACCEPT_ROOT/status_after_second_resume.json"
```

Check no scientific stage was started and no runtime evidence changed:

```bash
python3 - \
  "$RUN" \
  "$ACCEPT_ROOT/before_second_resume.json" \
  "$ACCEPT_ROOT/status_after_second_resume.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

run = Path(sys.argv[1]).resolve()
before = json.loads(Path(sys.argv[2]).read_text())
status = json.loads(Path(sys.argv[3]).read_text())
algs = ["fast_livo2", "fast_lio2", "kiss_icp"]
assert status["state"] == "PASS"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

events = [json.loads(p.read_text()) for p in sorted((run / "metadata/suite/events").glob("*.json"))]
assert sum(x["event_type"] == "STAGE_STARTED" for x in events) == before["stage_started_count"]
for alg in algs:
    assert sha(run / f"metadata/algorithms/{alg}/runtime_identity.json") == before["runtime_identity_sha256"][alg]
    assert sha(run / f"metadata/run_{alg}.json") == before["run_status_sha256"][alg]
print("P2_SECOND_RESUME_SCIENTIFIC_NOOP=PASS")
PY
```

---

## 9. Repository-side smoke before final target contract

Run the pure P2 focused tests on the exact target HEAD before reading the target result:

```bash
python3 -m unittest benchmark_base.tests.test_suite_plan -v
python3 -m unittest benchmark_base.tests.test_suite_status -v
python3 -m unittest benchmark_base.tests.test_suite_events -v
python3 -m unittest benchmark_base.tests.test_suite_identity -v
python3 -m unittest benchmark_base.tests.test_suite_identity_status_gate -v
python3 -m unittest benchmark_base.tests.test_suite_timestamp_gate -v
python3 -m unittest benchmark_base.tests.test_suite_orchestrator -v
python3 -m unittest benchmark_base.tests.test_suite_cli -v
```

Do not modify the run based on these tests.

---

## 10. Authoritative target-machine contract

Run exactly after Sections 1–9 succeed:

```bash
python3 - \
  "$RUN" \
  "$ACCEPT_ROOT" \
  "$BENCHMARK_SUITE_ORCHESTRATOR_V1_EXPECTED_HEAD" \
  "$EXPECTED_BAG_CONTENT_SHA" <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

run = Path(sys.argv[1]).resolve()
accept_root = Path(sys.argv[2]).resolve()
expected_head = sys.argv[3]
expected_bag_sha = sys.argv[4]
algs = ["fast_livo2", "fast_lio2", "kiss_icp"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

# Exact repository / clean tree.
head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
assert head == expected_head
assert subprocess.check_output(["git", "status", "--short"], text=True).strip() == ""

# Frozen run manifest and plan.
manifest = load(run / "manifest.json")
plan = load(run / "metadata/suite/plan.json")
assert manifest["replay"] == {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 45.0}
assert list(manifest["algorithms"]) == algs
assert plan["schema"] == "lio_benchmark_suite_plan/v1"
assert plan["profile"] == "SAME_BAG_MAPPING_V1"
assert plan["selected_algorithms"] == algs
assert plan["manifest_sha256"] == sha(run / "manifest.json")
assert plan["dataset"]["expected_bag_content_sha256"] == expected_bag_sha

# Source bag unchanged before and after estimator group.
pre = load(run / "metadata/suite/dataset_identity_pre.json")
post = load(run / "metadata/suite/dataset_identity_post.json")
assert pre["status"] == "PASS"
assert post["status"] == "PASS"
assert pre["expected_bag_content_sha256"] == expected_bag_sha
assert pre["observed_bag_content_sha256"] == expected_bag_sha
assert post["expected_bag_content_sha256"] == expected_bag_sha
assert post["observed_bag_content_sha256"] == expected_bag_sha
assert post["pre_observed_bag_content_sha256"] == expected_bag_sha

# Three invocations: interrupted first, completing resume, no-op resume.
events = [load(p) for p in sorted((run / "metadata/suite/events").glob("*.json"))]
invocations = [x["invocation_id"] for x in events if x["event_type"] == "SUITE_INVOCATION_STARTED"]
assert len(invocations) == 3
first, second, third = invocations

def starts(invocation: str) -> list[str]:
    return [
        x["stage_id"]
        for x in events
        if x["invocation_id"] == invocation and x["event_type"] == "STAGE_STARTED"
    ]

first_starts = starts(first)
second_starts = starts(second)
third_starts = starts(third)
assert "runtime/fast_livo2" in first_starts
assert "runtime/fast_lio2" not in first_starts
assert "runtime/kiss_icp" not in first_starts
assert "runtime/fast_livo2" not in second_starts
assert second_starts.count("runtime/fast_lio2") == 1
assert second_starts.count("runtime/kiss_icp") == 1
assert third_starts == []
assert any(
    x["invocation_id"] == first
    and x["event_type"] == "SUITE_STOP_REQUESTED"
    and x.get("reason_code") == "INTERRUPTED_AT_STAGE_BOUNDARY"
    for x in events
)

# FAST-LIVO2 evidence is byte-identical across resume.
before_first_resume = load(accept_root / "fast_livo2_before_resume.json")
assert sha(run / "metadata/algorithms/fast_livo2/runtime_identity.json") == before_first_resume["runtime_identity_sha256"]
assert sha(run / "metadata/run_fast_livo2.json") == before_first_resume["run_status_sha256"]

# Second resume started no scientific stage and all runtime evidence remained immutable.
before_second = load(accept_root / "before_second_resume.json")
assert sum(x["event_type"] == "STAGE_STARTED" for x in events) == before_second["stage_started_count"]
for alg in algs:
    assert sha(run / f"metadata/algorithms/{alg}/runtime_identity.json") == before_second["runtime_identity_sha256"][alg]
    assert sha(run / f"metadata/run_{alg}.json") == before_second["run_status_sha256"][alg]
    assert load(run / f"metadata/run_{alg}.json")["status"] == "PASS"
    assert load(run / f"metadata/algorithms/{alg}/runtime_identity.json")["identity_status"] == "FROZEN"

# Strict common scan and all Unified Maps.
common = run / "standardized/map_sampling/common_matched_scans.csv"
common_meta = load(run / "standardized/map_sampling/common_matched_metadata.json")
assert common.is_file()
assert common_meta["common_manifest_sha256"] == sha(common)
assert common_meta["selected_algorithms"] == algs
assert common_meta["common_matched_scan_count"] > 0
for alg in algs:
    meta = load(run / f"standardized/maps/{alg}/unified/metadata.json")
    matching = meta["timestamp_matching"]
    assert meta["scan_set_policy"] == "STRICT_COMMON_INTERSECTION"
    assert meta["common_manifest_sha256"] == sha(common)
    assert meta["point_count"] > 0
    assert matching["selected_scan_count"] > 0
    assert matching["matched_scan_count"] == matching["selected_scan_count"]
    assert matching["unmatched_scan_count"] == 0

# Relative SE(3) is exact frozen-set descriptive disagreement.
relative = load(run / "metrics/relative_se3/metadata.json")
assert relative["requested_algorithms"] == algs
assert set(relative["eligible_algorithms"]) == set(algs)
assert relative["blocked_algorithms"] == {}
assert relative["terminology"] == "PAIRWISE_DISAGREEMENT"

# Canonical clean-run Same-Bag summary exists and is final.
summary = load(run / "reports/same_bag_mapping_v1.json")
assert summary["artifact_role"] == "CANONICAL_FINAL_SUMMARY"
assert [row["algorithm_id"] for row in summary["algorithms"]] == algs

# Public artifact-derived status remains PASS after no-op resume.
status = load(accept_root / "status_after_second_resume.json")
assert status["state"] == "PASS"
assert status["selected_algorithms"] == algs
assert all(stage["state"] == "PASS" for stage in status["stages"])

print("BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_CONTRACT=PASS")
PY
```

Only the exact printed marker authorizes:

```text
BENCHMARK_SUITE_ORCHESTRATOR_V1_TARGET_MACHINE_ACCEPTANCE = PASS
```

---

## 11. Failure / blocked policy

If target acceptance exposes an implementation bug:

```text
systematic debugging
→ root cause
→ add strict regression RED
→ prove RED fails for the intended reason
→ minimal GREEN
→ full Core Contracts
→ commit new exact HEAD
→ create a new unique RUN_ID and ACCEPT_ROOT
→ rerun this acceptance from Section 1
```

Preserve the failed run and acceptance root as evidence. Do not overwrite them.

Do **not** obtain PASS by changing:

- source bag bytes;
- P1 dataset contract;
- LiDAR/IMU topics;
- MID360 internal calibration;
- IMU units;
- algorithm set/order;
- estimator executable/overlay merely to bypass a failure;
- map scan/point/voxel settings;
- trajectory time tolerance;
- strict common intersection policy;
- target assertions.

If an environment dependency is genuinely unavailable, report `BLOCKED_ENVIRONMENT`; do not silently replace it.

After target PASS, stop. Do not start P3 or a new algorithm adapter in the same acceptance session.
