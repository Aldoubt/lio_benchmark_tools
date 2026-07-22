import json

from generate_experiment_report import build_report, render_markdown
from generate_comprehensive_report import build_report as build_comprehensive_report


def test_preliminary_report_classifies_runtime_crash_and_success(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    (run / "raw" / "good" / "trajectory").mkdir(parents=True)
    (run / "raw" / "bad").mkdir(parents=True)
    manifest = {"run_id": "run", "dataset": {"bag_dir": "/tmp/bag"}, "algorithms": {"good": {"enabled": True}, "bad": {"enabled": True}}}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    status = {"run_id": "run", "state": "failed", "algorithms": {
        "good": {"state": "completed", "result": {"status": "SUCCESS", "bag_playback": "completed", "trajectory_messages": 2}},
        "bad": {"state": "failed", "result": {"status": "RUNTIME_CRASH", "trajectory_messages": 1}},
    }}
    (run / "metadata" / "run_status.json").write_text(json.dumps(status), encoding="utf-8")
    (run / "raw" / "good" / "trajectory" / "metadata.yaml").write_text("rosbag2_bagfile_information:\n  message_count: 2\n", encoding="utf-8")
    (run / "raw" / "good" / "input_validation.json").write_text("{}", encoding="utf-8")
    (run / "raw" / "good" / "resource_monitor.json").write_text(json.dumps({"status": "finished", "samples": 2, "wall_time_s": 1}), encoding="utf-8")
    (run / "raw" / "bad" / "stderr.log").write_text("terminate called after throwing an instance of NotEnoughMemoryException\n", encoding="utf-8")
    report = build_report(run)
    categories = {item["algorithm"]: item["category"] for item in report["algorithms"]}
    assert categories == {"good": "SUCCESS", "bad": "RUNTIME_CRASH"}
    assert report["summary"]["critical_or_high_anomalies"] == 1
    assert "Algorithm Review" in render_markdown(report)


def test_comprehensive_report_uses_fast_baseline_and_excludes_divergent_results(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    (run / "metrics").mkdir()
    (run / "figures" / "fast_livo2_baseline_maps").mkdir(parents=True)
    manifest = {
        "run_id": "run",
        "playback_rate": 1.0,
        "dataset": {"duration_s": 10.0, "ground_truth": None, "imu_acceleration_unit": "g"},
        "evaluation": {"map_voxel_m": 0.12},
        "algorithms": {
            "fast_livo2": {"group": "lidar_imu_odometry", "mode": "odometry", "sensor_inputs": ["lidar", "imu"]},
            "point_lio": {"group": "lidar_imu_odometry", "mode": "odometry", "sensor_inputs": ["lidar", "imu"]},
        },
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "metadata" / "run_status.json").write_text(json.dumps({"run_id": "run", "state": "completed"}), encoding="utf-8")
    comparison = {
        "algorithms": [
            {"algorithm": "fast_livo2", "status": "SUCCESS", "trajectory": {"z_range_m": 1.0}, "resource_monitor": {"mean_cpu_percent": 100.0, "peak_cpu_percent": 120.0, "peak_rss_mib": 500.0}},
            {"algorithm": "point_lio", "status": "SUCCESS", "health_flags": ["path_divergence"], "trajectory": {"z_range_m": 100.0}, "resource_monitor": {"mean_cpu_percent": 20.0, "peak_cpu_percent": 30.0, "peak_rss_mib": 100.0}},
        ]
    }
    (run / "metrics" / "full_comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
    (run / "figures" / "fast_livo2_baseline_maps" / "visualization_metadata.json").write_text(json.dumps({"baseline": "fast_livo2", "trajectory_comparison": {"fast_livo2": {"rmse_m": 0.0}}}), encoding="utf-8")
    hardware = {"cpu_model": "test", "physical_cores": 2, "logical_cpus": 2, "nominal_ghz": 2.0, "max_ghz": 2.0, "gpus": [], "fp32_ops_per_cycle_assumption": 32, "tops_proxy_method": "test"}
    report = build_comprehensive_report(run, hardware=hardware)
    rows = {row["algorithm"]: row for row in report["algorithms"]}
    assert report["baseline"] == "fast_livo2"
    assert report["playback_rate"] == 1.0
    assert rows["fast_livo2"]["cpu_equivalent"]["mean_tops_at_nominal"] == 0.064
    assert rows["point_lio"]["recommendation_eligible"] is False
    assert report["tops"]["host_peak_nominal_tops"] == 0.128
