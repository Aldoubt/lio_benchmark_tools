from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_automatic_runner_owns_clock_anchor_lifecycle():
    source = (ROOT / "evaluators" / "run_algorithm.sh").read_text(encoding="utf-8")
    assert 'clock_anchor_pid=""' in source
    assert 'clock_anchor_recorder.py" --output "$output_dir/clock_anchors.json"' in source
    assert 'kill -0 "$clock_anchor_pid"' in source
    assert 'stop_process "$clock_anchor_pid" TERM' in source


def test_manual_controller_owns_clock_anchor_lifecycle():
    source = (ROOT / "evaluators" / "manual_run_controller.py").read_text(encoding="utf-8")
    assert 'evaluators/clock_anchor_recorder.py' in source
    assert '"--output", str(self._output_dir / "clock_anchors.json")' in source
    assert 'self._spawn("clock_anchor"' in source
    assert 'self._terminate("clock_anchor", signal.SIGTERM' in source
