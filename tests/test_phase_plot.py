import json

from plot_phase_analysis import plot_phase_analysis


def test_plot_phase_analysis_writes_all_contract_figures(tmp_path):
    run = tmp_path / "run"
    (run / "metrics").mkdir(parents=True)
    result = {
        "schema_version": 1,
        "baseline": "fast_livo2",
        "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
        "time_alignment_mode": "approximate/lifecycle-aligned",
        "phases": [
            {"id": "phase_000", "state": "INITIALIZATION", "start_s": 0.0, "end_s": 2.0, "duration_s": 2.0, "return_near_start": False},
            {"id": "phase_001", "state": "STRAIGHT", "start_s": 2.0, "end_s": 10.0, "duration_s": 8.0, "return_near_start": False},
        ],
        "algorithms": {
            "fast_livo2": {
                "selection_eligible": True,
                "phases": {
                    "phase_000": {"trajectory": {"relative_position_rmse_m": 0.0, "relative_z_rmse_m": 0.0, "z_change_m": 0.0}, "resource": {"availability": "available", "cpu_p95_percent": 50.0, "rss_growth_mib": 10.0}},
                    "phase_001": {"trajectory": {"relative_position_rmse_m": 0.0, "relative_z_rmse_m": 0.0, "z_change_m": 0.1}, "resource": {"availability": "available", "cpu_p95_percent": 70.0, "rss_growth_mib": 20.0}},
                },
            },
            "candidate": {
                "selection_eligible": True,
                "phases": {
                    "phase_000": {"trajectory": {"relative_position_rmse_m": 0.2, "relative_z_rmse_m": 0.1, "z_change_m": 0.05}, "resource": {"availability": "unavailable", "cpu_p95_percent": None, "rss_growth_mib": None}},
                    "phase_001": {"trajectory": {"relative_position_rmse_m": 0.4, "relative_z_rmse_m": 0.3, "z_change_m": 0.4}, "resource": {"availability": "unavailable", "cpu_p95_percent": None, "rss_growth_mib": None}},
                },
            },
        },
        "warnings": [],
    }
    (run / "metrics" / "phase_analysis.json").write_text(json.dumps(result), encoding="utf-8")
    paths = plot_phase_analysis(run)
    expected = {
        "phase_timeline.png",
        "trajectory_error_by_phase.png",
        "z_change_by_phase.png",
        "cpu_by_phase.png",
        "rss_growth_by_phase.png",
        "phase_dashboard.png",
    }
    assert {path.name for path in paths} == expected
    assert all(path.is_file() and path.stat().st_size > 1000 for path in paths)
