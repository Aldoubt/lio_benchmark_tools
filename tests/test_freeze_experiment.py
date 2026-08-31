import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from freeze_experiment import (
    discover_freeze_sources,
    freeze_directory_name,
    finalize_freeze,
    prepare_freeze,
    register_generated_artifact,
    resolve_git_identity,
    sha256_path,
    write_json_atomic,
)


def test_sha256_path_hashes_file_bytes(tmp_path):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"abc")
    digest, size = sha256_path(path)
    assert digest == hashlib.sha256(b"abc").hexdigest()
    assert size == 3


def test_sha256_path_directory_is_sorted_and_content_sensitive(tmp_path):
    root = tmp_path / "bag"
    root.mkdir()
    (root / "b.db3").write_bytes(b"B")
    (root / "a.yaml").write_bytes(b"A")
    first, size = sha256_path(root)
    assert size == 2
    (root / "b.db3").write_bytes(b"C")
    second, _ = sha256_path(root)
    assert first != second


def test_freeze_directory_name_is_sanitized_and_deterministic():
    created = dt.datetime(2026, 8, 30, 15, 40, 5, tzinfo=dt.timezone.utc)
    assert freeze_directory_name("greenhouse/run 01", created, "abcdef12") == (
        "greenhouse_run_01_20260830T154005Z_abcdef12"
    )


def test_write_json_atomic_leaves_only_final_file(tmp_path):
    path = tmp_path / "freeze_manifest.json"
    write_json_atomic(path, {"freeze_state": "INCOMPLETE"})
    assert json.loads(path.read_text(encoding="utf-8"))["freeze_state"] == "INCOMPLETE"
    assert not list(tmp_path.glob("*.tmp"))


def make_core_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    (run / "metrics" / "diagnostic_timeline").mkdir(parents=True)
    (run / "standardized" / "trajectories").mkdir(parents=True)
    manifest = {
        "dataset": {"bag_dir": str(tmp_path / "bag"), "ground_truth": None},
        "evaluation": {"ground_truth_available": False},
        "algorithms": {
            "fast_livo2": {"group": "lidar_imu_odometry", "commit": "abc"},
            "dlio": {"group": "lidar_imu_odometry", "commit": "def"},
        },
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "metadata" / "run_status.json").write_text(
        json.dumps({"run_id": "run-001", "state": "COMPLETED"}), encoding="utf-8"
    )
    for rel in ("full_comparison.json", "trajectory_discontinuity.json"):
        (run / "metrics" / rel).write_text("{}", encoding="utf-8")
    (run / "metrics" / "diagnostic_timeline.json").write_text(
        json.dumps({"algorithm_order": ["fast_livo2", "dlio"], "anomaly_windows": []}),
        encoding="utf-8",
    )
    for algorithm in ("fast_livo2", "dlio"):
        (run / "standardized" / "trajectories" / f"{algorithm}.csv").write_text(
            "timestamp,x,y,z\n0,0,0,0\n", encoding="utf-8"
        )
        (run / "metrics" / "diagnostic_timeline" / f"{algorithm}.csv").write_text(
            "bag_time_s,x_m,y_m,z_m\n0,0,0,0\n", encoding="utf-8"
        )
    bag = tmp_path / "bag"
    bag.mkdir()
    (bag / "metadata.yaml").write_text("rosbag2_bagfile_information: {}", encoding="utf-8")
    return run


def test_discover_freeze_sources_keeps_failed_algorithm_evidence(tmp_path):
    run = make_core_run(tmp_path)
    sources = discover_freeze_sources(run)
    assert sources["algorithms"] == ["fast_livo2", "dlio"]
    required = {path.relative_to(run).as_posix() for path in sources["required_files"]}
    assert "standardized/trajectories/dlio.csv" in required
    assert "metrics/diagnostic_timeline/dlio.csv" in required


def test_discover_freeze_sources_fails_when_core_diagnostic_is_missing(tmp_path):
    run = make_core_run(tmp_path)
    (run / "metrics" / "trajectory_discontinuity.json").unlink()
    with pytest.raises(FileNotFoundError, match="trajectory_discontinuity"):
        discover_freeze_sources(run)


def test_discover_freeze_sources_marks_optional_evidence_without_requiring_it(tmp_path):
    run = make_core_run(tmp_path)
    sources = discover_freeze_sources(run)
    assert sources["optional_evidence"] == {
        "maps": False,
        "phase_analysis": False,
        "pointcloud_index": False,
        "resource_timelines": False,
    }


def test_prepare_freeze_creates_incomplete_bundle_and_copies_small_core_files(tmp_path, monkeypatch):
    run = make_core_run(tmp_path)
    monkeypatch.setattr(
        "freeze_experiment.resolve_git_identity",
        lambda _: {"branch": "feat/test", "commit": "0123456789abcdef", "short_sha": "01234567"},
    )
    created = dt.datetime(2026, 8, 30, 15, 40, 5, tzinfo=dt.timezone.utc)
    frozen = prepare_freeze(
        run,
        baseline="fast_livo2",
        language="zh-CN",
        repo_root=tmp_path,
        created_at=created,
    )
    payload = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["freeze_state"] == "INCOMPLETE"
    assert payload["metric_class"] == "relative-to-baseline/diagnostic/non-ground-truth"
    assert payload["ground_truth_available"] is False
    assert payload["source_run"]["run_id"] == "run-001"
    assert payload["algorithms"] == ["fast_livo2", "dlio"]
    assert (frozen / "source/manifest.json").is_file()
    assert (frozen / "source/standardized/trajectories/dlio.csv").is_file()
    assert not (frozen / "source/bag").exists()
    assert payload["dataset_source"]["path"].endswith("/bag")
    assert payload["dataset_source"]["sha256"]


def test_prepare_freeze_never_overwrites_same_identity(tmp_path, monkeypatch):
    run = make_core_run(tmp_path)
    monkeypatch.setattr(
        "freeze_experiment.resolve_git_identity",
        lambda _: {"branch": "feat/test", "commit": "0123456789abcdef", "short_sha": "01234567"},
    )
    created = dt.datetime(2026, 8, 30, 15, 40, 5, tzinfo=dt.timezone.utc)
    kwargs = dict(baseline="fast_livo2", language="en", repo_root=tmp_path, created_at=created)
    prepare_freeze(run, **kwargs)
    with pytest.raises(FileExistsError):
        prepare_freeze(run, **kwargs)


def _prepare_test_freeze(tmp_path, monkeypatch):
    run = make_core_run(tmp_path)
    monkeypatch.setattr(
        "freeze_experiment.resolve_git_identity",
        lambda _: {"branch": "feat/test", "commit": "0123456789abcdef", "short_sha": "01234567"},
    )
    return prepare_freeze(run, baseline="fast_livo2", language="en", repo_root=tmp_path)


def test_register_generated_artifact_records_relative_hash(tmp_path, monkeypatch):
    frozen = _prepare_test_freeze(tmp_path, monkeypatch)
    generated = frozen / "viewer/diagnostic.rrd"
    generated.write_bytes(b"rrd")
    record = register_generated_artifact(frozen, "viewer/diagnostic.rrd", "native_rerun_recording")
    assert record["path"] == "viewer/diagnostic.rrd"
    assert record["size_bytes"] == 3
    manifest = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert manifest["freeze_state"] == "INCOMPLETE"
    assert manifest["generated_artifacts"] == [record]


def test_register_generated_artifact_rejects_path_traversal(tmp_path, monkeypatch):
    frozen = _prepare_test_freeze(tmp_path, monkeypatch)
    outside = frozen.parent / "outside.bin"
    outside.write_bytes(b"outside")
    with pytest.raises(ValueError, match="relative path"):
        register_generated_artifact(frozen, "../outside.bin", "bad")


def test_register_generated_artifact_replaces_existing_record(tmp_path, monkeypatch):
    frozen = _prepare_test_freeze(tmp_path, monkeypatch)
    generated = frozen / "viewer/diagnostic.rrd"
    generated.write_bytes(b"one")
    register_generated_artifact(frozen, "viewer/diagnostic.rrd", "native_rerun_recording")
    generated.write_bytes(b"two-two")
    second = register_generated_artifact(frozen, "viewer/diagnostic.rrd", "native_rerun_recording")
    manifest = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert manifest["generated_artifacts"] == [second]
    assert second["size_bytes"] == 7


def test_finalize_freeze_requires_every_declared_generated_artifact(tmp_path, monkeypatch):
    frozen = _prepare_test_freeze(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError, match="viewer/diagnostic.rrd"):
        finalize_freeze(frozen, required_generated_paths=("viewer/diagnostic.rrd",))
    payload = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert payload["freeze_state"] == "INCOMPLETE"


def test_finalize_freeze_rejects_unregistered_generated_artifact(tmp_path, monkeypatch):
    frozen = _prepare_test_freeze(tmp_path, monkeypatch)
    (frozen / "viewer/diagnostic.rrd").write_bytes(b"rrd")
    with pytest.raises(ValueError, match="not registered"):
        finalize_freeze(frozen, required_generated_paths=("viewer/diagnostic.rrd",))


def test_finalize_freeze_rejects_generated_artifact_changed_after_registration(tmp_path, monkeypatch):
    frozen = _prepare_test_freeze(tmp_path, monkeypatch)
    path = frozen / "viewer/diagnostic.rrd"
    path.write_bytes(b"rrd")
    register_generated_artifact(frozen, "viewer/diagnostic.rrd", "native_rerun_recording")
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed after registration"):
        finalize_freeze(frozen, required_generated_paths=("viewer/diagnostic.rrd",))


def test_finalize_freeze_promotes_only_after_hash_verification(tmp_path, monkeypatch):
    frozen = _prepare_test_freeze(tmp_path, monkeypatch)
    path = frozen / "viewer/diagnostic.rrd"
    path.write_bytes(b"rrd")
    register_generated_artifact(frozen, "viewer/diagnostic.rrd", "native_rerun_recording")
    completed = dt.datetime(2026, 8, 30, 16, 0, tzinfo=dt.timezone.utc)
    payload = finalize_freeze(
        frozen,
        required_generated_paths=("viewer/diagnostic.rrd",),
        completed_at=completed,
    )
    assert payload["freeze_state"] == "COMPLETE"
    assert payload["completed_at_utc"] == completed.isoformat()


def test_complete_bundle_rejects_registration_and_refinalization(tmp_path, monkeypatch):
    frozen = _prepare_test_freeze(tmp_path, monkeypatch)
    path = frozen / "viewer/diagnostic.rrd"
    path.write_bytes(b"rrd")
    register_generated_artifact(frozen, "viewer/diagnostic.rrd", "native_rerun_recording")
    finalize_freeze(frozen, required_generated_paths=("viewer/diagnostic.rrd",))
    with pytest.raises(ValueError, match="already COMPLETE"):
        register_generated_artifact(frozen, "viewer/diagnostic.rrd", "native_rerun_recording")
    with pytest.raises(ValueError, match="already COMPLETE"):
        finalize_freeze(frozen, required_generated_paths=("viewer/diagnostic.rrd",))
