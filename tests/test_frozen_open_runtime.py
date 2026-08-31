from pathlib import Path
from types import SimpleNamespace

from lio_benchmark.frozen_bundle import _resolve_rerun_executable


def test_resolve_rerun_executable_falls_back_to_repo_local_freeze_venv(tmp_path):
    repo_root = tmp_path / "repo"
    executable = repo_root / ".venv-freeze" / "bin" / "rerun"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)

    resolved = _resolve_rerun_executable(
        executable_resolver=lambda _: None,
        repo_root=repo_root,
    )

    assert resolved == str(executable.resolve())


def test_resolve_rerun_executable_prefers_path_lookup(tmp_path):
    repo_root = tmp_path / "repo"
    executable = repo_root / ".venv-freeze" / "bin" / "rerun"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)

    resolved = _resolve_rerun_executable(
        executable_resolver=lambda _: "/opt/rerun/bin/rerun",
        repo_root=repo_root,
    )

    assert resolved == "/opt/rerun/bin/rerun"
