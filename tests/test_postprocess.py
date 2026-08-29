from pathlib import Path

import pytest

from lio_benchmark.postprocess import build_stage_commands


def names(commands):
    return [Path(command[1]).name for command in commands]


def test_visualize_uses_existing_metrics_without_restandardizing(tmp_path):
    run = tmp_path / "run"
    (run / "metrics").mkdir(parents=True)
    (run / "metrics" / "full_comparison.json").write_text("{}", encoding="utf-8")
    commands = build_stage_commands(run, "visualize", with_maps=False)
    assert names(commands) == [
        "plot_comparison_dashboard.py",
        "plot_resource_curves.py",
        "trajectory_discontinuity.py",
        "diagnostic_timeline.py",
    ]


def test_visualize_bootstraps_metrics_when_missing_and_maps_are_opt_in(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    commands = build_stage_commands(run, "visualize", with_maps=True, baseline="fast_livo2")
    assert names(commands) == [
        "summarize_smoke_run.py",
        "plot_comparison_dashboard.py",
        "plot_resource_curves.py",
        "trajectory_discontinuity.py",
        "diagnostic_timeline.py",
        "reconstruct_comparison_maps.py",
        "enhance_map_comparison.py",
    ]
    assert "--baseline" in commands[-4]
    assert "--baseline" in commands[-3]
    assert "--baseline" in commands[-2]
    assert "--baseline" in commands[-1]


def test_compare_is_fresh_end_to_end_postprocess_plan(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    commands = build_stage_commands(run, "compare", with_maps=False)
    assert names(commands) == [
        "summarize_smoke_run.py",
        "plot_comparison_dashboard.py",
        "plot_resource_curves.py",
        "trajectory_discontinuity.py",
        "diagnostic_timeline.py",
        "current_run_report.py",
    ]


def test_compare_with_maps_enhances_maps_before_current_run_report(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    commands = build_stage_commands(run, "compare", with_maps=True, baseline="fast_livo2")
    assert names(commands) == [
        "summarize_smoke_run.py",
        "plot_comparison_dashboard.py",
        "plot_resource_curves.py",
        "trajectory_discontinuity.py",
        "diagnostic_timeline.py",
        "reconstruct_comparison_maps.py",
        "enhance_map_comparison.py",
        "current_run_report.py",
    ]


def test_diagnostics_stage_is_lightweight_and_pointcloud_index_is_opt_in(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    commands = build_stage_commands(
        run,
        "diagnostics",
        baseline="fast_livo2",
        diagnostic_hz=10.0,
        anomaly_window_gap_s=1.0,
        with_pointcloud_index=False,
    )
    assert names(commands) == [
        "trajectory_discontinuity.py",
        "diagnostic_timeline.py",
    ]
    assert "--hz" in commands[-1]
    assert "10.0" in commands[-1]

    indexed = build_stage_commands(
        run,
        "diagnostics",
        baseline="fast_livo2",
        with_pointcloud_index=True,
    )
    assert names(indexed) == [
        "trajectory_discontinuity.py",
        "diagnostic_timeline.py",
        "pointcloud_frame_index.py",
    ]


def test_native_viewer_stage_launches_rerun_consumer(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    save_path = tmp_path / "viewer.rrd"
    commands = build_stage_commands(
        run,
        "viewer",
        baseline="fast_livo2",
        viewer_mode="native",
        viewer_algorithms="fast_livo2,point_lio",
        viewer_language="en",
        viewer_with_maps=False,
        viewer_pointcloud_mode="sampled",
        viewer_pointcloud_period_s=2.0,
        viewer_point_step=25,
        viewer_point_lods="10,20,80",
        viewer_world_pointcloud_mode="sampled",
        viewer_world_algorithm="point_lio",
        viewer_map_point_step=5,
        viewer_save=save_path,
        viewer_spawn=False,
    )
    assert names(commands) == ["rerun_diagnostic_viewer.py"]
    command = commands[0]
    assert "--algorithms" in command and "fast_livo2,point_lio" in command
    assert "--lang" in command and "en" in command
    assert "--no-maps" in command
    assert "--pointcloud-mode" in command and "sampled" in command
    assert "--pointcloud-period" in command and "2.0" in command
    assert "--point-step" in command and "25" in command
    assert "--point-lods" in command and "10,20,80" in command
    assert "--world-pointcloud-mode" in command and "sampled" in command
    assert "--world-algorithm" in command and "point_lio" in command
    assert "--map-point-step" in command and "5" in command
    assert "--save" in command and str(save_path) in command
    assert "--no-spawn" in command
    assert all(isinstance(item, str) for item in command)


def test_web_viewer_stage_launches_web_controller(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    commands = build_stage_commands(
        run,
        "viewer",
        viewer_mode="web",
        viewer_spawn=False,
    )
    assert names(commands) == ["web_diagnostic_viewer.py"]
    assert "--no-browser" in commands[0]
    assert "--save" not in commands[0]


def test_web_viewer_rejects_rrd_save(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    with pytest.raises(ValueError, match="web.*save"):
        build_stage_commands(
            run,
            "viewer",
            viewer_mode="web",
            viewer_save=tmp_path / "viewer.rrd",
        )


def test_report_bootstraps_comparison_then_generates_current_run_report(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    commands = build_stage_commands(run, "report")
    assert names(commands) == ["summarize_smoke_run.py", "current_run_report.py"]
