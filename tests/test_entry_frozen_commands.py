from pathlib import Path

from lio_benchmark import entry


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
