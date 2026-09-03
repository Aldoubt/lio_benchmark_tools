from pathlib import Path

from generate_comprehensive_report import build_report, main


def test_legacy_comprehensive_report_entrypoint_preserves_api_without_historical_literals():
    assert callable(build_report)
    assert callable(main)

    root = Path(__file__).resolve().parents[1]
    text = (root / "evaluators" / "generate_comprehensive_report.py").read_text(
        encoding="utf-8"
    )
    for stale in ("805.5", "63.6 km", "4.14 GiB", "单次 807 s"):
        assert stale not in text
