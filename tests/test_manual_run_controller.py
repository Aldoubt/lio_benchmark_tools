import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path

from manual_run_controller import ManualRunController


def test_controller_uses_retry_directory_for_existing_failed_logs(tmp_path):
    run = tmp_path / "run"
    (run / "raw" / "demo").mkdir(parents=True)
    (run / "metadata").mkdir()
    manifest = {
        "schema_version": 2,
        "run_id": "run",
        "name": "demo",
        "output_root": str(tmp_path),
        "dataset": {"bag_dir": str(tmp_path / "bag"), "setup_scripts": []},
        "algorithms": {"demo": {"enabled": True, "config": "demo.yaml", "setup_scripts": [], "required_executables": ["demo"]}},
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "raw" / "demo" / "stderr.log").write_text("old failure\n", encoding="utf-8")
    (run / "metadata" / "run_status.json").write_text(json.dumps({"algorithms": {"demo": {"state": "failed"}}}), encoding="utf-8")
    (tmp_path / "bag").mkdir()
    (tmp_path / "demo.yaml").write_text("{}\n", encoding="utf-8")
    controller = ManualRunController(run, "demo")
    output = controller._allocate_output_dir()
    assert output.parent == run / "raw" / "demo"
    assert output.name.startswith("attempt_")
    assert (run / "raw" / "demo" / "stderr.log").read_text() == "old failure\n"


def test_controller_allows_full_run_after_smoke_success(tmp_path):
    run = tmp_path / "run"
    (run / "raw" / "demo").mkdir(parents=True)
    (run / "metadata").mkdir()
    manifest = {"run_id": "run", "algorithms": {"demo": {"enabled": True}}}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "metadata" / "run_status.json").write_text(json.dumps({"algorithms": {"demo": {"state": "completed", "result": {"status": "SUCCESS", "duration_s": 5.0}}}}), encoding="utf-8")
    (run / "raw" / "demo" / "run_result.json").write_text("{}", encoding="utf-8")
    controller = ManualRunController(run, "demo")
    output = controller._allocate_output_dir()
    assert output.name.startswith("attempt_")


def test_controller_snapshot_reports_trajectory_files(tmp_path):
    run = tmp_path / "run"
    (run / "raw" / "demo" / "trajectory").mkdir(parents=True)
    (run / "metadata").mkdir()
    manifest = {"run_id": "run", "algorithms": {"demo": {"enabled": True}}}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "metadata" / "run_status.json").write_text(json.dumps({"state": "initialized", "algorithms": {"demo": {"state": "pending"}}}), encoding="utf-8")
    controller = ManualRunController(run, "demo")
    controller._output_dir = run / "raw" / "demo"
    (controller._output_dir / "trajectory" / "trajectory_0.db3").write_bytes(b"abc")
    snapshot = controller.trajectory_snapshot()
    assert snapshot["bytes"] == 3
    assert snapshot["messages"] == 0


def test_spawn_uses_an_independent_process_session(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    (run / "raw").mkdir()
    manifest = {"run_id": "run", "algorithms": {"demo": {"enabled": True}}}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    fake_process = Mock(pid=1234)
    fake_process.poll.return_value = 0
    popen = Mock(return_value=fake_process)
    controller = ManualRunController(run, "demo", popen_factory=popen)
    controller._output_dir = run / "raw" / "demo"
    controller._output_dir.mkdir()
    controller._spawn("demo", "exec true", controller._output_dir / "demo.log")
    kwargs = popen.call_args.kwargs
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is not None
    controller.cleanup()


def test_process_snapshot_uses_mocked_psutil_tree(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    (run / "raw").mkdir()
    manifest = {"run_id": "run", "algorithms": {"demo": {"enabled": True}}}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    controller = ManualRunController(run, "demo")
    process = Mock(pid=99)
    process.children.return_value = []
    process.cpu_percent.return_value = 12.5
    process.memory_info.return_value.rss = 4096
    process.num_threads.return_value = 3
    controller._processes["algorithm"] = SimpleNamespace(pid=99)
    with patch("psutil.Process", return_value=process):
        snapshot = controller._process_snapshot()
    assert snapshot == {"pid": 99, "cpu_percent": 12.5, "rss_bytes": 4096, "threads": 3}
    controller._processes.clear()


def test_tail_lines_does_not_need_to_read_the_whole_log(tmp_path):
    path = tmp_path / "large.log"
    path.write_text("old line\n" * 10000 + "last one\nlast two\n", encoding="utf-8")
    assert ManualRunController._tail_lines(path, 2) == ["last one", "last two"]


def test_run_queue_continues_after_a_failed_algorithm(tmp_path):
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"run_id": "run", "algorithms": {}}), encoding="utf-8")
    calls = []

    class FakeController:
        def __init__(self, _run, algorithm, **_kwargs):
            self.algorithm = algorithm
            self.state = "idle"
            calls.append((algorithm, "construct"))

        def prepare(self):
            self.state = "prepared"
            calls.append((self.algorithm, "prepare"))

        def play(self):
            self.state = "finished"
            calls.append((self.algorithm, "play"))
            if self.algorithm == "failed":
                raise RuntimeError("mock crash")
            return {"algorithm": self.algorithm, "status": "SUCCESS", "trajectory_messages": 1}

        def stop_and_save(self):
            self.state = "failed"
            return {"algorithm": self.algorithm, "status": "RUNTIME_CRASH", "reason": "mock crash"}

        def cleanup(self):
            calls.append((self.algorithm, "cleanup"))

    from manual_run_controller import RunQueueWorker

    worker = RunQueueWorker(run, ["failed", "next"], controller_factory=FakeController)
    worker.start()
    worker._thread.join(timeout=3)
    snapshot = worker.snapshot()
    assert snapshot["state"] == "completed"
    assert snapshot["results"]["failed"]["status"] == "RUNTIME_CRASH"
    assert snapshot["results"]["next"]["status"] == "SUCCESS"
    assert calls.index(("failed", "cleanup")) < calls.index(("next", "construct"))
    assert json.loads((run / "metadata/run_queue.json").read_text())["state"] == "completed"
