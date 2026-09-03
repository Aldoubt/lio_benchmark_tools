from pathlib import Path

import lio_benchmark.entry as entry
from lio_benchmark.postprocess import build_stage_commands


def names(commands):
    return [Path(command[1]).name for command in commands]


def test_phase_analysis_plan_is_analysis_then_plot(tmp_path):
    commands = build_stage_commands(
        tmp_path,
        "phase-analysis",
        baseline="fast_livo2",
        phase_params=["stationary_speed_mps=0.08", "min_phase_duration_s=2.0"],
    )
    assert names(commands) == ["phase_analysis.py", "plot_phase_analysis.py"]
    assert commands[0][-6:] == [
        "--baseline", "fast_livo2",
        "--phase-param", "stationary_speed_mps=0.08",
        "--phase-param", "min_phase_duration_s=2.0",
    ]


def test_phase_analysis_no_plot(tmp_path):
    commands = build_stage_commands(tmp_path, "phase-analysis", no_plot=True)
    assert names(commands) == ["phase_analysis.py"]


def test_phase_analysis_entry_forwards_args(monkeypatch, tmp_path):
    captured = {}

    def fake_execute(run, stage, **kwargs):
        captured.update({"run": run, "stage": stage, **kwargs})
        return 0

    monkeypatch.setattr(entry, "execute_stage", fake_execute)
    result = entry.main([
        "phase-analysis", "--run", str(tmp_path), "--baseline", "fast_livo2",
        "--phase-param", "turn_yaw_rate_deg_s=10", "--no-plot", "--dry-run",
    ])
    assert result == 0
    assert captured["stage"] == "phase-analysis"
    assert captured["baseline"] == "fast_livo2"
    assert captured["phase_params"] == ["turn_yaw_rate_deg_s=10"]
    assert captured["no_plot"] is True
    assert captured["dry_run"] is True
