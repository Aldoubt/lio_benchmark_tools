import csv
import json
from pathlib import Path

import numpy as np

from plot_comparison_dashboard import (
    align_candidate_to_baseline,
    build_alignment_summary,
    build_metric_summary,
    choose_stable_algorithms,
    discover_algorithms,
    health_valid,
    load_trajectory,
)


def _write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["timestamp_s", "x_m", "y_m", "z_m", "qx", "qy", "qz", "qw", "roll_rad", "pitch_rad", "yaw_rad", "source_topic"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_initial_yaw_translation_alignment_recovers_same_xy_shape(tmp_path):
    base_rows = []
    candidate_rows = []
    for index in range(5):
        t = float(index)
        x, y = t, 0.5 * t
        base_rows.append({"timestamp_s": t, "x_m": x, "y_m": y, "z_m": 0.0, "qx": 0, "qy": 0, "qz": 0, "qw": 1, "roll_rad": 0, "pitch_rad": 0, "yaw_rad": 0.0, "source_topic": "/base"})
        cx, cy = -y + 10.0, x - 3.0
        candidate_rows.append({"timestamp_s": t, "x_m": cx, "y_m": cy, "z_m": 1.0, "qx": 0, "qy": 0, "qz": 0.70710678, "qw": 0.70710678, "roll_rad": 0, "pitch_rad": 0, "yaw_rad": np.pi / 2, "source_topic": "/candidate"})
    base_path = tmp_path / "base.csv"
    candidate_path = tmp_path / "candidate.csv"
    _write_csv(base_path, base_rows)
    _write_csv(candidate_path, candidate_rows)

    baseline = load_trajectory(base_path)
    candidate = load_trajectory(candidate_path)
    aligned, metadata = align_candidate_to_baseline(baseline, candidate)

    assert metadata["method"] == "initial_yaw_translation"
    assert metadata["samples"] >= 5
    assert np.max(np.abs(aligned[:, :2] - baseline["positions"][:, :2])) < 1e-6


def test_discover_algorithms_prefers_metrics_order_and_filters_missing_csv(tmp_path):
    run = tmp_path / "run"
    (run / "metrics").mkdir(parents=True)
    (run / "standardized" / "trajectories").mkdir(parents=True)
    (run / "metrics" / "full_comparison.json").write_text(json.dumps({"algorithms": [
        {"algorithm": "fast_livo2"},
        {"algorithm": "glim_odometry"},
        {"algorithm": "missing"},
    ]}), encoding="utf-8")
    for name in ("fast_livo2", "glim_odometry"):
        (run / "standardized" / "trajectories" / f"{name}.csv").write_text("timestamp_s,x_m,y_m,z_m,qx,qy,qz,qw,roll_rad,pitch_rad,yaw_rad,source_topic\n", encoding="utf-8")

    assert discover_algorithms(run) == ["fast_livo2", "glim_odometry"]


def test_metric_summary_reads_trajectory_and_resource_monitor_fields():
    comparison = {"algorithms": [{
        "algorithm": "fast_livo2",
        "trajectory": {"path_length_m": 12.5, "z_range_m": 0.42},
        "resource_monitor": {"mean_cpu_percent": 123.0, "peak_rss_mib": 850.0},
        "health_flags": [],
        "status": "SUCCESS",
    }]}
    rows = build_metric_summary(comparison, ["fast_livo2"])
    assert rows == [{
        "algorithm": "fast_livo2",
        "status": "SUCCESS",
        "health_flags": [],
        "path_length_m": 12.5,
        "z_range_m": 0.42,
        "mean_cpu_percent": 123.0,
        "peak_rss_mib": 850.0,
    }]


def test_health_valid_requires_success_without_flags():
    assert health_valid({"status": "SUCCESS", "health_flags": []})
    assert not health_valid({"status": "SUCCESS", "health_flags": ["path_divergence"]})
    assert not health_valid({"status": "RUNTIME_CRASH", "health_flags": []})


def test_choose_stable_algorithms_excludes_health_failures_but_keeps_baseline():
    algorithms = ["fast_livo2", "glim_odometry", "point_lio", "dlio"]
    rows = [
        {"algorithm": "fast_livo2", "status": "SUCCESS", "health_flags": []},
        {"algorithm": "glim_odometry", "status": "SUCCESS", "health_flags": []},
        {"algorithm": "point_lio", "status": "SUCCESS", "health_flags": ["trajectory_short", "path_divergence"]},
        {"algorithm": "dlio", "status": "SUCCESS", "health_flags": ["path_divergence"]},
    ]
    stable, excluded = choose_stable_algorithms(algorithms, rows, "fast_livo2")
    assert stable == ["fast_livo2", "glim_odometry"]
    assert excluded == {
        "point_lio": ["trajectory_short", "path_divergence"],
        "dlio": ["path_divergence"],
    }


def test_alignment_summary_uses_zero_for_baseline_and_relative_values_for_candidate():
    rows = [
        {"algorithm": "fast_livo2", "status": "SUCCESS", "health_flags": []},
        {"algorithm": "glim_odometry", "status": "SUCCESS", "health_flags": []},
    ]
    alignment = {
        "fast_livo2": {"method": "identity"},
        "glim_odometry": {"relative_rmse_m": 0.11, "relative_p95_m": 0.16},
    }
    result = build_alignment_summary(alignment, rows, ["fast_livo2", "glim_odometry"], "fast_livo2")
    assert result[0]["relative_rmse_m"] == 0.0
    assert result[0]["relative_p95_m"] == 0.0
    assert result[1]["relative_rmse_m"] == 0.11
    assert result[1]["relative_p95_m"] == 0.16
