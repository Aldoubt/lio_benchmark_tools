import csv
import json
from pathlib import Path

from current_run_report import build_report, render_markdown


def write_traj(path: Path, xs, zs=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    zs = zs or [0.0] * len(xs)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["timestamp_s", "x_m", "y_m", "z_m", "yaw_rad"],
        )
        writer.writeheader()
        for index, (x_value, z_value) in enumerate(zip(xs, zs)):
            writer.writerow(
                {
                    "timestamp_s": float(index),
                    "x_m": x_value,
                    "y_m": 0.0,
                    "z_m": z_value,
                    "yaw_rad": 0.0,
                }
            )


def test_current_run_data_drives_report_and_healthy_point_lio_is_not_excluded(tmp_path):
    run = tmp_path / "greenhouse_full623_round1_001"
    (run / "metrics").mkdir(parents=True)
    (run / "metadata").mkdir()
    (run / "standardized" / "trajectories").mkdir(parents=True)
    manifest = {
        "playback_rate": 1.0,
        "dataset": {"duration_s": 622.994416876, "ground_truth": None},
        "algorithms": {
            "fast_livo2": {"group": "lidar_imu_odometry"},
            "point_lio": {"group": "lidar_imu_odometry"},
            "dlio": {"group": "lidar_imu_odometry"},
        },
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "metadata" / "run_status.json").write_text(
        json.dumps({"run_id": run.name, "state": "failed"}), encoding="utf-8"
    )
    comparison = {
        "algorithms": [
            {
                "algorithm": "fast_livo2",
                "status": "SUCCESS",
                "health_flags": [],
                "trajectory": {
                    "duration_s": 622.56,
                    "path_length_m": 534.42,
                    "z_range_m": 0.991,
                },
                "resource_monitor": {
                    "mean_cpu_percent": 133.1,
                    "peak_rss_mib": 740.0,
                },
            },
            {
                "algorithm": "point_lio",
                "status": "SUCCESS",
                "health_flags": [],
                "trajectory": {
                    "duration_s": 622.50,
                    "path_length_m": 533.19,
                    "z_range_m": 0.925,
                },
                "resource_monitor": {
                    "mean_cpu_percent": 40.8,
                    "peak_rss_mib": 192.3,
                },
            },
            {
                "algorithm": "dlio",
                "status": "RUNTIME_CRASH",
                "health_flags": ["trajectory_short"],
                "trajectory": {
                    "duration_s": 93.69,
                    "path_length_m": 854.56,
                    "z_range_m": 17.305,
                },
                "resource_monitor": {
                    "mean_cpu_percent": 153.1,
                    "peak_rss_mib": 2042.6,
                },
            },
        ]
    }
    (run / "metrics" / "full_comparison.json").write_text(
        json.dumps(comparison), encoding="utf-8"
    )
    write_traj(run / "standardized/trajectories/fast_livo2.csv", [0, 1, 2, 3])
    write_traj(run / "standardized/trajectories/point_lio.csv", [0, 1.05, 2.10, 3.15])
    write_traj(run / "standardized/trajectories/dlio.csv", [0, 2, 4, 6])

    report = build_report(run)
    rows = {row["algorithm"]: row for row in report["algorithms"]}
    assert rows["point_lio"]["health_pass"] is True
    assert rows["point_lio"]["recommendation_eligible"] is True
    assert rows["point_lio"]["relative_to_baseline"]["rmse_m"] is not None
    assert rows["point_lio"]["map"]["available"] is False
    assert rows["dlio"]["recommendation_eligible"] is False
    assert report["recommendations"]["lowest_mean_cpu"] == "point_lio"

    markdown = render_markdown(report)
    assert "622.99" in markdown
    assert "0.925" in markdown
    assert "N/A" in markdown
    for stale in ("805.5", "807 s", "63.6 km", "4.14 GiB"):
        assert stale not in markdown
