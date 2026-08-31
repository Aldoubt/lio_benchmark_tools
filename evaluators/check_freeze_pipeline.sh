#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

run_dir=""
baseline="fast_livo2"
language="zh-CN"
export_output=""
open_after=0

usage() {
  cat <<'EOF'
Usage:
  evaluators/check_freeze_pipeline.sh [options]

Static/unit gate (no real run required):
  evaluators/check_freeze_pipeline.sh

Real completed-run acceptance:
  evaluators/check_freeze_pipeline.sh --run <RUN_DIR> [--baseline fast_livo2] [--lang zh-CN|en]

Options:
  --run DIR            completed benchmark run to freeze and validate
  --baseline NAME      baseline algorithm (default: fast_livo2)
  --lang LANG          report language: zh-CN or en (default: zh-CN)
  --export-output DIR  explicit export destination for real-run acceptance
  --open               launch Native Rerun after freeze validation
  -h, --help           show this help
EOF
}

while (($#)); do
  case "$1" in
    --run) run_dir=${2:?--run requires a directory}; shift 2 ;;
    --baseline) baseline=${2:?--baseline requires a value}; shift 2 ;;
    --lang) language=${2:?--lang requires zh-CN or en}; shift 2 ;;
    --export-output) export_output=${2:?--export-output requires a directory}; shift 2 ;;
    --open) open_after=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$language" != "zh-CN" && "$language" != "en" ]]; then
  echo "--lang must be zh-CN or en" >&2
  exit 2
fi

export MPLBACKEND="${MPLBACKEND:-Agg}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/lio-benchmark-matplotlib}"
mkdir -p "$MPLCONFIGDIR"
export PYTHONPATH="$repo_root/evaluators:$repo_root/benchmark_base${PYTHONPATH:+:$PYTHONPATH}"

python3 -m py_compile \
  evaluators/freeze_experiment.py \
  evaluators/freeze_rerun.py \
  evaluators/freeze_workflow.py \
  evaluators/report_data.py \
  evaluators/report_evidence.py \
  evaluators/report_html.py \
  evaluators/report_pdf.py \
  benchmark_base/lio_benchmark/entry.py \
  benchmark_base/lio_benchmark/frozen_bundle.py

python3 -m pytest -q \
  tests/test_freeze_experiment.py \
  tests/test_freeze_failure_audit.py \
  tests/test_freeze_provenance.py \
  tests/test_freeze_rerun.py \
  tests/test_report_data.py \
  tests/test_report_evidence.py \
  tests/test_report_pointcloud_evidence.py \
  tests/test_report_html.py \
  tests/test_report_pdf.py \
  tests/test_frozen_bundle.py \
  tests/test_entry_frozen_commands.py \
  tests/test_freeze_workflow.py \
  tests/test_viewer_projection.py \
  tests/test_rerun_diagnostic_viewer.py \
  tests/test_entry.py \
  tests/test_postprocess.py \
  tests/test_current_run_report.py \
  tests/test_diagnostic_timeline.py

git diff --check

echo "freeze/native-delivery static regression gate passed"

if [[ -z "$run_dir" ]]; then
  cat <<'EOF'
No --run supplied: real completed-run acceptance was not executed.
Provide --run to verify an actual COMPLETE freeze, immutable source artifacts, frozen-only export, and optionally Native open.
EOF
  exit 0
fi

run_dir=$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$run_dir")
if [[ ! -d "$run_dir" || ! -f "$run_dir/manifest.json" ]]; then
  echo "invalid benchmark run: $run_dir" >&2
  exit 2
fi

before_hashes=$(mktemp)
after_hashes=$(mktemp)
cleanup() { rm -f "$before_hashes" "$after_hashes"; }
trap cleanup EXIT

python3 - "$run_dir" >"$before_hashes" <<'PY'
import hashlib, json, sys
from pathlib import Path
run = Path(sys.argv[1])
paths = [
    run / "manifest.json",
    run / "metadata/run_status.json",
    run / "metrics/full_comparison.json",
    run / "metrics/trajectory_discontinuity.json",
    run / "metrics/diagnostic_timeline.json",
]
for trajectory in sorted((run / "standardized/trajectories").glob("*.csv")):
    paths.append(trajectory)
result = {}
for path in paths:
    if path.is_file():
        result[str(path.relative_to(run))] = hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(result, sort_keys=True))
PY

freeze_output=$(benchmark_base/bin/lio-benchmark freeze \
  --run "$run_dir" \
  --baseline "$baseline" \
  --lang "$language")
printf '%s\n' "$freeze_output"

frozen=$(printf '%s\n' "$freeze_output" | python3 -c '
import json, sys
selected = None
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        continue
    if isinstance(value, dict) and value.get("frozen"):
        selected = value
if not selected:
    raise SystemExit("freeze output did not contain frozen path JSON")
if selected.get("freeze_state") != "COMPLETE":
    raise SystemExit(f"freeze did not complete: {selected}")
print(selected["frozen"])
')

python3 - "$run_dir" >"$after_hashes" <<'PY'
import hashlib, json, sys
from pathlib import Path
run = Path(sys.argv[1])
paths = [
    run / "manifest.json",
    run / "metadata/run_status.json",
    run / "metrics/full_comparison.json",
    run / "metrics/trajectory_discontinuity.json",
    run / "metrics/diagnostic_timeline.json",
]
for trajectory in sorted((run / "standardized/trajectories").glob("*.csv")):
    paths.append(trajectory)
result = {}
for path in paths:
    if path.is_file():
        result[str(path.relative_to(run))] = hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(result, sort_keys=True))
PY

if ! cmp -s "$before_hashes" "$after_hashes"; then
  echo "source run core artifacts changed during freeze" >&2
  diff -u "$before_hashes" "$after_hashes" || true
  exit 1
fi

python3 - "$frozen" <<'PY'
import json, sys
from pathlib import Path
from lio_benchmark.frozen_bundle import verify_registered_artifact
frozen = Path(sys.argv[1]).resolve()
manifest = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
if manifest.get("freeze_state") != "COMPLETE":
    raise SystemExit("freeze_manifest.json is not COMPLETE")
required = {
    "viewer/diagnostic.rrd",
    "report_data.json",
    "evidence/evidence_manifest.json",
    "report/index.html",
    "report/report.pdf",
}
registered = {
    str(item.get("path"))
    for item in manifest.get("generated_artifacts", [])
    if isinstance(item, dict) and item.get("path")
}
missing = sorted(required - registered)
if missing:
    raise SystemExit(f"required generated artifacts are not registered: {missing}")
for relative in sorted(registered):
    verify_registered_artifact(frozen, relative)
print(json.dumps({"freeze": str(frozen), "verified_generated_artifacts": len(registered)}, ensure_ascii=False))
PY

if [[ -z "$export_output" ]]; then
  export_output="${frozen}_acceptance_export"
fi
if [[ -e "$export_output" ]]; then
  echo "acceptance export output already exists: $export_output" >&2
  exit 2
fi

benchmark_base/bin/lio-benchmark export "$frozen" --output "$export_output"
for path in \
  "$export_output/report.html" \
  "$export_output/report.pdf" \
  "$export_output/metrics/summary.json" \
  "$export_output/metrics/summary.csv" \
  "$export_output/provenance/freeze_manifest.json"; do
  test -s "$path" || { echo "missing/empty export artifact: $path" >&2; exit 1; }
done

if ((open_after)); then
  benchmark_base/bin/lio-benchmark open "$frozen"
fi

cat <<EOF
real completed-run freeze acceptance passed:
  source run: $run_dir
  frozen:     $frozen
  export:     $export_output
  native open executed: $open_after
EOF
