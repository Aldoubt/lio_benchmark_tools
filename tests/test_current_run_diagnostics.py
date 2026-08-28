import csv
import json
from pathlib import Path

from current_run_report import build_report, render_markdown


def write_traj(path: Path, xs):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["timestamp_s", "x_m", "y_m", "z_m", "yaw_rad"],
        )
        writer.writeheader()
        for index, x_value in enumerate(xs):
            writer.writerow(
                {
                    "timestamp_s": float(index),
                    "x_m": float(x_value),
                    "y_m": 0.0,
                    "z_m": 0.0,
                    "yaw_rad": 0.0,
                }
            )


def test_report_keeps_map_health_separate_and_exposes_jump_diagnostics(tmp_path):
    run = tmp_path / "run"
    (run / "metrics").mkdir(parents=True)
    (run / "metadata").mkdir()
    map_dir = run / "figures" / "fast_livo2_baseline_maps"
    map_dir.mkdir(parents=True)
    manifest = {
        "dataset": {"duration_s": 10.0, "ground_truth": None},
        "algorithms": {
            "fast_livo2": {"group": "lidar_imu_odometry"},
            "kiss_icp": {"group": "lidar_odometry"},
        },
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "metadata" / "run_status.json").write_text(
        json.dumps({"run_id": "run", "state": "completed"}), encoding="utf-8"
    )
    comparison = {
        "algorithms": [
            {
                "algorithm": "fast_livo2",
                "status": "SUCCESS",
                "health_flags": [],
                "trajectory": {"duration_s": 9.0, "path_length_m": 9.0, "z_range_m": 0.2},
                "resource_monitor": {"mean_cpu_percent": 100.0, "peak_rss_mib": 500.0},
            },
            {
                "algorithm": "kiss_icp",
                "status": "SUCCESS",
                "health_flags": [],
                "trajectory": {"duration_s": 9.0, "path_length_m": 11.0, "z_range_m": 0.3},
                "resource_monitor": {"mean_cpu_percent": 50.0, "peak_rss_mib": 100.0},
            },
        ]
    }
    (run / "metrics" / "full_comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
    write_traj(run / "standardized/trajectories/fast_livo2.csv", [0, 1, 2, 3])
    write_traj(run / "standardized/trajectories/kiss_icp.csv", [0, 1, 2, 3])
    map_metrics = {
        "algorithms": {
            "fast_livo2": {
                "available": True,
                "map_health_pass": True,
                "map_health_flags": [],
                "robust_extent_xyz_m": [10.0, 20.0, 5.0],
                "baseline_voxel_iou": 1.0,
                "symmetric_nn_p95_m": 0.0,
            },
            "kiss_icp": {
                "available": True,
                "map_health_pass": False,
                "map_health_flags": ["excessive_robust_z_span"],
                "robust_extent_xyz_m": [10.0, 20.0, 20.0],
                "baseline_voxel_iou": 0.4,
                "symmetric_nn_p95_m": 1.0,
            },
        }
    }
    (map_dir / "map_comparison_metrics.json").write_text(json.dumps(map_metrics), encoding="utf-8")
    discontinuity = {
        "algorithms": {
            "fast_livo2": {"event_count": 0, "position_jump_count": 0, "yaw_jump_count": 0, "max_position_step_m": 0.2, "max_yaw_step_deg": 1.0},
            "kiss_icp": {"event_count": 2, "position_jump_count": 1, "yaw_jump_count": 1, "max_position_step_m": 2.0, "max_yaw_step_deg": 30.0},
        }
    }
    (run / "metrics" / "trajectory_discontinuity.json").write_text(json.dumps(discontinuity), encoding="utf-8")

    report = build_report(run)
    rows = {item["algorithm"]: item for item in report["algorithms"]}
    assert rows["kiss_icp"]["trajectory_health_pass"] is True
    assert rows["kiss_icp"]["map_health_pass"] is False
    assert rows["kiss_icp"]["recommendation_eligible"] is False
    assert rows["kiss_icp"]["trajectory_diagnostics"]["event_count"] == 2
    assert report["recommendations"]["map_consistent_algorithms"] == ["fast_livo2"]
    assert report["recommendations"]["not_recommended_this_run"] == ["kiss_icp"]

    markdown = render_markdown(report)
    assert "excessive_robust_z_span" in markdown
    assert "2" in markdown
    assert "30.000" in markdown
