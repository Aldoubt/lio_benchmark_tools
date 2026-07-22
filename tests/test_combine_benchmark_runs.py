import json

from combine_benchmark_runs import combine


def _write_run(root, algorithm_dir, *, output_dir=None):
    (root / "metadata").mkdir(parents=True, exist_ok=True)
    (root / "raw" / algorithm_dir).mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 2,
        "name": root.name,
        "output_root": str(root.parent),
        "playback_rate": 1.0,
        "dataset": {},
        "calibration": {},
        "algorithms": {
            "fast_livo2": {"enabled": True},
            "mola_lio": {"enabled": True},
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = {"algorithm": algorithm_dir, "status": "SUCCESS"}
    if output_dir:
        result["output_dir"] = str(output_dir)
    status = {"run_id": root.name, "state": "completed", "algorithms": {
        "fast_livo2": {"state": "completed", "result": {"status": "SUCCESS"}},
        "mola_lio": {"state": "pending"},
    }}
    status["algorithms"][algorithm_dir] = {"state": "completed", "result": result}
    (root / "metadata" / "run_status.json").write_text(json.dumps(status), encoding="utf-8")
    (root / "raw" / algorithm_dir / "marker.txt").write_text(root.name, encoding="utf-8")


def test_combine_overlays_one_algorithm_without_mutating_base(tmp_path):
    base = tmp_path / "base"
    override = tmp_path / "override"
    output = tmp_path / "combined"
    _write_run(base, "fast_livo2")
    _write_run(base, "mola_lio")
    _write_run(override, "mola_lio", output_dir=override / "raw" / "mola_lio")
    (override / "raw" / "mola_lio" / "marker.txt").write_text("new", encoding="utf-8")

    combine(base, override, output, "mola_lio")

    assert (base / "raw" / "mola_lio" / "marker.txt").read_text() == "base"
    assert (output / "raw" / "mola_lio" / "marker.txt").read_text() == "new"
    assert (output / "raw" / "fast_livo2" / "marker.txt").read_text() == "base"
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["composition"]["override_run"] == str(override.resolve())
    status = json.loads((output / "metadata" / "run_status.json").read_text())
    assert status["algorithms"]["mola_lio"]["result"]["output_dir"] == str(output / "raw" / "mola_lio")
