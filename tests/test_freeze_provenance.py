import json
from pathlib import Path

import pytest

from freeze_experiment import finalize_freeze, prepare_freeze, register_generated_artifact


def _make_core_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    (run / "metrics/diagnostic_timeline").mkdir(parents=True)
    (run / "standardized/trajectories").mkdir(parents=True)
    manifest = {
        "dataset": {"bag_dir": str(tmp_path / "bag"), "ground_truth": None},
        "evaluation": {"ground_truth_available": False},
        "algorithms": {
            "fast_livo2": {"commit": "abc"},
            "dlio": {"commit": "def"},
        },
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "metadata/run_status.json").write_text(
        json.dumps({"run_id": "run-001", "state": "COMPLETED"}), encoding="utf-8"
    )
    (run / "metrics/full_comparison.json").write_text("{}", encoding="utf-8")
    (run / "metrics/trajectory_discontinuity.json").write_text("{}", encoding="utf-8")
    (run / "metrics/diagnostic_timeline.json").write_text(
        json.dumps({"algorithm_order": ["fast_livo2", "dlio"], "anomaly_windows": []}),
        encoding="utf-8",
    )
    for algorithm in ("fast_livo2", "dlio"):
        (run / f"standardized/trajectories/{algorithm}.csv").write_text(
            "timestamp,x,y,z\n0,0,0,0\n", encoding="utf-8"
        )
        (run / f"metrics/diagnostic_timeline/{algorithm}.csv").write_text(
            "bag_time_s,x_m,y_m,z_m\n0,0,0,0\n", encoding="utf-8"
        )
    bag = tmp_path / "bag"
    bag.mkdir()
    (bag / "metadata.yaml").write_text("bag", encoding="utf-8")
    return run


def _git_identity(monkeypatch):
    monkeypatch.setattr(
        "freeze_experiment.resolve_git_identity",
        lambda _: {"branch": "feat/test", "commit": "0123456789abcdef", "short_sha": "01234567"},
    )


def test_prepare_freeze_snapshots_declared_algorithm_configs_and_calibration(tmp_path, monkeypatch):
    run = _make_core_run(tmp_path)
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["calibration"] = {
        "source": "vehicle calibration",
        "confidence": "measured",
        "lidar_to_imu": {"translation": [0.1, 0.2, 0.3]},
    }
    manifest["algorithms"]["fast_livo2"]["config"] = "configs/fast.yaml"
    manifest["algorithms"]["dlio"]["config"] = "configs/dlio"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "configs/dlio").mkdir(parents=True)
    (tmp_path / "configs/fast.yaml").write_text("fast: 1\n", encoding="utf-8")
    (tmp_path / "configs/dlio/params.yaml").write_text("dlio: 2\n", encoding="utf-8")
    _git_identity(monkeypatch)

    frozen = prepare_freeze(run, baseline="fast_livo2", language="en", repo_root=tmp_path)

    payload = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert payload["calibration"]["source"] == "vehicle calibration"
    fast = payload["config_sources"]["fast_livo2"]
    dlio = payload["config_sources"]["dlio"]
    assert fast["source_path"] == str((tmp_path / "configs/fast.yaml").resolve())
    assert fast["bundle_path"] == "source/configs/fast_livo2/fast.yaml"
    assert fast["sha256"]
    assert (frozen / fast["bundle_path"]).read_text() == "fast: 1\n"
    assert dlio["bundle_path"] == "source/configs/dlio/dlio"
    assert dlio["sha256"]
    assert (frozen / dlio["bundle_path"] / "params.yaml").read_text() == "dlio: 2\n"


def test_prepare_freeze_fails_auditably_when_declared_config_is_missing(tmp_path, monkeypatch):
    run = _make_core_run(tmp_path)
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["algorithms"]["fast_livo2"]["config"] = "configs/missing.yaml"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _git_identity(monkeypatch)

    with pytest.raises(FileNotFoundError, match="algorithm config"):
        prepare_freeze(run, baseline="fast_livo2", language="en", repo_root=tmp_path)

    frozen = next((run / "frozen").iterdir())
    payload = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert payload["freeze_state"] == "INCOMPLETE"
    assert payload["failure"]["stage"] == "config_sources"


def test_finalize_freeze_rechecks_copied_source_artifact_hashes(tmp_path, monkeypatch):
    run = _make_core_run(tmp_path)
    _git_identity(monkeypatch)
    frozen = prepare_freeze(run, baseline="fast_livo2", language="en", repo_root=tmp_path)
    generated = frozen / "viewer/diagnostic.rrd"
    generated.write_bytes(b"rrd")
    register_generated_artifact(frozen, "viewer/diagnostic.rrd", "native_rerun_recording")
    (frozen / "source/manifest.json").write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="source artifact changed"):
        finalize_freeze(frozen, required_generated_paths=("viewer/diagnostic.rrd",))
