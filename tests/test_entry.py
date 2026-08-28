from pathlib import Path

import lio_benchmark.entry as entry


def test_compare_dispatches_to_postprocess(monkeypatch, tmp_path):
    captured = {}

    def fake_execute(run, stage, **kwargs):
        captured.update({"run": run, "stage": stage, **kwargs})
        return 0

    monkeypatch.setattr(entry, "execute_stage", fake_execute)
    result = entry.main([
        "compare", "--run", str(tmp_path), "--with-maps", "--baseline", "fast_livo2",
        "--scan-step", "7", "--point-step", "30", "--voxel", "0.15", "--dry-run",
    ])

    assert result == 0
    assert captured["run"] == Path(tmp_path)
    assert captured["stage"] == "compare"
    assert captured["with_maps"] is True
    assert captured["scan_step"] == 7
    assert captured["point_step"] == 30
    assert captured["voxel"] == 0.15
    assert captured["dry_run"] is True


def test_visualize_defaults_to_lightweight_mode(monkeypatch, tmp_path):
    captured = {}

    def fake_execute(run, stage, **kwargs):
        captured.update({"run": run, "stage": stage, **kwargs})
        return 0

    monkeypatch.setattr(entry, "execute_stage", fake_execute)
    assert entry.main(["visualize", "--run", str(tmp_path)]) == 0
    assert captured["stage"] == "visualize"
    assert captured["with_maps"] is False
