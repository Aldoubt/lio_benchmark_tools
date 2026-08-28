#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

export MPLBACKEND="${MPLBACKEND:-Agg}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/lio-benchmark-matplotlib}"
mkdir -p "$MPLCONFIGDIR"

python3 -m py_compile \
  evaluators/phase_analysis.py \
  evaluators/plot_phase_analysis.py \
  evaluators/clock_anchor_recorder.py \
  evaluators/health_policy.py \
  evaluators/manual_run_controller.py \
  evaluators/manual_run_controller_base.py \
  evaluators/summarize_smoke_run.py \
  evaluators/current_run_report.py \
  evaluators/generate_comprehensive_report.py \
  evaluators/reconstruct_comparison_maps.py \
  evaluators/map_consistency.py \
  evaluators/enhance_map_comparison.py \
  evaluators/trajectory_discontinuity.py \
  benchmark_base/lio_benchmark/entry.py \
  benchmark_base/lio_benchmark/postprocess.py

bash -n evaluators/run_algorithm.sh

python3 -m pytest -q \
  tests/test_phase_analysis.py \
  tests/test_phase_cli.py \
  tests/test_phase_plot.py \
  tests/test_clock_anchor_recorder.py \
  tests/test_clock_anchor_runner_contract.py \
  tests/test_health_policy.py \
  tests/test_lio_sam_6axis_patch_contract.py \
  tests/test_algorithm_configs.py \
  tests/test_manual_clock_anchor_facade.py \
  tests/test_manual_run_controller.py \
  tests/test_entry.py \
  tests/test_postprocess.py \
  tests/test_current_run_report.py \
  tests/test_current_run_diagnostics.py \
  tests/test_legacy_comprehensive_report_wrapper.py \
  tests/test_experiment_report.py \
  tests/test_map_consistency.py \
  tests/test_map_comparison_enhancement.py \
  tests/test_map_reconstruction_selection.py \
  tests/test_trajectory_discontinuity.py

cat <<'EOF'

phase/comparison pipeline static/self tests passed.

Next, inspect an existing run without changing it:
  benchmark_base/bin/lio-benchmark phase-analysis --run <RUN_DIR> --baseline fast_livo2 --dry-run

Then execute the offline analysis:
  benchmark_base/bin/lio-benchmark phase-analysis --run <RUN_DIR> --baseline fast_livo2

Expected visualization behavior:
  - primary trajectory figures contain health-valid algorithms only
  - *_all trajectory figures retain health-fail runs for diagnosis
  - PRE_MOTION_STATIC and POST_MOTION_STATIC remain in the timeline but are excluded from primary trajectory plots
  - trajectory-only runs do not keep stale cpu_by_phase.png or rss_growth_by_phase.png

Current-run comparison/report behavior:
  - comprehensive report values come only from the selected run
  - whole-run baseline-relative RMSE/P95 are recomputed from current standardized CSVs
  - compare/visualize generate timestamped trajectory-discontinuity timelines and per-step CSVs
  - discontinuity time prefers bag LiDAR header start, so relative time maps directly to rosbag regions when bag_analysis exists
  - compare --with-maps computes robust P99-P1 extents, baseline voxel IoU and symmetric nearest-neighbour metrics
  - map health remains separate from trajectory health
  - primary map figures require trajectory+map health; *_all retains every reconstructable map
  - missing current-run map metadata is reported as N/A rather than backfilled
  - the legacy generate_comprehensive_report.py filename/API delegates to current-run-only data

Smoke coverage policy:
  - short smoke runs are compared with smoke_duration_s and allow a 5 s startup margin
  - full-bag runs still require at least 98% trajectory coverage

LIO-SAM 6-axis compatibility:
  - patches/lio_sam/allow_6axis_imu.patch must be applied to the locked LIO-SAM source before rebuilding
  - allow6AxisImu=true is explicit in both no-loop and loop benchmark params

For a new strict-clock smoke run, run one algorithm for 20-30 s first, then verify:
  raw/<algorithm>/clock_anchors.json
contains status=finished, samples>2, and no unexpected time backtracks.
EOF