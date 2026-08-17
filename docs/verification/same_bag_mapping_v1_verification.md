# Same-Bag Mapping Benchmark V1 Verification

Date: 2026-08-17
Branch: `feat/lio-baseline-suite`

## Scope

This document is the target-machine acceptance and recovery runbook for Same-Bag Mapping Benchmark V1.

The frozen full-bag baseline is exactly:

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

Do not add Point-LIO, DLIO, LIO-SAM, Leg-KILO, GLIM, Faster-LIO or SLICT during this acceptance.

## Scientific / fairness boundary

This benchmark establishes reproducible execution, run-local input/output evidence, single-run resource evidence, and strict same-scan Unified Map reconstruction for one complete MID360 bag.

It does **not** establish ground-truth trajectory accuracy, map accuracy, causal failure labels, or objective estimator ranking.

KISS-ICP remains a LiDAR-only control. FAST-LIVO2 and FAST-LIO2 use LiDAR + IMU. Do not describe the three algorithms as having identical sensor modality.

Native Map means only an upstream/default artifact naturally present under the frozen runtime profile. A missing Native Map is valid `MISSING` / `NOT_PROVIDED` evidence and is not an acceptance failure.

Unified Maps are the formal map comparison surface and must use:

```text
STRICT_COMMON_INTERSECTION
```

Relative SE(3) remains:

```text
PAIRWISE_DISAGREEMENT
DESCRIPTIVE_NO_GROUND_TRUTH
```

## 1. Repository gate

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

Do not use `reset --hard`, do not discard local changes, and do not proceed if an unexplained modification can affect benchmark code/configuration.

## 2. Frozen target config

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

Do not edit the bag, topics, manufacturer-spec MID360 internal LiDAR/IMU geometry, runtime executable, runtime overlays, scan sampling contract, or trajectory matching tolerance during acceptance.

## 3. Clean-run execution path

For a **new** run, create a new immutable run ID and execute the following order exactly once:

```text
init
snapshot
analyze-bag
preflight
fast_livo2 full bag
fast_lio2 full bag
kiss_icp full bag
trajectory-from-run x3
trajectory timestamp audit
trajectory frame audit
runtime provenance audit
trajectory coverage audit
scan-manifest
common-map-manifest
strict Unified Map x3
Relative SE(3)
summarize same-bag
machine acceptance
```

The estimator execution commands remain sequential:

```bash
RUN_ID="samebag_v1_full_$(date +%Y%m%d_%H%M%S)"
RUN=$(python3 benchmark_base/bin/lio-benchmark init \
  --config "$CONFIG" \
  --run-id "$RUN_ID" | tail -n1)

python3 benchmark_base/bin/lio-benchmark snapshot --run "$RUN"
python3 benchmark_base/bin/lio-benchmark analyze-bag --run "$RUN"
python3 benchmark_base/bin/lio-benchmark preflight --run "$RUN"

for ALG in fast_livo2 fast_lio2 kiss_icp; do
  python3 benchmark_base/bin/lio-benchmark run --run "$RUN" --algorithm "$ALG"
done
```

Do not run estimators concurrently and do not repeat a successful estimator inside the same immutable run.

Continue with:

```bash
for ALG in fast_livo2 fast_lio2 kiss_icp; do
  python3 benchmark_base/bin/lio-benchmark standardize trajectory-from-run \
    --run "$RUN" --algorithm "$ALG"
done

python3 benchmark_base/bin/lio-benchmark audit trajectory-timestamps \
  --run "$RUN" --algorithms fast_livo2 fast_lio2 kiss_icp

python3 benchmark_base/bin/lio-benchmark audit trajectory-frames \
  --run "$RUN" --algorithms fast_livo2 fast_lio2 kiss_icp

python3 benchmark_base/bin/lio-benchmark audit runtime-provenance \
  --run "$RUN" --algorithms fast_livo2 fast_lio2 kiss_icp

python3 benchmark_base/bin/lio-benchmark audit trajectory-coverage \
  --run "$RUN" --algorithms fast_livo2 fast_lio2 kiss_icp

python3 benchmark_base/bin/lio-benchmark standardize scan-manifest --run "$RUN"
python3 benchmark_base/bin/lio-benchmark standardize common-map-manifest --run "$RUN"

for ALG in fast_livo2 fast_lio2 kiss_icp; do
  python3 benchmark_base/bin/lio-benchmark standardize map --run "$RUN" --algorithm "$ALG"
done

python3 benchmark_base/bin/lio-benchmark compare relative-se3 \
  --run "$RUN" --algorithms fast_livo2 fast_lio2 kiss_icp

python3 benchmark_base/bin/lio-benchmark summarize same-bag --run "$RUN"
```

### Canonical summary readiness gate

`summary same-bag` is now fail-closed. It refuses to create the immutable canonical summary until every selected algorithm has:

```text
run_status = PASS
runtime_identity_status = FROZEN
trajectory_status = AVAILABLE
runtime performance evidence = present
Unified Map = AVAILABLE
scan_set_policy = STRICT_COMMON_INTERSECTION
selected_scan_count > 0
matched_scan_count = selected_scan_count
unmatched_scan_count = 0
Unified Map point_count > 0
```

Native Map availability is deliberately **not** a readiness requirement.

This prevents a future run from freezing a canonical summary while strict Unified Maps are still being generated.

## 4. Frame-audit status semantics

Do not conflate raw evidence availability with semantic contract classification.

The raw trajectory frame audit CSV has the evidence-layer status:

```text
metrics/trajectory_frame_audit.csv
status = AVAILABLE
```

`AVAILABLE` means the raw frame evidence was successfully observed/audited.

The semantic contract comparison is recorded by runtime provenance:

```text
metrics/runtime_provenance.csv
status = MATCH
frame_contract_status = MATCH
```

Therefore target acceptance requires:

```text
raw frame audit status = AVAILABLE
runtime provenance status = MATCH
runtime provenance frame_contract_status = MATCH
```

It must **not** require `trajectory_frame_audit.csv.status == MATCH`.

## 5. Strict Unified Map contract

Required artifacts:

```text
standardized/map_sampling/selected_scans.csv
standardized/map_sampling/common_matched_scans.csv
standardized/map_sampling/common_matched_metadata.json
standardized/maps/<algorithm>/unified/map.ply
standardized/maps/<algorithm>/unified/metadata.json
```

Map metadata stores the strict policy at the metadata root and matching counts inside `timestamp_matching`:

```text
metadata.scan_set_policy = STRICT_COMMON_INTERSECTION
metadata.timestamp_matching.matched_scan_count = selected_scan_count
metadata.timestamp_matching.unmatched_scan_count = 0
metadata.point_count > 0
```

Point counts may legitimately differ between algorithms.

## 6. Failed target attempt preserved as evidence

The first target attempt used:

```text
repository HEAD = 82b652ac08166511d8f492fca32c87e80a4910e0
run = /home/yangxuan/lio_benchmark_runs/green_house/samebag_v1_full_20260817_162851
result = SAME_BAG_MAPPING_V1_TARGET_CONTRACT=FAIL
```

The estimator and map evidence from that run must be preserved.

Observed full-bag estimator status was `PASS` for all three algorithms. Strict Unified Maps were subsequently completed with:

```text
common scan count = 829
common manifest SHA256 = 0acf35ab766239e8ceea7b01b6525317b0c2441e6859753a5a131df819fdf335
fast_livo2 selected/matched/unmatched = 829 / 829 / 0
fast_lio2  selected/matched/unmatched = 829 / 829 / 0
kiss_icp   selected/matched/unmatched = 829 / 829 / 0
```

The target failed because:

1. the canonical immutable Same-Bag summary was generated before the Unified Maps completed and therefore froze `MISSING` map status;
2. the old machine contract incorrectly required raw frame-audit `status=MATCH` although the raw evidence layer correctly reports `AVAILABLE`.

Do **not** delete, overwrite, edit, or replace the old canonical summary. It is historical evidence of the premature-summary bug.

Do **not** rerun the estimators or rebuild the already-complete maps merely to recover this acceptance.

## 7. Append-only recovery path for the preserved failed run

After pulling the repository recovery HEAD, set:

```bash
RUN=/home/yangxuan/lio_benchmark_runs/green_house/samebag_v1_full_20260817_162851
```

Confirm the historical canonical summary still exists:

```bash
test -f "$RUN/reports/same_bag_mapping_v1.json"
test -f "$RUN/reports/algorithm_io_matrix.csv"
test -f "$RUN/reports/algorithm_io_matrix.md"
test -f "$RUN/metrics/runtime_performance.csv"
```

Then run exactly one append-only finalization:

```bash
python3 benchmark_base/bin/lio-benchmark summarize same-bag-finalize --run "$RUN"
```

The command must **not** run ROS, read/replay the source bag, execute an estimator, standardize a trajectory, or rebuild a map.

It writes a new independent package only at:

```text
reports/same_bag_mapping_v1_finalization/algorithm_io_matrix.csv
reports/same_bag_mapping_v1_finalization/algorithm_io_matrix.md
reports/same_bag_mapping_v1_finalization/runtime_performance.csv
reports/same_bag_mapping_v1_finalization/same_bag_mapping_v1.json
reports/same_bag_mapping_v1_finalization/lineage.json
```

The original four canonical summary files remain byte-for-byte unchanged.

The finalization lineage records:

```text
schema = lio_benchmark_same_bag_mapping_finalization/v1
reason = PREMATURE_IMMUTABLE_SUMMARY
mutation_policy = APPEND_ONLY_NO_SOURCE_OVERWRITE
source_summary_sha256 = SHA256(original reports/same_bag_mapping_v1.json)
```

A second finalization attempt must be refused rather than overwrite the first finalization package.

## 8. Corrected machine acceptance contract

Run this check after either:

- a clean new run has successfully generated its canonical final summary; or
- the preserved failed run has successfully generated the append-only finalization package.

```bash
python3 - "$RUN" <<'PY'
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys

run = Path(sys.argv[1]).resolve()
algs = ["fast_livo2", "fast_lio2", "kiss_icp"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


manifest = json.loads((run / "manifest.json").read_text())
assert list(manifest["algorithms"]) == algs
assert manifest["replay"] == {
    "rate": 1.0,
    "start_offset_s": 0.0,
    "duration_s": 622.99,
}

for alg in algs:
    status = json.loads((run / "metadata" / f"run_{alg}.json").read_text())
    assert status["status"] == "PASS", (alg, status)
    assert status["returncode"] == 0, (alg, status)

    identity = json.loads(
        (run / "metadata" / "algorithms" / alg / "runtime_identity.json").read_text()
    )
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

    ts = json.loads(
        (run / "metadata" / "trajectory_timestamp_audit" / f"{alg}.json").read_text()
    )
    assert ts["summary"]["effective_regression_count"] == 0, (alg, ts["summary"])

with (run / "metrics" / "trajectory_frame_audit.csv").open(
    newline="", encoding="utf-8"
) as f:
    frame_rows = list(csv.DictReader(f))
assert {r["algorithm_id"] for r in frame_rows} == set(algs)
assert all(r["status"] == "AVAILABLE" for r in frame_rows), frame_rows

with (run / "metrics" / "runtime_provenance.csv").open(
    newline="", encoding="utf-8"
) as f:
    provenance_rows = list(csv.DictReader(f))
assert {r["algorithm_id"] for r in provenance_rows} == set(algs)
assert all(r["status"] == "MATCH" for r in provenance_rows), provenance_rows
assert all(r["frame_contract_status"] == "MATCH" for r in provenance_rows), provenance_rows

with (run / "metrics" / "trajectory_coverage.csv").open(
    newline="", encoding="utf-8"
) as f:
    coverage_rows = list(csv.DictReader(f))
assert [r["algorithm_id"] for r in coverage_rows] == algs

common_csv = run / "standardized" / "map_sampling" / "common_matched_scans.csv"
common_meta_path = run / "standardized" / "map_sampling" / "common_matched_metadata.json"
assert common_csv.is_file() and common_csv.stat().st_size > 0
assert common_meta_path.is_file()

for alg in algs:
    map_path = run / "standardized" / "maps" / alg / "unified" / "map.ply"
    metadata_path = run / "standardized" / "maps" / alg / "unified" / "metadata.json"
    assert map_path.is_file() and map_path.stat().st_size > 0, alg
    meta = json.loads(metadata_path.read_text())
    assert meta["scan_set_policy"] == "STRICT_COMMON_INTERSECTION", (alg, meta)
    matching = meta["timestamp_matching"]
    assert matching["selected_scan_count"] > 0, (alg, matching)
    assert matching["matched_scan_count"] == matching["selected_scan_count"], (
        alg,
        matching,
    )
    assert matching["unmatched_scan_count"] == 0, (alg, matching)
    assert meta["point_count"] > 0, (alg, meta["point_count"])

canonical_summary_path = run / "reports" / "same_bag_mapping_v1.json"
final_dir = run / "reports" / "same_bag_mapping_v1_finalization"
final_summary_path = final_dir / "same_bag_mapping_v1.json"
lineage_path = final_dir / "lineage.json"

if final_summary_path.is_file():
    summary_path = final_summary_path
    lineage = json.loads(lineage_path.read_text())
    assert lineage["schema"] == "lio_benchmark_same_bag_mapping_finalization/v1"
    assert lineage["reason"] == "PREMATURE_IMMUTABLE_SUMMARY"
    assert lineage["mutation_policy"] == "APPEND_ONLY_NO_SOURCE_OVERWRITE"
    assert canonical_summary_path.is_file()
    assert lineage["source_summary_sha256"] == sha256(canonical_summary_path)
else:
    summary_path = canonical_summary_path

summary = json.loads(summary_path.read_text())
assert summary["schema"] == "lio_benchmark_same_bag_mapping/v1"
assert summary["scientific_status"] == "DESCRIPTIVE_NO_GROUND_TRUTH"
assert summary["performance_status"] == "SINGLE_RUN_DESCRIPTIVE"
assert summary["benchmark_profile"] == "DEFAULT_ADAPTED"
assert [row["algorithm_id"] for row in summary["algorithms"]] == algs

for row in summary["algorithms"]:
    assert row["run_status"] == "PASS", row
    assert row["trajectory_status"] == "AVAILABLE", row
    assert row["unified_map_status"] == "AVAILABLE", row
    assert row["strict_common_scan_policy"] == "STRICT_COMMON_INTERSECTION", row
    assert row["selected_scan_count"] > 0, row
    assert row["matched_scan_count"] == row["selected_scan_count"], row
    assert row["unmatched_scan_count"] == 0, row
    assert row["unified_map_point_count"] > 0, row
    assert "map_accuracy" not in row

print("SAME_BAG_MAPPING_V1_TARGET_CONTRACT=PASS")
print("summary_path=", summary_path)
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

Only claim target PASS if this exact corrected contract prints:

```text
SAME_BAG_MAPPING_V1_TARGET_CONTRACT=PASS
```

## 9. Recovery stop condition

For the preserved failed run, after the corrected contract passes, return:

```bash
cat "$RUN/reports/same_bag_mapping_v1_finalization/algorithm_io_matrix.md"
cat "$RUN/reports/same_bag_mapping_v1_finalization/lineage.json"
git status --short
```

Then stop.

Do not:

- rerun the 622.99 s estimators;
- rebuild already-complete maps;
- delete or overwrite stale canonical summary artifacts;
- add new algorithms;
- tune greenhouse-specific estimator parameters;
- start a second performance trial.

## Current acceptance state

The failed run remains target `FAIL` until the append-only recovery command and corrected machine acceptance contract are executed on the target machine.

Repository recovery acceptance may be marked PASS only after the final recovery documentation HEAD passes a fresh complete Core Contracts run.

```text
SAME_BAG_MAPPING_V1_TARGET_MACHINE_ACCEPTANCE = FAIL_PENDING_APPEND_ONLY_RECOVERY
```
