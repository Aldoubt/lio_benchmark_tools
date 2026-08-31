import json
from pathlib import Path

import pytest
from PIL import Image as PILImage

from report_pdf import render_report_pdf, resolve_cjk_font


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_bundle(tmp_path: Path, *, language: str = "en") -> Path:
    frozen = tmp_path / "frozen"
    (frozen / "evidence/overview").mkdir(parents=True)
    PILImage.new("RGB", (16, 8), (240, 240, 240)).save(
        frozen / "evidence/overview/overview.png"
    )
    _write_json(
        frozen / "freeze_manifest.json",
        {"freeze_state": "INCOMPLETE", "generated_artifacts": []},
    )
    _write_json(
        frozen / "report_data.json",
        {
            "schema_version": 1,
            "report_type": "frozen_lio_benchmark_experiment",
            "experiment": {
                "run_id": "run-001",
                "source_run_state": "COMPLETED",
                "freeze_created_at_utc": "2026-08-31T09:00:00+00:00",
                "benchmark": {"branch": "feat/test", "commit": "0123456789abcdef"},
                "baseline": "fast_livo2",
                "language": language,
            },
            "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
            "ground_truth_available": False,
            "ground_truth_disclaimer": "No independent ground truth is available. Accuracy-style metrics are relative-to-baseline diagnostics, not ATE/RPE or absolute accuracy rankings.",
            "dataset_timing": {"dataset": {"duration_s": 100.0}, "playback_rate": 1.0, "dataset_source": {"sha256": "bagsha", "size_bytes": 1234}},
            "calibration": {"source": "test calibration", "confidence": "mixed"},
            "algorithm_provenance": {"fast_livo2": {"commit": "algo1"}, "bad_algo": {"commit": "algo2"}},
            "runtime_health": {
                "fast_livo2": {"status": "SUCCESS", "health_flags": [], "trajectory_health_pass": True, "recommendation_eligible": True},
                "bad_algo": {"status": "FAILED", "health_flags": ["trajectory_short"], "trajectory_health_pass": False, "recommendation_eligible": False},
            },
            "trajectory_summary": {"fast_livo2": {"path_length_m": 50.0, "z_range_m": 0.5}, "bad_algo": {"path_length_m": 20.0, "z_range_m": 3.0}},
            "baseline_relative_diagnostics": {"fast_livo2": {"rmse_m": 0.0, "p95_m": 0.0}, "bad_algo": {"rmse_m": 1.5, "p95_m": 2.0}},
            "resource_summary": {"fast_livo2": {"mean_cpu_percent": 120.0, "peak_rss_mib": 500.0}, "bad_algo": {}},
            "trajectory_diagnostics": {"fast_livo2": {"position_jump_count": 0, "yaw_jump_count": 1}, "bad_algo": {"position_jump_count": 1, "yaw_jump_count": 0}},
            "phase_summary": {"available": False, "data": None},
            "anomaly_summary": {"representative_cases": [{"window_id": "bad_algo:window_0001", "algorithm": "bad_algo", "types": ["position_jump"], "severity": 4.2, "view_start_bag_time_s": 19.5, "view_end_bag_time_s": 20.6}]},
            "evidence_based_conclusions": {"scope": "baseline-relative diagnostic only", "health_valid_algorithms": ["fast_livo2"], "not_recommended_this_run": ["bad_algo"]},
            "reproducibility_checklist": {"benchmark_commit_recorded": True, "dataset_sha256_recorded": True, "native_rerun_registered": True},
            "limitations": ["existing limitation"],
        },
    )
    _write_json(
        frozen / "evidence/evidence_manifest.json",
        {"schema_version": 1, "static_figures": [{"bundle_path": "evidence/overview/overview.png"}], "anomaly_cases": [], "pointcloud_case_evidence": {"available": False, "reason": "pointcloud_frame_index_missing"}},
    )
    return frozen


def test_resolve_cjk_font_uses_first_existing_candidate(tmp_path):
    missing = tmp_path / "missing.ttf"
    existing = tmp_path / "font.ttf"
    existing.write_bytes(b"font")
    assert resolve_cjk_font((missing, existing)) == existing.resolve()


def test_render_report_pdf_generates_and_registers_english_pdf(tmp_path):
    frozen = _make_bundle(tmp_path, language="en")
    result = render_report_pdf(frozen)
    output = frozen / "report/report.pdf"
    assert result["path"] == output
    assert output.read_bytes().startswith(b"%PDF-")
    assert output.stat().st_size > 1000
    manifest = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert manifest["freeze_state"] == "INCOMPLETE"
    assert any(item["path"] == "report/report.pdf" and item["role"] == "offline_pdf_report" for item in manifest["generated_artifacts"])


def test_render_report_pdf_fails_clearly_when_cjk_font_is_unavailable(tmp_path):
    frozen = _make_bundle(tmp_path, language="zh-CN")
    with pytest.raises(RuntimeError, match="CJK font"):
        render_report_pdf(frozen, cjk_font_candidates=())
    assert not (frozen / "report/report.pdf").exists()


def test_render_report_pdf_with_installed_cjk_font(tmp_path):
    candidates = (
        Path("/usr/share/fonts/truetype/arphic-gbsn00lp/gbsn00lp.ttf"),
        Path("/usr/share/fonts/truetype/arphic-gkai00mp/gkai00mp.ttf"),
    )
    font = next((path for path in candidates if path.is_file()), None)
    if font is None:
        pytest.skip("no local CJK TTF in test environment")
    frozen = _make_bundle(tmp_path, language="zh-CN")
    result = render_report_pdf(frozen, cjk_font_candidates=(font,))
    assert result["font_path"] == str(font.resolve())
    assert (frozen / "report/report.pdf").stat().st_size > 1000


def test_render_report_pdf_refuses_complete_bundle(tmp_path):
    frozen = _make_bundle(tmp_path)
    path = frozen / "freeze_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["freeze_state"] = "COMPLETE"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="already COMPLETE"):
        render_report_pdf(frozen)
