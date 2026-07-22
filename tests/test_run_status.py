import json

from lio_benchmark.run_status import initialize_run_status, update_run_status


def test_status_tracks_successful_algorithm(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    manifest = {
        "run_id": "run",
        "created_at": "2026-07-21T00:00:00+08:00",
        "algorithms": {"kiss_icp": {"enabled": True}},
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    initialize_run_status(run, manifest)
    update_run_status(run, "kiss_icp", "running", "running")
    result = run / "result.json"
    result.write_text(json.dumps({"status": "SUCCESS", "trajectory_messages": 597}), encoding="utf-8")
    update_run_status(run, "kiss_icp", "completed", "completed", str(result))

    status = json.loads((run / "metadata" / "run_status.json").read_text())
    assert status["state"] == "completed"
    assert status["algorithms"]["kiss_icp"]["result"]["trajectory_messages"] == 597
    assert "状态：completed" in (run / "RUN_STATUS.md").read_text()


def test_status_marks_non_success_as_failed(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    manifest = {"run_id": "run", "algorithms": {"kiss_icp": {"enabled": True}}}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    initialize_run_status(run, manifest)
    result = run / "result.json"
    result.write_text(json.dumps({"status": "NO_ODOMETRY", "trajectory_messages": 0}), encoding="utf-8")
    update_run_status(run, "kiss_icp", "failed", "failed", str(result), "NO_ODOMETRY")
    status = json.loads((run / "metadata" / "run_status.json").read_text())
    assert status["state"] == "failed"
    assert status["bag_playback"] == "failed"


def test_status_marks_selected_subset_as_completed_partial(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    manifest = {
        "run_id": "run",
        "algorithms": {
            "kiss_icp": {"enabled": True},
            "dlio": {"enabled": True},
        },
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    initialize_run_status(run, manifest)
    result = run / "result.json"
    result.write_text(json.dumps({"status": "SUCCESS", "trajectory_messages": 1}), encoding="utf-8")
    update_run_status(run, "kiss_icp", "completed", "completed", str(result))
    status = json.loads((run / "metadata" / "run_status.json").read_text())
    assert status["state"] == "completed_partial"


def test_status_keeps_failure_when_later_algorithm_succeeds(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    manifest = {
        "run_id": "run",
        "algorithms": {
            "kiss_icp": {"enabled": True},
            "dlio": {"enabled": True},
        },
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    initialize_run_status(run, manifest)
    failed = run / "failed.json"
    failed.write_text(json.dumps({"status": "NO_ODOMETRY"}), encoding="utf-8")
    succeeded = run / "succeeded.json"
    succeeded.write_text(json.dumps({"status": "SUCCESS"}), encoding="utf-8")
    update_run_status(run, "kiss_icp", "failed", "failed", str(failed))
    update_run_status(run, "dlio", "completed", "completed", str(succeeded))
    status = json.loads((run / "metadata" / "run_status.json").read_text())
    assert status["state"] == "failed"
