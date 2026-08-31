#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

run_dir=""
baseline="fast_livo2"
language="zh-CN"
export_output=""
open_after=0
system_python="${LIO_SYSTEM_PYTHON:-python3}"
freeze_python="${LIO_FREEZE_PYTHON:-$repo_root/.venv-freeze/bin/python}"

usage() {
  cat <<'EOF'
Usage:
  evaluators/check_freeze_pipeline.sh [options]

Static/unit gate (isolated freeze venv required):
  evaluators/setup_freeze_venv.sh
  evaluators/check_freeze_pipeline.sh

Real completed-run acceptance:
  evaluators/setup_freeze_venv.sh
  evaluators/check_freeze_pipeline.sh --run <RUN_DIR> [--baseline fast_livo2] [--lang zh-CN|en]

Options:
  --run DIR             completed benchmark run to freeze and validate
  --baseline NAME       baseline algorithm (default: fast_livo2)
  --lang LANG           report language: zh-CN or en (default: zh-CN)
  --freeze-python FILE  isolated freeze Python (default: .venv-freeze/bin/python)
  --export-output DIR   explicit export destination for real-run acceptance
  --open                launch Native Rerun after freeze validation
  -h, --help            show this help

Environment policy:
  - ROS/legacy scientific-stack regression uses system Python with PYTHONNOUSERSITE=1
  - freeze/report/Native Rerun regression and real freeze work use isolated freeze Python
  - freeze dependency installation and runtime both ignore ~/.local
  - do not install rerun-sdk / NumPy 2 into the ROS system or ~/.local stack
EOF
}

while (($#)); do
  case "$1" in
    --run) run_dir=${2:?--run requires a directory}; shift 2 ;;
    --baseline) baseline=${2:?--baseline requires a value}; shift 2 ;;
    --lang) language=${2:?--lang requires zh-CN or en}; shift 2 ;;
    --freeze-python) freeze_python=${2:?--freeze-python requires a file}; shift 2 ;;
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

system_py() {
  env PYTHONNOUSERSITE=1 "$system_python" "$@"
}

system_py - <<'PY'
import sys
import numpy
import scipy
from scipy.spatial import cKDTree

_ = cKDTree([[0.0, 0.0, 0.0]])
print(
    f"system scientific stack: python={sys.executable} "
    f"numpy={numpy.__version__} scipy={scipy.__version__}"
)
PY

# Keep the venv launcher path itself. A venv's bin/python is normally a symlink
# to the base interpreter; Path.resolve()/realpath would follow it and silently
# turn the freeze interpreter back into /usr/bin/python3.
freeze_python=$(system_py -c 'import os, sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$freeze_python")
if [[ ! -x "$freeze_python" ]]; then
  cat >&2 <<EOF
isolated freeze Python is unavailable: $freeze_python
Create or repair it first with:
  ./evaluators/setup_freeze_venv.sh
Or pass an equivalent environment with:
  --freeze-python /path/to/venv/bin/python
EOF
  exit 2
fi

freeze_bin_dir=$(dirname "$freeze_python")
freeze_py() {
  env PYTHONNOUSERSITE=1 PATH="$freeze_bin_dir:$PATH" "$freeze_python" "$@"
}

freeze_py - <<'PY'
import sys
import jinja2
import matplotlib
import numpy
import pyarrow
import rerun
import scipy
from scipy.spatial import cKDTree

_ = cKDTree([[0.0, 0.0, 0.0]])
if int(numpy.__version__.split('.', 1)[0]) < 2:
    raise SystemExit(f"freeze Python must use NumPy 2 for rerun-sdk 0.36.3: {numpy.__version__}")
print(
    "freeze scientific stack: "
    f"python={sys.executable} "
    f"numpy={numpy.__version__} scipy={scipy.__version__} "
    f"matplotlib={matplotlib.__version__} jinja2={jinja2.__version__} "
    f"pyarrow={pyarrow.__version__} rerun={rerun.__version__}"
)
PY

freeze_py -m py_compile \
  evaluators/freeze_compat.py \
  evaluators/freeze_experiment.py \
  evaluators/freeze_map_compat.py \
  evaluators/freeze_rerun.py \
  evaluators/freeze_workflow.py \
  evaluators/pointcloud_frame_index.py \
  evaluators/rerun_diagnostic_viewer.py \
  evaluators/viewer_i18n.py \
  evaluators/report_data.py \
  evaluators/report_evidence.py \
  evaluators/report_html.py \
  evaluators/report_pdf.py \
  benchmark_base/lio_benchmark/entry.py \
  benchmark_base/lio_benchmark/frozen_bundle.py

# The contract itself and legacy benchmark boundary tests must remain valid with
# the ROS/system NumPy/SciPy stack and with ~/.local hidden.
system_py -m pytest -q \
  tests/test_freeze_environment_contract.py \
  tests/test_viewer_projection.py \
  tests/test_entry.py \
  tests/test_postprocess.py \
  tests/test_current_run_report.py \
  tests/test_diagnostic_timeline.py

# Freeze/report/Rerun tests intentionally run in the dedicated NumPy-2 venv.
freeze_py -m pytest -q \
  tests/test_freeze_compat.py \
  tests/test_freeze_experiment.py \
  tests/test_freeze_failure_audit.py \
  tests/test_freeze_provenance.py \
  tests/test_freeze_rerun.py \
  tests/test_native_visual_acceptance.py \
  tests/test_pointcloud_frame_index.py \
  tests/test_viewer_i18n.py \
  tests/test_report_data.py \
  tests/test_report_evidence.py \
  tests/test_report_pointcloud_evidence.py \
  tests/test_report_html.py \
  tests/test_report_pdf.py \
  tests/test_frozen_bundle.py \
  tests/test_entry_frozen_commands.py \
  tests/test_freeze_workflow.py \
  tests/test_rerun_diagnostic_viewer.py

git diff --check

echo "freeze/native-delivery static regression gate passed"

if [[ -z "$run_dir" ]]; then
  cat <<'EOF'
No --run supplied: real completed-run acceptance was not executed.
Provide --run to verify an actual COMPLETE freeze, immutable source artifacts, frozen-only export, and optionally Native open.
EOF
  exit 0
fi

run_dir=$(system_py -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$run_dir")
if [[ ! -d "$run_dir" || ! -f "$run_dir/manifest.json" ]]; then
  echo "invalid benchmark run: $run_dir" >&2
  exit 2
fi

before_hashes=$(mktemp)
after_hashes=$(mktemp)
cleanup() { rm -f "$before_hashes" "$after_hashes"; }
trap cleanup EXIT

system_py - "$run_dir" >"$before_hashes" <<'PY'
import hashlib, json, sys
from pathlib import Path
run = Path(sys.argv[1])
paths = [
    run / "manifest.json",
    run / "metadata/run_status.json",
    run / "metrics/full_comparison.json",
    run / "metrics/trajectory_discontinuity.json",
    run / "metrics/diagnostic_timeline.json",
    run / "metrics/pointcloud_frame_index.json",
    run / "metrics/pointcloud_frame_index.csv",
]
for trajectory in sorted((run / "standardized/trajectories").glob("*.csv")):
    paths.append(trajectory)
for map_path in sorted((run / "figures/fast_livo2_baseline_maps").glob("*_map.ply")):
    paths.append(map_path)
result = {}
for path in paths:
    if path.is_file():
        result[str(path.relative_to(run))] = hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(result, sort_keys=True))
PY

freeze_output=$(env \
  PYTHONNOUSERSITE=1 \
  PATH="$freeze_bin_dir:$PATH" \
  benchmark_base/bin/lio-benchmark freeze \
    --run "$run_dir" \
    --baseline "$baseline" \
    --lang "$language")
printf '%s\n' "$freeze_output"

frozen=$(printf '%s\n' "$freeze_output" | env PYTHONNOUSERSITE=1 "$system_python" -c '
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

system_py - "$run_dir" >"$after_hashes" <<'PY'
import hashlib, json, sys
from pathlib import Path
run = Path(sys.argv[1])
paths = [
    run / "manifest.json",
    run / "metadata/run_status.json",
    run / "metrics/full_comparison.json",
    run / "metrics/trajectory_discontinuity.json",
    run / "metrics/diagnostic_timeline.json",
    run / "metrics/pointcloud_frame_index.json",
    run / "metrics/pointcloud_frame_index.csv",
]
for trajectory in sorted((run / "standardized/trajectories").glob("*.csv")):
    paths.append(trajectory)
for map_path in sorted((run / "figures/fast_livo2_baseline_maps").glob("*_map.ply")):
    paths.append(map_path)
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

freeze_py - "$frozen" <<'PY'
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

env \
  PYTHONNOUSERSITE=1 \
  PATH="$freeze_bin_dir:$PATH" \
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
  env \
    PYTHONNOUSERSITE=1 \
    PATH="$freeze_bin_dir:$PATH" \
    benchmark_base/bin/lio-benchmark open "$frozen"
fi

cat <<EOF
real completed-run freeze acceptance passed:
  source run:    $run_dir
  frozen:        $frozen
  export:        $export_output
  freeze Python: $freeze_python
  native open executed: $open_after
EOF
