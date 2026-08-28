#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

python3 -m py_compile \
  evaluators/phase_analysis.py \
  evaluators/plot_phase_analysis.py \
  evaluators/clock_anchor_recorder.py \
  evaluators/manual_run_controller.py \
  evaluators/manual_run_controller_base.py \
  benchmark_base/lio_benchmark/entry.py \
  benchmark_base/lio_benchmark/postprocess.py

bash -n evaluators/run_algorithm.sh

python3 -m pytest -q \
  tests/test_phase_analysis.py \
  tests/test_phase_cli.py \
  tests/test_phase_plot.py \
  tests/test_clock_anchor_recorder.py \
  tests/test_clock_anchor_runner_contract.py \
  tests/test_manual_clock_anchor_facade.py \
  tests/test_manual_run_controller.py \
  tests/test_entry.py \
  tests/test_postprocess.py

cat <<'EOF'

phase pipeline static/self tests passed.

Next, inspect an existing run without changing it:
  benchmark_base/bin/lio-benchmark phase-analysis --run <RUN_DIR> --baseline fast_livo2 --dry-run

Then execute the offline analysis:
  benchmark_base/bin/lio-benchmark phase-analysis --run <RUN_DIR> --baseline fast_livo2

For a new strict-clock smoke run, run one algorithm for 20-30 s first, then verify:
  raw/<algorithm>/clock_anchors.json
contains status=finished, samples>2, and no unexpected time backtracks.
EOF
