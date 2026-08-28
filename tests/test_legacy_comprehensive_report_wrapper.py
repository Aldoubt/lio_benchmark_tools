from pathlib import Path


def test_legacy_comprehensive_report_entrypoint_delegates_without_historical_literals():
    root = Path(__file__).resolve().parents[1]
    text = (root / "evaluators" / "generate_comprehensive_report.py").read_text(
        encoding="utf-8"
    )
    assert "from current_run_report import main" in text
    for stale in ("805.5", "63.6 km", "4.14 GiB", "单次 807 s"):
        assert stale not in text
