import json
from pathlib import Path

import pytest

import freeze_workflow


def _write_manifest(frozen: Path, *, state="INCOMPLETE", artifacts=None, failure=None):
    frozen.mkdir(parents=True, exist_ok=True)
    (frozen / "freeze_manifest.json").write_text(
        json.dumps(
            {
                "freeze_state": state,
                "generated_artifacts": artifacts or [],
                "failure": failure,
            }
        ),
        encoding="utf-8",
    )


def test_run_freeze_workflow_executes_frozen_pipeline_and_finalizes_all_generated(monkeypatch, tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    frozen = run / "frozen" / "snapshot"
    calls = []

    def prepare(*args, **kwargs):
        calls.append(("prepare", kwargs["baseline"], kwargs["language"], kwargs["repo_root"]))
        _write_manifest(frozen)
        return frozen

    def stage(name, relative):
        def invoke(bundle):
            calls.append((name, bundle))
            path = bundle / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
            manifest_path = bundle / "freeze_manifest.json"
            payload = json.loads(manifest_path.read_text())
            payload["generated_artifacts"].append(
                {"path": relative, "role": name, "sha256": "fake", "size_bytes": path.stat().st_size}
            )
            manifest_path.write_text(json.dumps(payload))
            return {"path": path}
        return invoke

    monkeypatch.setattr(freeze_workflow, "prepare_freeze", prepare)
    monkeypatch.setattr(freeze_workflow, "build_frozen_rerun", stage("rrd", "viewer/diagnostic.rrd"))
    monkeypatch.setattr(freeze_workflow, "build_report_data", stage("data", "report_data.json"))
    monkeypatch.setattr(freeze_workflow, "build_report_evidence", stage("evidence", "evidence/evidence_manifest.json"))
    monkeypatch.setattr(freeze_workflow, "render_report_html", stage("html", "report/index.html"))
    monkeypatch.setattr(freeze_workflow, "render_report_pdf", stage("pdf", "report/report.pdf"))

    finalized = {}
    def finalize(bundle, *, required_generated_paths, completed_at=None):
        finalized["bundle"] = bundle
        finalized["paths"] = required_generated_paths
        payload = json.loads((bundle / "freeze_manifest.json").read_text())
        payload["freeze_state"] = "COMPLETE"
        (bundle / "freeze_manifest.json").write_text(json.dumps(payload))
        return payload
    monkeypatch.setattr(freeze_workflow, "finalize_freeze", finalize)

    result = freeze_workflow.run_freeze_workflow(
        run,
        baseline="fast_livo2",
        language="zh-CN",
        repo_root=tmp_path,
    )

    assert result["frozen"] == frozen
    assert result["freeze_state"] == "COMPLETE"
    assert [item[0] for item in calls] == ["prepare", "rrd", "data", "evidence", "html", "pdf"]
    assert set(finalized["paths"]) == {
        "viewer/diagnostic.rrd",
        "report_data.json",
        "evidence/evidence_manifest.json",
        "report/index.html",
        "report/report.pdf",
    }


def test_run_freeze_workflow_verifies_extra_registered_evidence_before_complete(monkeypatch, tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    frozen = run / "frozen/snapshot"

    def prepare(*args, **kwargs):
        _write_manifest(frozen)
        return frozen

    monkeypatch.setattr(freeze_workflow, "prepare_freeze", prepare)
    for name in ("build_frozen_rerun", "build_report_data", "render_report_html", "render_report_pdf"):
        monkeypatch.setattr(freeze_workflow, name, lambda bundle: {})

    def evidence(bundle):
        path = bundle / "evidence/overview/dashboard.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        payload = json.loads((bundle / "freeze_manifest.json").read_text())
        payload["generated_artifacts"].append(
            {"path": "evidence/overview/dashboard.png", "role": "static_report_evidence", "sha256": "fake", "size_bytes": 3}
        )
        (bundle / "freeze_manifest.json").write_text(json.dumps(payload))
        return {}
    monkeypatch.setattr(freeze_workflow, "build_report_evidence", evidence)

    captured = {}
    def finalize(bundle, *, required_generated_paths, completed_at=None):
        captured["paths"] = required_generated_paths
        return {"freeze_state": "COMPLETE"}
    monkeypatch.setattr(freeze_workflow, "finalize_freeze", finalize)

    freeze_workflow.run_freeze_workflow(run, baseline="fast_livo2", language="en", repo_root=tmp_path)
    assert "evidence/overview/dashboard.png" in captured["paths"]


def test_run_freeze_workflow_records_failed_stage_and_never_finalizes(monkeypatch, tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    frozen = run / "frozen/snapshot"

    def prepare(*args, **kwargs):
        _write_manifest(frozen)
        return frozen

    monkeypatch.setattr(freeze_workflow, "prepare_freeze", prepare)
    monkeypatch.setattr(freeze_workflow, "build_frozen_rerun", lambda bundle: {})
    monkeypatch.setattr(
        freeze_workflow,
        "build_report_data",
        lambda bundle: (_ for _ in ()).throw(RuntimeError("report data failed")),
    )
    finalized = []
    monkeypatch.setattr(freeze_workflow, "finalize_freeze", lambda *args, **kwargs: finalized.append(True))

    with pytest.raises(RuntimeError, match="report data failed"):
        freeze_workflow.run_freeze_workflow(run, baseline="fast_livo2", language="en", repo_root=tmp_path)

    payload = json.loads((frozen / "freeze_manifest.json").read_text())
    assert payload["freeze_state"] == "INCOMPLETE"
    assert payload["failure"]["stage"] == "report_data.json"
    assert payload["failure"]["type"] == "RuntimeError"
    assert finalized == []


def test_run_freeze_workflow_rejects_unknown_language_before_creating_snapshot(monkeypatch, tmp_path):
    run = tmp_path / "run"
    called = []
    monkeypatch.setattr(freeze_workflow, "prepare_freeze", lambda *args, **kwargs: called.append(True))
    with pytest.raises(ValueError, match="language"):
        freeze_workflow.run_freeze_workflow(run, baseline="fast_livo2", language="fr", repo_root=tmp_path)
    assert called == []
