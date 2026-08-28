from pathlib import Path

from lio_benchmark.postprocess import build_stage_commands


def names(commands):
    return [Path(command[1]).name for command in commands]


def test_visualize_uses_existing_metrics_without_restandardizing(tmp_path):
    run = tmp_path / "run"
    (run / "metrics").mkdir(parents=True)
    (run / "metrics" / "full_comparison.json").write_text("{}", encoding="utf-8")
    commands = build_stage_commands(run, "visualize", with_maps=False)
    assert names(commands) == ["plot_comparison_dashboard.py", "plot_resource_curves.py"]


def test_visualize_bootstraps_metrics_when_missing_and_maps_are_opt_in(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    commands = build_stage_commands(run, "visualize", with_maps=True, baseline="fast_livo2")
    assert names(commands) == [
        "summarize_smoke_run.py",
        "plot_comparison_dashboard.py",
        "plot_resource_curves.py",
        "reconstruct_comparison_maps.py",
        "enhance_map_comparison.py",
    ]
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
        "reconstruct_comparison_maps.py",
        "enhance_map_comparison.py",
        "current_run_report.py",
    ]


def test_report_bootstraps_comparison_then_generates_current_run_report(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    commands = build_stage_commands(run, "report")
    assert names(commands) == ["summarize_smoke_run.py", "current_run_report.py"]
