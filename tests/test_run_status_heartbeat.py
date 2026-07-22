import json
import threading

from lio_benchmark.run_status import heartbeat_run_status, initialize_run_status


def test_heartbeat_is_atomic_and_contains_live_fields(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    manifest = {"run_id": "run", "algorithms": {"demo": {"enabled": True}}}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    initialize_run_status(run, manifest)

    def beat(index):
        heartbeat_run_status(run, "demo", "running", phase="playback", current_process={"pid": index, "cpu_percent": 3.0, "rss_bytes": 12, "threads": 2}, event=f"event-{index}")

    threads = [threading.Thread(target=beat, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    status = json.loads((run / "metadata/run_status.json").read_text())
    assert status["heartbeat"]["at"]
    assert status["current_process"]["pid"] in range(4)
    assert status["elapsed_s"] >= 0
    assert "最近事件" in (run / "RUN_STATUS.md").read_text()
