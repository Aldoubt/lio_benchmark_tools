import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lio_benchmark.frozen_bundle import (
    export_frozen_bundle,
    open_frozen_recording,
    verify_registered_artifact,
)


def _sha(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def _write(path: Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    digest, size = _sha(path)
    return {"path": path, "sha256": digest, "size_bytes": size}


def _make_complete_bundle(tmp_path: Path) -> Path:
    frozen = tmp_path / "frozen"
    artifacts = []
    for rel, role, data in (
        ("viewer/diagnostic.rrd", "native_rerun_recording", b"rrd"),
        ("report/index.html", "offline_html_report", b"<html>offline</html>"),
        ("report/report.pdf", "offline_pdf_report", b"%PDF-fake"),
        ("evidence/overview/dashboard.png", "static_report_evidence", b"png"),
        ("evidence/evidence_manifest.json", "report_evidence_manifest", b"{}"),
    ):
        info = _write(frozen / rel, data)
        artifacts.append({"path": rel, "role": role, "sha256": info["sha256"], "size_bytes": info["size_bytes"]})

    report_data = {
        "runtime_health": {
            "fast_livo2": {"status": "SUCCESS", "trajectory_health_pass": True, "recommendation_eligible": True},
            "bad_algo": {"status": "FAILED", "trajectory_health_pass": False, "recommendation_eligible": False},
        },
        "trajectory_summary": {"fast_livo2": {"path_length_m": 50.0, "z_range_m": 0.5}, "bad_algo": {"path_length_m": 20.0, "z_range_m": 3.0}},
        "resource_summary": {"fast_livo2": {"mean_cpu_percent": 120.0, "peak_rss_mib": 500.0}, "bad_algo": {}},
        "baseline_relative_diagnostics": {"fast_livo2": {"rmse_m": 0.0, "p95_m": 0.0}, "bad_algo": {"rmse_m": 1.5, "p95_m": 2.0}},
        "trajectory_diagnostics": {"fast_livo2": {"position_jump_count": 0, "yaw_jump_count": 1}, "bad_algo": {"position_jump_count": 1, "yaw_jump_count": 0}},
    }
    path = frozen / "report_data.json"
    path.write_text(json.dumps(report_data), encoding="utf-8")
    digest, size = _sha(path)
    artifacts.append({"path": "report_data.json", "role": "shared_report_data", "sha256": digest, "size_bytes": size})

    evidence = {
        "static_figures": [{"bundle_path": "evidence/overview/dashboard.png"}],
        "anomaly_cases": [],
    }
    path = frozen / "evidence/evidence_manifest.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    digest, size = _sha(path)
    for item in artifacts:
        if item["path"] == "evidence/evidence_manifest.json":
            item["sha256"] = digest
            item["size_bytes"] = size

    manifest = {
        "schema_version": 1,
        "freeze_state": "COMPLETE",
        "source_run": {"path": "/definitely/missing/live/run", "run_id": "run-001", "state": "COMPLETED"},
        "generated_artifacts": artifacts,
    }
    (frozen / "freeze_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return frozen


def test_verify_registered_artifact_rejects_tampering(tmp_path):
    frozen = _make_complete_bundle(tmp_path)
    record = verify_registered_artifact(frozen, "viewer/diagnostic.rrd")
    assert record["role"] == "native_rerun_recording"
    (frozen / "viewer/diagnostic.rrd").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        verify_registered_artifact(frozen, "viewer/diagnostic.rrd")


def test_open_frozen_recording_uses_only_registered_rrd_and_never_source_run(tmp_path):
    frozen = _make_complete_bundle(tmp_path)
    calls = []

    def fake_run(command, check=False):
        calls.append((command, check))
        return SimpleNamespace(returncode=0)

    result = open_frozen_recording(
        frozen,
        executable_resolver=lambda _: "/usr/bin/rerun",
        run_process=fake_run,
    )

    assert result == 0
    assert calls == [(["/usr/bin/rerun", str((frozen / "viewer/diagnostic.rrd").resolve())], False)]


def test_open_frozen_recording_requires_complete_bundle(tmp_path):
    frozen = _make_complete_bundle(tmp_path)
    path = frozen / "freeze_manifest.json"
    payload = json.loads(path.read_text())
    payload["freeze_state"] = "INCOMPLETE"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="not COMPLETE"):
        open_frozen_recording(frozen, executable_resolver=lambda _: "/usr/bin/rerun")


def test_export_frozen_bundle_materializes_delivery_from_frozen_only(tmp_path):
    frozen = _make_complete_bundle(tmp_path)
    output = tmp_path / "delivery"

    result = export_frozen_bundle(frozen, output=output)

    assert result == output.resolve()
    assert (output / "report.html").read_bytes() == (frozen / "report/index.html").read_bytes()
    assert (output / "report.pdf").read_bytes() == (frozen / "report/report.pdf").read_bytes()
    assert (output / "figures/overview/dashboard.png").read_bytes() == b"png"
    assert json.loads((output / "metrics/summary.json").read_text()) == json.loads((frozen / "report_data.json").read_text())
    assert json.loads((output / "provenance/freeze_manifest.json").read_text())["freeze_state"] == "COMPLETE"
    with (output / "metrics/summary.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["algorithm"] for row in rows] == ["fast_livo2", "bad_algo"]
    assert rows[1]["status"] == "FAILED"
    assert rows[1]["relative_rmse_m"] == "1.5"


def test_export_refuses_overwrite_and_tampered_frozen_report(tmp_path):
    frozen = _make_complete_bundle(tmp_path)
    existing = tmp_path / "delivery"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        export_frozen_bundle(frozen, output=existing)

    existing.rmdir()
    (frozen / "report/report.pdf").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash or size mismatch"):
        export_frozen_bundle(frozen, output=existing)
    assert not existing.exists()
