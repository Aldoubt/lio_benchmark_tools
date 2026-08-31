import json
from pathlib import Path

import pytest

from report_html import render_report_html


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_bundle(tmp_path: Path, *, language: str = "zh-CN") -> Path:
    frozen = tmp_path / "frozen"
    (frozen / "evidence/overview/comparison_dashboard").mkdir(parents=True)
    (frozen / "evidence/overview/comparison_dashboard/diagnostic_dashboard.png").write_bytes(b"png")
    _write_json(frozen / "freeze_manifest.json", {"freeze_state": "INCOMPLETE", "generated_artifacts": []})
    _write_json(frozen / "report_data.json", {
        "schema_version": 1,
        "report_type": "frozen_lio_benchmark_experiment",
        "experiment": {"run_id": "run-001", "source_run_state": "COMPLETED", "freeze_created_at_utc": "2026-08-31T09:00:00+00:00", "benchmark": {"branch": "feat/test", "commit": "0123456789abcdef"}, "baseline": "fast_livo2", "language": language},
        "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
        "ground_truth_available": False,
        "ground_truth_disclaimer": "No independent ground truth is available. Accuracy-style metrics are relative-to-baseline diagnostics, not ATE/RPE or absolute accuracy rankings.",
        "dataset_timing": {"dataset": {"duration_s": 100.0, "lidar_topic": "/lidar", "imu_topic": "/imu"}, "playback_rate": 1.0, "dataset_source": {"size_bytes": 1234, "sha256": "bagsha"}},
        "calibration": {"source": "test calibration", "confidence": "mixed"},
        "runtime_health": {"fast_livo2": {"status": "SUCCESS", "health_flags": [], "trajectory_health_pass": True, "recommendation_eligible": True}, "bad_algo": {"status": "FAILED", "health_flags": ["trajectory_short"], "trajectory_health_pass": False, "recommendation_eligible": False}},
        "trajectory_summary": {"fast_livo2": {"duration_s": 100.0, "path_length_m": 50.0, "z_range_m": 0.5}, "bad_algo": {"duration_s": 40.0, "path_length_m": 20.0, "z_range_m": 3.0}},
        "baseline_relative_diagnostics": {"fast_livo2": {"rmse_m": 0.0, "p95_m": 0.0}, "bad_algo": {"rmse_m": 1.5, "p95_m": 2.0}},
        "map_health": {"fast_livo2": {"available": False, "health_pass": None, "health_flags": []}, "bad_algo": {"available": False, "health_pass": None, "health_flags": []}},
        "resource_summary": {"fast_livo2": {"mean_cpu_percent": 120.0, "peak_rss_mib": 500.0}, "bad_algo": {}},
        "trajectory_diagnostics": {"fast_livo2": {"position_jump_count": 0, "yaw_jump_count": 1}, "bad_algo": {"position_jump_count": 1, "yaw_jump_count": 0}},
        "phase_summary": {"available": False, "data": None},
        "anomaly_summary": {"window_count": 1, "representative_cases": [{"window_id": "bad_algo:window_0001", "algorithm": "bad_algo", "types": ["position_jump"], "severity": 4.2, "view_start_bag_time_s": 19.5, "view_end_bag_time_s": 20.6}], "selected_window_ids": ["bad_algo:window_0001"]},
        "evidence_based_conclusions": {"scope": "baseline-relative diagnostic only", "health_valid_algorithms": ["fast_livo2"], "not_recommended_this_run": ["bad_algo"], "closest_to_baseline": None},
        "reproducibility_checklist": {"benchmark_commit_recorded": True, "dataset_sha256_recorded": True, "algorithm_provenance_recorded": True, "calibration_disclosed": True, "core_source_artifacts_hashed": True, "native_rerun_registered": True},
        "optional_evidence": {"maps": False, "phase_analysis": False, "pointcloud_index": False},
        "limitations": ["existing limitation"],
    })
    _write_json(frozen / "evidence/evidence_manifest.json", {
        "schema_version": 1,
        "static_figures": [{"bundle_path": "evidence/overview/comparison_dashboard/diagnostic_dashboard.png", "bundle_sha256": "abc"}],
        "anomaly_cases": [{"window_id": "bad_algo:window_0001", "algorithm": "bad_algo", "types": ["position_jump"], "severity": 4.2, "bundle_path": "evidence/anomalies/case_01_bad_algo_window_0001.json"}],
        "pointcloud_case_evidence": {"available": False, "source_available": False, "reason": "pointcloud_frame_index_missing"},
    })
    _write_json(frozen / "evidence/anomalies/case_01_bad_algo_window_0001.json", {"window": {"window_id": "bad_algo:window_0001"}})
    return frozen


def test_render_report_html_is_offline_local_and_registers_artifact(tmp_path):
    frozen = _make_bundle(tmp_path, language="zh-CN")
    result = render_report_html(frozen)
    output = frozen / "report/index.html"
    html = output.read_text(encoding="utf-8")
    assert result["path"] == output
    assert "LIO 冻结实验报告" in html
    assert "run-001" in html
    assert "relative-to-baseline/diagnostic/non-ground-truth" in html
    assert "not ATE/RPE" in html
    assert "bad_algo" in html
    assert "../evidence/overview/comparison_dashboard/diagnostic_dashboard.png" in html
    assert "http://" not in html
    assert "https://" not in html
    assert "<script src=" not in html
    manifest = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert manifest["freeze_state"] == "INCOMPLETE"
    assert any(item["path"] == "report/index.html" and item["role"] == "offline_html_report" for item in manifest["generated_artifacts"])


def test_render_report_html_supports_english_and_escapes_untrusted_text(tmp_path):
    frozen = _make_bundle(tmp_path, language="en")
    data_path = frozen / "report_data.json"
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["limitations"] = ["<script>alert('x')</script>"]
    data_path.write_text(json.dumps(payload), encoding="utf-8")
    render_report_html(frozen)
    html = (frozen / "report/index.html").read_text(encoding="utf-8")
    assert "Frozen LIO Experiment Report" in html
    assert "&lt;script&gt;alert" in html
    assert "<script>alert" not in html


def test_render_report_html_rejects_missing_manifest_listed_evidence(tmp_path):
    frozen = _make_bundle(tmp_path)
    (frozen / "evidence/overview/comparison_dashboard/diagnostic_dashboard.png").unlink()
    with pytest.raises(FileNotFoundError, match="diagnostic_dashboard.png"):
        render_report_html(frozen)


def test_render_report_html_refuses_complete_bundle(tmp_path):
    frozen = _make_bundle(tmp_path)
    path = frozen / "freeze_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["freeze_state"] = "COMPLETE"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="already COMPLETE"):
        render_report_html(frozen)
