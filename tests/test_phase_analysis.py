import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest

from phase_analysis import (
    DEFAULT_PHASE_PARAMETERS,
    align_resource_samples,
    aggregate_resource_phase,
    build_phases,
    compute_phase_trajectory_metrics,
    piecewise_wall_to_recorded,
    recorded_to_header_offset,
    run_phase_analysis,
)


def iso(seconds: float) -> str:
    base = dt.datetime(2026, 8, 28, tzinfo=dt.timezone.utc)
    return (base + dt.timedelta(seconds=seconds)).isoformat()


def test_piecewise_clock_anchor_interpolation():
    anchors = [
        {"wall_time_ns": 100_000_000_000, "ros_time_s": 1000.0},
        {"wall_time_ns": 110_000_000_000, "ros_time_s": 1012.0},
    ]
    assert piecewise_wall_to_recorded(105.0, anchors) == pytest.approx(1006.0)
    assert piecewise_wall_to_recorded(99.0, anchors) is None
    assert piecewise_wall_to_recorded(111.0, anchors) is None


def test_recorded_to_header_offset_uses_lidar_median():
    bag = {
        "topics": {
            "/livox/lidar": {
                "recorded_first_s": 2000.0,
                "record_minus_header_s": {
                    "count": 100,
                    "mean": 0.21,
                    "median": 0.20,
                    "std": 0.01,
                    "min": 0.18,
                    "max": 0.23,
                },
            }
        }
    }
    offset, evidence, warnings = recorded_to_header_offset(bag, "/livox/lidar")
    assert offset == pytest.approx(0.20)
    assert evidence["source"] == "bag_analysis:/livox/lidar:record_minus_header_s"
    assert evidence["median_s"] == pytest.approx(0.20)
    assert warnings == []


def test_strict_resource_alignment_applies_recorded_to_header_offset():
    resource = {"sample_history": [{"at": iso(5), "cpu_percent": 20.0, "rss_bytes": 100, "threads": 2}]}
    anchors = [
        {"wall_time_ns": int((dt.datetime.fromisoformat(iso(0)).timestamp()) * 1e9), "ros_time_s": 2000.0},
        {"wall_time_ns": int((dt.datetime.fromisoformat(iso(10)).timestamp()) * 1e9), "ros_time_s": 2010.0},
    ]
    bag = {"topics": {"/livox/lidar": {"recorded_first_s": 2000.0, "record_minus_header_s": {"count": 10, "median": 0.2, "std": 0.0, "min": 0.2, "max": 0.2}}}}
    mode, aligned, evidence, warnings = align_resource_samples(
        resource, "fast_livo2", {}, bag, "/livox/lidar", anchors, playback_rate=1.0
    )
    assert mode == "strict/clock-anchored"
    assert aligned[0]["trajectory_time_s"] == pytest.approx(2004.8)
    assert evidence["clock_anchor_count"] == 2
    assert warnings == []


def test_lifecycle_alignment_or_downgrade():
    resource = {"sample_history": [{"at": iso(15), "cpu_percent": 20.0, "rss_bytes": 100, "threads": 2}]}
    status = {"events": [{"at": iso(10), "algorithm": "fast_livo2", "bag_playback": "running"}]}
    bag = {"topics": {"/livox/lidar": {"recorded_first_s": 3000.0, "record_minus_header_s": {"count": 4, "median": 0.1, "std": 0.0, "min": 0.1, "max": 0.1}}}}
    mode, aligned, evidence, warnings = align_resource_samples(resource, "fast_livo2", status, bag, "/livox/lidar", None, playback_rate=1.0)
    assert mode == "approximate/lifecycle-aligned"
    assert aligned[0]["trajectory_time_s"] == pytest.approx(3004.9)
    assert evidence["playback_wall_at"] == iso(10)
    assert any("approximate" in item for item in warnings)

    mode2, aligned2, _, warnings2 = align_resource_samples(resource, "fast_livo2", {"events": []}, bag, "/livox/lidar", None, playback_rate=1.0)
    assert mode2 == "trajectory-only"
    assert aligned2 == []
    assert warnings2


def _row(t, x, y=0.0, z=0.0, yaw=0.0, roll=0.0, pitch=0.0):
    return {"timestamp_s": float(t), "x_m": float(x), "y_m": float(y), "z_m": float(z), "yaw_rad": float(yaw), "roll_rad": float(roll), "pitch_rad": float(pitch)}


def test_phase_builder_respects_priority_and_merges_short_fragments():
    params = dict(DEFAULT_PHASE_PARAMETERS)
    params.update({
        "resample_hz": 2.0,
        "stationary_speed_mps": 0.05,
        "turn_yaw_rate_deg_s": 20.0,
        "high_curvature_1pm": 0.5,
        "min_phase_duration_s": 1.0,
        "sustained_motion_s": 1.0,
        "near_start_radius_m": 0.4,
    })
    rows = [
        _row(0, 0.00), _row(0.5, 0.00),
        _row(1.0, 0.10), _row(1.5, 0.20), _row(2.0, 0.30),
        _row(2.5, 0.35, 0.05, yaw=0.4), _row(3.0, 0.35, 0.15, yaw=0.8), _row(3.5, 0.35, 0.25, yaw=1.2),
        _row(4.0, 0.45, 0.25, yaw=1.2), _row(4.5, 0.55, 0.25, yaw=1.2),
    ]
    samples, phases = build_phases(rows, params)
    states = [phase["state"] for phase in phases]
    assert states[0] == "PRE_MOTION_STATIC"
    assert "TURN" in states
    assert states[-1] == "STRAIGHT"
    turn_samples = [s for s in samples if s["state"] == "TURN"]
    assert turn_samples
    assert any(s["curvature_1pm"] > params["high_curvature_1pm"] for s in turn_samples)


def test_phase_builder_labels_terminal_static_edges():
    params = dict(DEFAULT_PHASE_PARAMETERS)
    params.update({
        "resample_hz": 2.0,
        "stationary_speed_mps": 0.05,
        "min_phase_duration_s": 0.5,
        "sustained_motion_s": 1.0,
    })
    rows = [
        _row(0.0, 0.0), _row(0.5, 0.0),
        _row(1.0, 0.2), _row(1.5, 0.4), _row(2.0, 0.6),
        _row(2.5, 0.6), _row(3.0, 0.6),
    ]
    _, phases = build_phases(rows, params)
    states = [phase["state"] for phase in phases]
    assert states[0] == "PRE_MOTION_STATIC"
    assert states[-1] == "POST_MOTION_STATIC"
    assert "STRAIGHT" in states


def test_phase_metrics_and_resource_aggregation():
    baseline = [_row(0, 0), _row(1, 1), _row(2, 2), _row(3, 3)]
    candidate = [_row(0, 0, z=0), _row(1, 1, z=0.1), _row(2, 2, z=0.2), _row(3, 3, z=0.3)]
    phase = {"id": "phase_000", "state": "STRAIGHT", "start_s": 0.0, "end_s": 3.0, "duration_s": 3.0}
    metrics = compute_phase_trajectory_metrics(baseline, candidate, phase, resample_hz=2.0)
    assert metrics["samples"] >= 6
    assert metrics["coverage_ratio"] == pytest.approx(1.0)
    assert metrics["relative_z_rmse_m"] > 0
    assert metrics["z_change_m"] == pytest.approx(0.3)

    resource = [
        {"trajectory_time_s": 0.5, "cpu_percent": 10.0, "rss_bytes": 100 * 1024 * 1024, "threads": 2},
        {"trajectory_time_s": 1.5, "cpu_percent": 30.0, "rss_bytes": 120 * 1024 * 1024, "threads": 4},
        {"trajectory_time_s": 2.5, "cpu_percent": 20.0, "rss_bytes": 130 * 1024 * 1024, "threads": 3},
    ]
    r = aggregate_resource_phase(resource, phase)
    assert r["resource_samples"] == 3
    assert r["cpu_median_percent"] == pytest.approx(20.0)
    assert r["rss_growth_mib"] == pytest.approx(30.0)
    assert r["threads_peak"] == 4


def _write_traj(path: Path, rows):
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["timestamp_s", "x_m", "y_m", "z_m", "roll_rad", "pitch_rad", "yaw_rad"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({key: row.get(key, 0.0) for key in fields})


def test_run_phase_analysis_writes_contract_and_keeps_health_failures(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    (run / "metrics").mkdir(parents=True)
    (run / "raw" / "fast_livo2").mkdir(parents=True)
    (run / "raw" / "bad_algo").mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({
        "playback_rate": 1.0,
        "dataset": {"lidar_topic": "/livox/lidar"},
        "algorithms": {"fast_livo2": {"enabled": True}, "bad_algo": {"enabled": True}},
    }), encoding="utf-8")
    (run / "metadata" / "run_status.json").write_text(json.dumps({"events": [], "algorithms": {}}), encoding="utf-8")
    (run / "metrics" / "bag_analysis.json").write_text(json.dumps({"topics": {}}), encoding="utf-8")
    (run / "metrics" / "full_comparison.json").write_text(json.dumps({"algorithms": [
        {"algorithm": "fast_livo2", "status": "SUCCESS", "health_flags": []},
        {"algorithm": "bad_algo", "status": "SUCCESS", "health_flags": ["trajectory_short"]},
    ]}), encoding="utf-8")
    base = [_row(0, 0), _row(1, 0), _row(2, 1), _row(3, 2), _row(4, 3)]
    bad = [_row(0, 0), _row(1, 0), _row(2, 0.8), _row(3, 1.7), _row(4, 2.5)]
    _write_traj(run / "standardized" / "trajectories" / "fast_livo2.csv", base)
    _write_traj(run / "standardized" / "trajectories" / "bad_algo.csv", bad)

    result = run_phase_analysis(run, baseline="fast_livo2")
    assert result["schema_version"] == 1
    assert result["metric_class"] == "relative-to-baseline/diagnostic/non-ground-truth"
    assert result["time_alignment_mode"] == "trajectory-only"
    assert "bad_algo" in result["algorithms"]
    assert result["algorithms"]["bad_algo"]["selection_eligible"] is False
    assert (run / "metrics" / "phase_analysis.json").is_file()
    assert (run / "reports" / "phase_analysis.md").is_file()
