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
  evaluators/diagnostic_timeline.py \
  evaluators/pointcloud_frame_index.py \
  evaluators/viewer_i18n.py \
  evaluators/viewer_projection.py \
  evaluators/rerun_diagnostic_viewer.py \
  evaluators/web_diagnostic_viewer.py \
  benchmark_base/lio_benchmark/web_viewer_server.py \
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
  tests/test_trajectory_discontinuity.py \
  tests/test_diagnostic_timeline.py \
  tests/test_pointcloud_frame_index.py \
  tests/test_viewer_i18n.py \
  tests/test_viewer_projection.py \
  tests/test_rerun_diagnostic_viewer.py \
  tests/test_web_viewer_server.py

cat <<'EOF'

phase/comparison pipeline static/self tests passed.

Core comparison semantics:
  - comprehensive report values come only from the selected run
  - baseline-relative trajectory/map quantities are diagnostic/non-ground-truth
  - map health remains separate from trajectory lifecycle/health
  - raw per-output-step trajectory discontinuities are retained for audit
  - unified diagnostic timelines resample every trajectory on the same bag-anchored 10 Hz grid by default
  - anomaly events are clustered into review windows instead of flooding a viewer with isolated markers
  - resource sample history is mapped through clock anchors + recorded/header evidence onto the same bag-relative timeline
  - pointcloud frame indexing stores only rosbag message ids/timestamps; raw point-cloud bytes remain in the source bag
  - raw/world LiDAR viewer projection reuses per-point time, manifest extrinsic, 3D pose interpolation and baseline alignment
  - native/web viewers consume frozen artifacts and do not change benchmark metric definitions

Useful offline commands:
  benchmark_base/bin/lio-benchmark phase-analysis --run <RUN_DIR> --baseline fast_livo2
  benchmark_base/bin/lio-benchmark diagnostics --run <RUN_DIR> --baseline fast_livo2 --hz 10
  benchmark_base/bin/lio-benchmark viewer --run <RUN_DIR> --mode native --baseline fast_livo2
  benchmark_base/bin/lio-benchmark viewer --run <RUN_DIR> --mode web --baseline fast_livo2

Pointcloud indexing/viewing additionally requires the ROS overlay that provides the bag's exact LiDAR message type:
  benchmark_base/bin/lio-benchmark diagnostics --run <RUN_DIR> --baseline fast_livo2 --hz 10 --with-pointcloud-index

Rerun viewer dependency used by this branch:
  python3 -m pip install 'rerun-sdk==0.36.3'

Web viewer gate (run separately after npm dependencies are installed):
  cd benchmark_base/web_viewer && npm test && npm run build

Smoke coverage policy:
  - short smoke runs are compared with smoke_duration_s and allow a 5 s startup margin
  - full-bag runs still require at least 98% trajectory coverage

LIO-SAM 6-axis compatibility:
  - patches/lio_sam/allow_6axis_imu.patch must be applied to the locked LIO-SAM source before rebuilding
  - allow6AxisImu=true is explicit in both no-loop and loop benchmark params
EOF
