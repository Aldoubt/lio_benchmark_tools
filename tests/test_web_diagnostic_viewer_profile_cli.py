from pathlib import Path

from web_diagnostic_viewer import parse_args


def test_web_diagnostic_viewer_accepts_empty_recording_profile(tmp_path):
    args = parse_args([
        "--run", str(tmp_path),
        "--web-profile", "empty",
        "--no-browser",
    ])
    assert args.run == Path(tmp_path)
    assert args.web_profile == "empty"
    assert args.no_browser is True
