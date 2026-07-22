import json

from benchmark_gui import control_states, load_live_resource, resource_history


def test_gui_buttons_follow_controller_lifecycle():
    idle = control_states("idle", True)
    assert idle["prepare"] is True
    assert idle["play"] is False
    assert idle["stop"] is False
    prepared = control_states("prepared", True)
    assert prepared["prepare"] is False
    assert prepared["play"] is True
    assert prepared["stop"] is True
    playing = control_states("playing", True)
    assert playing["play"] is False
    assert playing["stop"] is True
    assert control_states("finalizing", True)["stop"] is False


def test_gui_without_run_only_allows_refresh():
    states = control_states("idle", False)
    assert states["prepare"] is False
    assert states["open"] is False
    assert states["logs"] is False
    assert states["refresh"] is True


def test_gui_reads_live_resource_for_external_run(tmp_path):
    resource_path = tmp_path / "raw" / "kiss_icp" / "resource_monitor.json"
    resource_path.parent.mkdir(parents=True)
    resource_path.write_text(json.dumps({
        "status": "live",
        "samples": 3,
        "updated_at": "now",
        "latest": {"elapsed_s": 2.0, "cpu_percent": 42.5, "rss_bytes": 10, "threads": 4},
        "sample_history": [
            {"elapsed_s": 1.0, "cpu_percent": 10.0},
            {"elapsed_s": 2.0, "cpu_percent": 42.5},
        ],
    }), encoding="utf-8")
    algorithm, resource = load_live_resource(tmp_path, {
        "state": "running",
        "current_algorithm": "kiss_icp",
        "last_algorithm": "kiss_icp",
        "algorithms": {"kiss_icp": {"state": "running"}},
    }, "kiss_icp")
    assert algorithm == "kiss_icp"
    assert resource["latest"]["cpu_percent"] == 42.5
    assert resource_history(resource) == [(1.0, 10.0), (2.0, 42.5)]
