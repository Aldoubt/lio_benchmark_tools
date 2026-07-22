import json

from generate_experiment_report import build_report, render_markdown


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
