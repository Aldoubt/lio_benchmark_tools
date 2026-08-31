import os
import runpy
from pathlib import Path

from lio_benchmark import entry


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "benchmark_base" / "bin" / "lio-benchmark"


def test_entry_parses_and_dispatches_open(monkeypatch, tmp_path):
    frozen = tmp_path / "frozen"
    calls = []
    monkeypatch.setattr(entry, "open_frozen_recording", lambda path: calls.append(path) or 7, raising=False)
    monkeypatch.setattr(entry, "_legacy_main", lambda argv: (_ for _ in ()).throw(AssertionError(f"legacy path used: {argv}")))

    result = entry.main(["open", str(frozen)])

    assert result == 7
    assert calls == [frozen]


def test_entry_parses_and_dispatches_export(monkeypatch, tmp_path, capsys):
    frozen = tmp_path / "frozen"
    output = tmp_path / "delivery"
    calls = []
    monkeypatch.setattr(
        entry,
        "export_frozen_bundle",
        lambda path, output=None: calls.append((path, output)) or output,
        raising=False,
    )
    monkeypatch.setattr(entry, "_legacy_main", lambda argv: (_ for _ in ()).throw(AssertionError(f"legacy path used: {argv}")))

    result = entry.main(["export", str(frozen), "--output", str(output)])

    assert result == 0
    assert calls == [(frozen, output)]
    assert str(output) in capsys.readouterr().out


def test_entry_reports_frozen_command_errors_without_traceback(monkeypatch, tmp_path, capsys):
    frozen = tmp_path / "frozen"
    monkeypatch.setattr(
        entry,
        "open_frozen_recording",
        lambda path: (_ for _ in ()).throw(ValueError("not COMPLETE")),
        raising=False,
    )
    monkeypatch.setattr(entry, "_legacy_main", lambda argv: (_ for _ in ()).throw(AssertionError("legacy path used")))

    result = entry.main(["open", str(frozen)])

    assert result == 2
    assert "not COMPLETE" in capsys.readouterr().err


def test_entry_parses_and_dispatches_freeze(monkeypatch, tmp_path):
    run = tmp_path / "run"
    calls = []
    monkeypatch.setattr(
        entry,
        "execute_freeze",
        lambda path, *, baseline, language: calls.append((path, baseline, language)) or 0,
        raising=False,
    )
    monkeypatch.setattr(entry, "_legacy_main", lambda argv: (_ for _ in ()).throw(AssertionError(f"legacy path used: {argv}")))

    result = entry.main(["freeze", "--run", str(run), "--baseline", "point_lio", "--lang", "en"])

    assert result == 0
    assert calls == [(run, "point_lio", "en")]


def test_repo_cli_exposes_freeze_venv_bin_to_native_viewer_lookup(monkeypatch):
    original_path = "/usr/local/bin:/usr/bin:/bin"
    monkeypatch.setenv("PATH", original_path)

    runpy.run_path(str(LAUNCHER), run_name="lio_benchmark_launcher_contract")

    expected = str((ROOT / ".venv-freeze" / "bin").resolve())
    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[0] == expected
    assert os.pathsep.join(parts[1:]) == original_path
