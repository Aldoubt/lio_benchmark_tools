# Same-Bag Mapping Benchmark V1 Verification

Date: 2026-08-17
Branch: `feat/lio-baseline-suite`

## Scope

This is the target-machine runbook for the first full-bag Same-Bag Mapping Benchmark V1.

Repository-side implementation must be accepted before this runbook is used. This document deliberately stops before any target-machine result is claimed.

The full-bag baseline is exactly:

```text
fast_livo2
fast_lio2
kiss_icp
```

The frozen replay contract is:

```text
profile = DEFAULT_ADAPTED
rate = 1.0
start_offset_s = 0.0
duration_s = 622.99
execution = sequential
scientific_status = DESCRIPTIVE_NO_GROUND_TRUTH
performance_status = SINGLE_RUN_DESCRIPTIVE
```

Do not add Point-LIO, DLIO, LIO-SAM, Leg-KILO, GLIM, Faster-LIO or SLICT during this target acceptance.

## Scientific / fairness boundary

The target run establishes reproducible execution, input/output artifact inventory, resource evidence and strict same-scan Unified Map reconstruction for one complete MID360 bag.

It does not establish ground-truth trajectory or map accuracy. KISS-ICP remains a LiDAR-only control and is not disguised as the same sensor-modality estimator as FAST-LIVO2 / FAST-LIO2.

Native Map means only a map naturally produced/collected by the frozen runtime profile. Do not enable an optional upstream native-map mode merely to populate the table if it changes runtime cost. Missing native maps are valid `NOT_PROVIDED` / `MISSING` evidence.

Unified Maps are the formal visual comparison surface and must use `STRICT_COMMON_INTERSECTION`.

## 1. Repository and expected HEAD gate

The handoff prompt must export the exact repository-accepted HEAD as `SAME_BAG_MAPPING_V1_EXPECTED_HEAD`.

```bash
set -euo pipefail
cd ~/lio_benchmark_tools
git switch feat/lio-baseline-suite
git pull --ff-only

test -n "${SAME_BAG_MAPPING_V1_EXPECTED_HEAD:-}" || {
  echo "missing SAME_BAG_MAPPING_V1_EXPECTED_HEAD"
  exit 1
}

HEAD=$(git rev-parse HEAD)
test "$HEAD" = "$SAME_BAG_MAPPING_V1_EXPECTED_HEAD" || {
  echo "unexpected HEAD: $HEAD"
  exit 1
}

git status --short
```

Do not use `reset --hard`, do not overwrite local changes, and do not proceed if an unexplained local modification can affect the benchmark implementation or configuration.

## 2. Freeze the target config

```bash
CONFIG=benchmark_base/config/green_house_three_full_bag_v1.json
python3 benchmark_base/bin/lio-benchmark validate --config "$CONFIG"

python3 - "$CONFIG" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
x = json.loads(p.read_text())
assert x["name"] == "green_house_three_full_bag_v1"
assert x["dataset"] == "green_house_mid360"
assert x["algorithms"] == ["fast_livo2", "fast_lio2", "kiss_icp"]
assert x["replay"] == {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 622.99}
print("SAME_BAG_MAPPING_V1_CONFIG=PASS")
PY
```

The current dataset registry identifies the greenhouse MID360 source at its configured path and uses the accepted manufacturer-spec internal LiDAR/IMU geometry. Do not edit the bag, topics, calibration or adapter parameters during acceptance.

## 3. Create one new immutable full-bag run

Use a new run id. Never reuse Representative Window V1 child runs or any historical full-bag run.

```bash
RUN_ID="samebag_v1_full_$(date +%Y%m%d_%H%M%S)"
RUN=$(python3 benchmark_base/bin/lio-benchmark init \
  --config "$CONFIG" \
  --run-id "$RUN_ID" | tail -n1)

echo "RUN=$RUN"
test -d "$RUN"
```

If `init` reports that the run already exists, choose a new run id. Do not delete or overwrite the old run.

## 4. Snapshot, bag inspection and preflight

```bash
python3 benchmark_base/bin/lio-benchmark snapshot --run "$RUN"
python3 benchmark_base/bin/lio-benchmark analyze-bag --run "$RUN"
python3 benchmark_base/bin/lio-benchmark preflight --run "$RUN"
```

All three algorithms must be runnable under the frozen runtime paths/overlays before estimator replay starts.

If any algorithm is `BLOCKED_*`, stop and diagnose the environment. Do not silently replace an executable, overlay, topic, calibration or config.

## 5. Run the full bag exactly once per algorithm, sequentially

This is the first step in this phase that executes the complete 622.99 s estimator replay.

```bash
for ALG in fast_livo2 fast_lio2 kiss_icp; do
  echo "===== FULL BAG: $ALG ====="
  python3 benchmark_base/bin/lio-benchmark run \
    --run "$RUN" \
    --algorithm "$ALG"
done
```

Do not use concurrent estimator execution. Do not repeat a successful full-bag algorithm run inside the same immutable run. Runtime identity and runtime metrics are intentionally non-overwritable.

Expected new performance evidence:

```text
metrics/runtime/fast_livo2.json
metrics/runtime/fast_lio2.json
metrics/runtime/kiss_icp.json
```

Each record uses:

```text
schema = lio_benchmark_runtime_performance/v1
performance interpretation = SINGLE_RUN_DESCRIPTIVE
```

On the target Linux host the expected measurement method is `LINUX_PROC_PROCESS_SESSION_V1`.

## 6. Standardize all trajectories

```bash
for ALG in fast_livo2 fast_lio2 kiss_icp; do
  python3 benchmark_base/bin/lio-benchmark standardize trajectory-from-run \
    --run "$RUN" \
    --algorithm "$ALG"
done
```

Do not sort, retime, repair or manually edit standardized trajectories.

## 7. Timestamp, frame, provenance and coverage gates

```bash
python3 benchmark_base/bin/lio-benchmark audit trajectory-timestamps \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp

python3 benchmark_base/bin/lio-benchmark audit trajectory-frames \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp

python3 benchmark_base/bin/lio-benchmark audit runtime-provenance \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp

python3 benchmark_base/bin/lio-benchmark audit trajectory-coverage \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp
```

Acceptance requires zero effective timestamp regressions. Frame and runtime-provenance rows must remain `MATCH`. Coverage remains descriptive and is not converted into an accuracy score.

## 8. Freeze the selected scans and strict common intersection

```bash
python3 benchmark_base/bin/lio-benchmark standardize scan-manifest --run "$RUN"
python3 benchmark_base/bin/lio-benchmark standardize common-map-manifest --run "$RUN"
```

Required strict evidence:

```text
standardized/map_sampling/selected_scans.csv
standardized/map_sampling/common_matched_scans.csv
standardized/map_sampling/common_matched_metadata.json
```

Do not use `--overwrite` and do not introduce an algorithm subset or tolerance override.

## 9. Reconstruct all three strict Unified Maps

```bash
for ALG in fast_livo2 fast_lio2 kiss_icp; do
  python3 benchmark_base/bin/lio-benchmark standardize map \
    --run "$RUN" \
    --algorithm "$ALG"
done
```

Required formal map artifacts:

```text
standardized/maps/<algorithm>/unified/map.ply
standardized/maps/<algorithm>/unified/metadata.json
```

The existing metadata contract stores `scan_set_policy` at the metadata root and scan counts inside `timestamp_matching`:

```text
metadata.scan_set_policy = STRICT_COMMON_INTERSECTION
metadata.timestamp_matching.matched_scan_count = selected_scan_count
metadata.timestamp_matching.unmatched_scan_count = 0
metadata.point_count > 0
```

Point counts may legitimately differ between algorithms.

## 10. Existing Relative SE(3) descriptive comparison

```bash
python3 benchmark_base/bin/lio-benchmark compare relative-se3 \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp
```

This is not ground truth. Keep terminology as `PAIRWISE_DISAGREEMENT` / `DESCRIPTIVE_NO_GROUND_TRUTH`.

## 11. Generate Same-Bag I/O / performance / map inventory

```bash
python3 benchmark_base/bin/lio-benchmark summarize same-bag --run "$RUN"
```

This command is read-only with respect to estimator, trajectory and map evidence and creates exactly its own summary artifacts:

```text
reports/algorithm_io_matrix.csv
reports/algorithm_io_matrix.md
metrics/runtime_performance.csv
reports/same_bag_mapping_v1.json
```

Do not rerun it after these files exist; V1 refuses silent overwrite.

## 12. Machine acceptance contract

Run this exact check after all preceding commands succeed:

```bash
python3 - "$RUN" <<'PY'
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

run = Path(sys.argv[1]).resolve()
algs = ["fast_livo2", "fast_lio2", "kiss_icp"]

manifest = json.loads((run / "manifest.json").read_text())
assert list(manifest["algorithms"]) == algs
assert manifest["replay"] == {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 622.99}

for alg in algs:
    status = json.loads((run / "metadata" / f"run_{alg}.json").read_text())
    assert status["status"] == "PASS", (alg, status)
    assert status["returncode"] == 0, (alg, status)

    identity = json.loads((run / "metadata" / "algorithms" / alg / "runtime_identity.json").read_text())
    assert identity["identity_status"] == "FROZEN", (alg, identity)

    perf = json.loads((run / "metrics" / "runtime" / f"{alg}.json").read_text())
    assert perf["schema"] == "lio_benchmark_runtime_performance/v1"
    assert perf["algorithm_id"] == alg
    assert perf["returncode"] == 0
    assert perf["status"] == "PASS"
    assert perf["wall_time_s"] > 0
    assert perf["cpu_total_s"] >= 0
    assert perf["max_rss_kib"] is not None and perf["max_rss_kib"] > 0

    traj = run / "standardized" / "trajectories" / f"{alg}.csv"
    assert traj.is_file() and traj.stat().st_size > 0

    ts = json.loads((run / "metadata" / "trajectory_timestamp_audit" / f"{alg}.json").read_text())
    assert ts["summary"]["effective_regression_count"] == 0, (alg, ts["summary"])

with (run / "metrics" / "trajectory_frame_audit.csv").open(newline="", encoding="utf-8") as f:
    frame_rows = list(csv.DictReader(f))
assert {r["algorithm_id"] for r in frame_rows} == set(algs)
assert all(r["status"] == "MATCH" for r in frame_rows), frame_rows

with (run / "metrics" / "runtime_provenance.csv").open(newline="", encoding="utf-8") as f:
    provenance_rows = list(csv.DictReader(f))
assert {r["algorithm_id"] for r in provenance_rows} == set(algs)
assert all(r["status"] == "MATCH" for r in provenance_rows), provenance_rows

with (run / "metrics" / "trajectory_coverage.csv").open(newline="", encoding="utf-8") as f:
    coverage_rows = list(csv.DictReader(f))
assert [r["algorithm_id"] for r in coverage_rows] == algs

common_csv = run / "standardized" / "map_sampling" / "common_matched_scans.csv"
common_meta = run / "standardized" / "map_sampling" / "common_matched_metadata.json"
assert common_csv.is_file() and common_csv.stat().st_size > 0
assert common_meta.is_file()

for alg in algs:
    map_path = run / "standardized" / "maps" / alg / "unified" / "map.ply"
    metadata_path = run / "standardized" / "maps" / alg / "unified" / "metadata.json"
    assert map_path.is_file() and map_path.stat().st_size > 0, alg
    meta = json.loads(metadata_path.read_text())
    assert meta["scan_set_policy"] == "STRICT_COMMON_INTERSECTION", (alg, meta)
    matching = meta["timestamp_matching"]
    assert matching["matched_scan_count"] == matching["selected_scan_count"], (alg, matching)
    assert matching["unmatched_scan_count"] == 0, (alg, matching)
    assert meta["point_count"] > 0, (alg, meta["point_count"])

summary_path = run / "reports" / "same_bag_mapping_v1.json"
summary = json.loads(summary_path.read_text())
assert summary["schema"] == "lio_benchmark_same_bag_mapping/v1"
assert summary["scientific_status"] == "DESCRIPTIVE_NO_GROUND_TRUTH"
assert summary["performance_status"] == "SINGLE_RUN_DESCRIPTIVE"
assert summary["benchmark_profile"] == "DEFAULT_ADAPTED"
assert [row["algorithm_id"] for row in summary["algorithms"]] == algs
assert all(row["strict_common_scan_policy"] == "STRICT_COMMON_INTERSECTION" for row in summary["algorithms"])
assert all("map_accuracy" not in row for row in summary["algorithms"])

for path in (
    run / "reports" / "algorithm_io_matrix.csv",
    run / "reports" / "algorithm_io_matrix.md",
    run / "metrics" / "runtime_performance.csv",
    summary_path,
):
    assert path.is_file() and path.stat().st_size > 0, path

print("SAME_BAG_MAPPING_V1_TARGET_CONTRACT=PASS")
for row in summary["algorithms"]:
    print(
        row["algorithm_id"],
        "modalities=", row["effective_modalities"],
        "runtime=", row["run_status"],
        "wall_s=", row["wall_time_s"],
        "cpu_s=", row["cpu_total_s"],
        "peak_rss_kib=", row["max_rss_kib"],
        "native_map=", row["native_map_status"],
        "unified_map=", row["unified_map_status"],
        "unified_points=", row["unified_map_point_count"],
    )
PY
```

Only print/claim target PASS after this machine check succeeds.

## 13. Visualization after machine PASS

These human-facing views are not required for the machine contract:

```bash
python3 benchmark_base/bin/lio-benchmark inspect \
  --run "$RUN" \
  --map-kind unified \
  --display-alignment START_XY_YAW

python3 benchmark_base/bin/lio-benchmark report \
  --run "$RUN" \
  --display-alignment START_XY_YAW

python3 benchmark_base/bin/lio-benchmark demo \
  --run "$RUN" \
  --algorithms fast_livo2 fast_lio2 kiss_icp \
  --display-alignment START_XY_YAW
```

Native maps may also be inspected where available. A missing Native Map is not an acceptance failure if the frozen/default runtime profile does not provide one.

## Target-machine stop condition

Stop after reporting:

```text
SAME_BAG_MAPPING_V1_TARGET_CONTRACT=PASS
```

and the three per-algorithm summary rows plus:

```bash
cat "$RUN/reports/algorithm_io_matrix.md"
git status --short
```

Do not begin new algorithm adapters or greenhouse-specific tuning in the same task.

## Current acceptance state

```text
SAME_BAG_MAPPING_V1_REPOSITORY_ACCEPTANCE = PENDING_EXACT_HEAD_CI
SAME_BAG_MAPPING_V1_TARGET_MACHINE_ACCEPTANCE = PENDING
```

Repository acceptance changes to PASS only after a fresh exact-head Core Contracts run succeeds. Target acceptance remains pending until Codex executes this runbook on the target machine.
