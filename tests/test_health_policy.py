from pathlib import Path

from health_policy import expected_trajectory_duration_s, trajectory_short


ROOT = Path(__file__).resolve().parents[1]


def test_smoke_uses_requested_duration_with_startup_margin():
    run_result = {"smoke_duration_s": 60.0}
    assert expected_trajectory_duration_s(run_result, manifest_duration_s=622.994) == 60.0
    assert trajectory_short(56.5, run_result, manifest_duration_s=622.994) is False
    assert trajectory_short(52.0, run_result, manifest_duration_s=622.994) is True


def test_manual_limited_run_uses_duration_with_startup_margin():
    run_result = {"smoke_duration_s": None, "duration_s": 60.0}
    assert expected_trajectory_duration_s(run_result, manifest_duration_s=622.994) == 60.0
    assert trajectory_short(56.5, run_result, manifest_duration_s=622.994) is False


def test_full_bag_keeps_strict_coverage_ratio():
    run_result = {"smoke_duration_s": None, "duration_s": None}
    assert expected_trajectory_duration_s(run_result, manifest_duration_s=622.994) == 622.994
    assert trajectory_short(620.0, run_result, manifest_duration_s=622.994) is False
    assert trajectory_short(600.0, run_result, manifest_duration_s=622.994) is True


def test_smoke_summarizer_delegates_to_shared_policy():
    source = (ROOT / "evaluators/summarize_smoke_run.py").read_text(encoding="utf-8")
    assert "from health_policy import trajectory_short" in source
    assert 'trajectory_short(metrics.get("duration_s"), result, expected_duration_s)' in source
    assert 'metrics["duration_s"] < expected_duration_s * 0.98' not in source
