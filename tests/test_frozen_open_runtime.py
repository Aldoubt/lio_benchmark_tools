import os
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "benchmark_base" / "bin" / "lio-benchmark"


def test_repo_cli_exposes_freeze_venv_bin_to_native_viewer_lookup(monkeypatch):
    original_path = "/usr/local/bin:/usr/bin:/bin"
    monkeypatch.setenv("PATH", original_path)

    runpy.run_path(str(LAUNCHER), run_name="lio_benchmark_launcher_contract")

    expected = str((ROOT / ".venv-freeze" / "bin").resolve())
    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[0] == expected
    assert os.pathsep.join(parts[1:]) == original_path
