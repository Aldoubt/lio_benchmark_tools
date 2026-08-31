import sys
from types import SimpleNamespace

from freeze_rerun import finalize_saved_rerun_recording


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
