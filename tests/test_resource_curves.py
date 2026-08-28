import json
from pathlib import Path

from plot_resource_curves import _display_label, cpu_distribution, health_flags


def test_health_flags_reads_trajectory_health_and_runtime_status(tmp_path: Path):
    run = tmp_path / "run"
    (run / "metrics").mkdir(parents=True)
    (run / "metrics" / "full_comparison.json").write_text(
        json.dumps(
            {
                "algorithms": [
                    {"algorithm": "fast_livo2", "status": "SUCCESS", "health_flags": []},
                    {"algorithm": "point_lio", "status": "SUCCESS", "health_flags": ["path_divergence"]},
                    {"algorithm": "dlio", "status": "RUNTIME_CRASH", "health_flags": []},
                ]
            }
        ),
        encoding="utf-8",
    )

    flags = health_flags(run)

    assert flags["fast_livo2"] == []
    assert flags["point_lio"] == ["path_divergence"]
    assert flags["dlio"] == ["status:RUNTIME_CRASH"]


def test_display_label_marks_health_fail_rows():
    assert _display_label({"label": "FAST-LIVO2", "health_flags": []}) == "FAST-LIVO2"
    assert _display_label({"label": "Point-LIO", "health_flags": ["path_divergence"]}) == "Point-LIO [health-fail]"


def test_cpu_distribution_reports_median_p95_and_peak():
    samples = [
        {"cpu_percent": 0.0},
        {"cpu_percent": 10.0},
        {"cpu_percent": 20.0},
        {"cpu_percent": 30.0},
        {"cpu_percent": 40.0},
    ]

    result = cpu_distribution(samples)

    assert result["median_cpu_percent"] == 20.0
    assert result["p95_cpu_percent"] == 38.0
    assert result["peak_cpu_percent_from_samples"] == 40.0


def test_cpu_distribution_handles_empty_samples():
    assert cpu_distribution([]) == {
        "median_cpu_percent": 0.0,
        "p95_cpu_percent": 0.0,
        "peak_cpu_percent_from_samples": 0.0,
    }
