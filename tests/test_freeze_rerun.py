import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from freeze_rerun import (
    build_frozen_rerun,
    finalize_saved_rerun_recording,
    pointcloud_source_status,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_source_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "metrics").mkdir(parents=True)
    return run


def _make_frozen(tmp_path: Path, run: Path) -> Path:
    frozen = tmp_path / "frozen"
    (frozen / "viewer").mkdir(parents=True)
    _write_json(
        frozen / "freeze_manifest.json",
        {
            "schema_version": 1,
            "freeze_state": "INCOMPLETE",
            "source_run": {"path": str(run), "run_id": "run-001", "state": "COMPLETED"},
            "baseline": "fast_livo2",
            "language": "zh-CN",
            "algorithms": ["fast_livo2", "dlio"],
            "optional_evidence": {"pointcloud_index": False, "maps": False},
            "generated_artifacts": [],
        },
    )
    return frozen


def test_pointcloud_source_status_discloses_absent_index(tmp_path):
    run = _make_source_run(tmp_path)
    status = pointcloud_source_status(run)
    assert status["available"] is False
    assert status["reason"] == "pointcloud_frame_index_missing"


def test_pointcloud_source_status_discloses_malformed_index(tmp_path):
    run = _make_source_run(tmp_path)
    (run / "metrics/pointcloud_frame_index.json").write_text("[]", encoding="utf-8")
    status = pointcloud_source_status(run)
    assert status["available"] is False
    assert status["reason"] == "pointcloud_frame_index_invalid"


def test_pointcloud_source_status_requires_sqlite_source(tmp_path):
    run = _make_source_run(tmp_path)
    _write_json(
        run / "metrics/pointcloud_frame_index.json",
        {"sqlite_db": "missing.db3", "lidar_topic": "/livox/lidar", "lidar_type": "livox_ros_driver2/msg/CustomMsg"},
    )
    status = pointcloud_source_status(run)
    assert status["available"] is False
    assert status["reason"] == "pointcloud_sqlite_missing"
    assert status["sqlite_db"].endswith("missing.db3")


def test_pointcloud_source_status_accepts_usable_index(tmp_path, monkeypatch):
    run = _make_source_run(tmp_path)
    sqlite_db = run / "bag.db3"
    sqlite_db.write_bytes(b"sqlite")
    _write_json(
        run / "metrics/pointcloud_frame_index.json",
        {"sqlite_db": "bag.db3", "lidar_topic": "/livox/lidar", "lidar_type": "livox_ros_driver2/msg/CustomMsg"},
    )
    monkeypatch.setattr("freeze_rerun._pointcloud_runtime_status", lambda _: (True, None))
    status = pointcloud_source_status(run)
    assert status == {
        "available": True,
        "reason": None,
        "index_path": str(run / "metrics/pointcloud_frame_index.json"),
        "sqlite_db": str(sqlite_db),
    }


def test_build_frozen_rerun_omits_optional_pointcloud_and_registers_rrd(tmp_path, monkeypatch):
    run = _make_source_run(tmp_path)
    frozen = _make_frozen(tmp_path, run)
    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        Path(kwargs["save"]).write_bytes(b"rrd")
        return {"pointcloud_frames_logged": 0, "world_pointcloud_frames_logged": 0}

    monkeypatch.setattr(
        "freeze_rerun._viewer_api",
        lambda: (fake_builder, lambda _: {"dense": 10, "medium": 20, "sparse": 80}, "10,20,80"),
    )
    monkeypatch.setattr("freeze_rerun.finalize_saved_rerun_recording", lambda: "0.36.3")

    result = build_frozen_rerun(frozen)

    assert captured["run"] == run.resolve()
    assert captured["algorithms"] == ["fast_livo2", "dlio"]
    assert captured["baseline"] == "fast_livo2"
    assert captured["language"] == "zh-CN"
    assert captured["pointcloud_mode"] == "none"
    assert captured["world_pointcloud_mode"] == "none"
    assert captured["spawn"] is False
    assert captured["save"] == (frozen / "viewer/diagnostic.rrd").resolve()
    assert result["artifact"]["role"] == "native_rerun_recording"

    manifest = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert manifest["freeze_state"] == "INCOMPLETE"
    assert manifest["generated_artifacts"][0]["path"] == "viewer/diagnostic.rrd"
    assert manifest["rerun_recording"]["sdk_version"] == "0.36.3"
    assert manifest["rerun_recording"]["pointcloud_evidence"]["enabled"] is False
    assert manifest["rerun_recording"]["pointcloud_evidence"]["omission_reason"] == "pointcloud_frame_index_missing"


def test_build_frozen_rerun_uses_anomaly_only_pointcloud_when_source_is_usable(tmp_path, monkeypatch):
    run = _make_source_run(tmp_path)
    sqlite_db = run / "bag.db3"
    sqlite_db.write_bytes(b"sqlite")
    _write_json(
        run / "metrics/pointcloud_frame_index.json",
        {"sqlite_db": str(sqlite_db), "lidar_topic": "/livox/lidar", "lidar_type": "livox_ros_driver2/msg/CustomMsg"},
    )
    frozen = _make_frozen(tmp_path, run)
    captured = {}
    monkeypatch.setattr("freeze_rerun._pointcloud_runtime_status", lambda _: (True, None))

    def fake_builder(**kwargs):
        captured.update(kwargs)
        Path(kwargs["save"]).write_bytes(b"rrd")
        return {"pointcloud_frames_logged": 3, "world_pointcloud_frames_logged": 3}

    monkeypatch.setattr(
        "freeze_rerun._viewer_api",
        lambda: (fake_builder, lambda _: {"dense": 10, "medium": 20, "sparse": 80}, "10,20,80"),
    )
    monkeypatch.setattr("freeze_rerun.finalize_saved_rerun_recording", lambda: "0.36.3")

    build_frozen_rerun(frozen)

    assert captured["pointcloud_mode"] == "anomaly"
    assert captured["world_pointcloud_mode"] == "anomaly"
    assert captured["pointcloud_period_s"] == 1.0


def test_build_frozen_rerun_requires_builder_to_materialize_rrd(tmp_path, monkeypatch):
    run = _make_source_run(tmp_path)
    frozen = _make_frozen(tmp_path, run)

    monkeypatch.setattr(
        "freeze_rerun._viewer_api",
        lambda: (lambda **_: {}, lambda _: {"dense": 10, "medium": 20, "sparse": 80}, "10,20,80"),
    )
    monkeypatch.setattr("freeze_rerun.finalize_saved_rerun_recording", lambda: "0.36.3")

    with pytest.raises(RuntimeError, match="did not create"):
        build_frozen_rerun(frozen)

    manifest = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert manifest["freeze_state"] == "INCOMPLETE"
    assert manifest["generated_artifacts"] == []
    assert manifest["failure"]["stage"] == "viewer/diagnostic.rrd"


def test_pointcloud_source_status_omits_lidar_when_ros_message_runtime_is_unavailable(tmp_path, monkeypatch):
    run = _make_source_run(tmp_path)
    sqlite_db = run / "bag.db3"
    sqlite_db.write_bytes(b"sqlite")
    _write_json(
        run / "metrics/pointcloud_frame_index.json",
        {"sqlite_db": str(sqlite_db), "lidar_topic": "/livox/lidar", "lidar_type": "livox_ros_driver2/msg/CustomMsg"},
    )
    monkeypatch.setattr(
        "freeze_rerun._pointcloud_runtime_status",
        lambda _: (False, "pointcloud_runtime_unavailable"),
    )

    status = pointcloud_source_status(run)

    assert status["available"] is False
    assert status["reason"] == "pointcloud_runtime_unavailable"


def test_build_frozen_rerun_finalizes_file_sink_before_hash_registration(tmp_path, monkeypatch):
    run = _make_source_run(tmp_path)
    frozen = _make_frozen(tmp_path, run)

    def fake_builder(**kwargs):
        Path(kwargs["save"]).write_bytes(b"partial")
        return {}

    def fake_finalize():
        with (frozen / "viewer/diagnostic.rrd").open("ab") as stream:
            stream.write(b"footer")
        return "0.36.3"

    monkeypatch.setattr(
        "freeze_rerun._viewer_api",
        lambda: (fake_builder, lambda _: {"dense": 10, "medium": 20, "sparse": 80}, "10,20,80"),
    )
    monkeypatch.setattr("freeze_rerun.finalize_saved_rerun_recording", fake_finalize)

    result = build_frozen_rerun(frozen)

    assert result["artifact"]["size_bytes"] == len(b"partialfooter")


def test_finalize_saved_rerun_uses_disconnect_for_rerun_0363(monkeypatch):
    calls: list[str] = []
    fake_rerun = SimpleNamespace(
        __version__="0.36.3",
        disconnect=lambda: calls.append("disconnect"),
    )
    monkeypatch.setitem(sys.modules, "rerun", fake_rerun)

    version = finalize_saved_rerun_recording()

    assert version == "0.36.3"
    assert calls == ["disconnect"]
