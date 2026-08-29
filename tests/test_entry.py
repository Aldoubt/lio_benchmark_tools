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


def test_diagnostics_dispatches_fixed_rate_and_pointcloud_index_options(monkeypatch, tmp_path):
    captured = {}

    def fake_execute(run, stage, **kwargs):
        captured.update({"run": run, "stage": stage, **kwargs})
        return 0

    monkeypatch.setattr(entry, "execute_stage", fake_execute)
    result = entry.main([
        "diagnostics",
        "--run", str(tmp_path),
        "--baseline", "fast_livo2",
        "--hz", "20",
        "--window-gap", "0.8",
        "--with-pointcloud-index",
        "--dry-run",
    ])
    assert result == 0
    assert captured["stage"] == "diagnostics"
    assert captured["baseline"] == "fast_livo2"
    assert captured["diagnostic_hz"] == 20.0
    assert captured["anomaly_window_gap_s"] == 0.8
    assert captured["with_pointcloud_index"] is True
    assert captured["dry_run"] is True
