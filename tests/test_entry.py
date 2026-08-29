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


def test_viewer_dispatches_display_options(monkeypatch, tmp_path):
    captured = {}

    def fake_execute(run, stage, **kwargs):
        captured.update({"run": run, "stage": stage, **kwargs})
        return 0

    monkeypatch.setattr(entry, "execute_stage", fake_execute)
    result = entry.main([
        "viewer",
        "--run", str(tmp_path),
        "--mode", "native",
        "--baseline", "fast_livo2",
        "--algorithms", "fast_livo2,point_lio",
        "--lang", "en",
        "--no-maps",
        "--pointcloud-mode", "sampled",
        "--pointcloud-period", "2.0",
        "--point-step", "25",
        "--point-lods", "10,20,80",
        "--world-pointcloud-mode", "sampled",
        "--world-algorithm", "point_lio",
        "--map-point-step", "5",
        "--save", str(tmp_path / "viewer.rrd"),
        "--no-spawn",
        "--dry-run",
    ])
    assert result == 0
    assert captured["stage"] == "viewer"
    assert captured["viewer_mode"] == "native"
    assert captured["viewer_algorithms"] == "fast_livo2,point_lio"
    assert captured["viewer_language"] == "en"
    assert captured["viewer_with_maps"] is False
    assert captured["viewer_pointcloud_mode"] == "sampled"
    assert captured["viewer_pointcloud_period_s"] == 2.0
    assert captured["viewer_point_step"] == 25
    assert captured["viewer_point_lods"] == "10,20,80"
    assert captured["viewer_world_pointcloud_mode"] == "sampled"
    assert captured["viewer_world_algorithm"] == "point_lio"
    assert captured["viewer_map_point_step"] == 5
    assert captured["viewer_save"] == Path(tmp_path / "viewer.rrd")
    assert captured["viewer_spawn"] is False
    assert captured["dry_run"] is True


def test_viewer_auto_language_uses_english_for_native(monkeypatch, tmp_path):
    captured = {}

    def fake_execute(run, stage, **kwargs):
        captured.update({"run": run, "stage": stage, **kwargs})
        return 0

    monkeypatch.setattr(entry, "execute_stage", fake_execute)
    assert entry.main(["viewer", "--run", str(tmp_path), "--mode", "native", "--dry-run"]) == 0
    assert captured["viewer_language"] == "en"


def test_web_viewer_mode_dispatches_chinese_shell_by_default(monkeypatch, tmp_path):
    captured = {}

    def fake_execute(run, stage, **kwargs):
        captured.update({"run": run, "stage": stage, **kwargs})
        return 0

    monkeypatch.setattr(entry, "execute_stage", fake_execute)
    result = entry.main([
        "viewer", "--run", str(tmp_path), "--mode", "web", "--dry-run"
    ])
    assert result == 0
    assert captured["viewer_mode"] == "web"
    assert captured["viewer_language"] == "zh-CN"
    assert captured["viewer_save"] is None
