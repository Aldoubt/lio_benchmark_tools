import datetime as dt
import hashlib
import json
from pathlib import Path

from freeze_experiment import freeze_directory_name, sha256_path, write_json_atomic


def test_sha256_path_hashes_file_bytes(tmp_path):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"abc")
    digest, size = sha256_path(path)
    assert digest == hashlib.sha256(b"abc").hexdigest()
    assert size == 3


def test_sha256_path_directory_is_sorted_and_content_sensitive(tmp_path):
    root = tmp_path / "bag"
    root.mkdir()
    (root / "b.db3").write_bytes(b"B")
    (root / "a.yaml").write_bytes(b"A")
    first, size = sha256_path(root)
    assert size == 2
    (root / "b.db3").write_bytes(b"C")
    second, _ = sha256_path(root)
    assert first != second


def test_freeze_directory_name_is_sanitized_and_deterministic():
    created = dt.datetime(2026, 8, 30, 15, 40, 5, tzinfo=dt.timezone.utc)
    assert freeze_directory_name("greenhouse/run 01", created, "abcdef12") == (
        "greenhouse_run_01_20260830T154005Z_abcdef12"
    )


def test_write_json_atomic_leaves_only_final_file(tmp_path):
    path = tmp_path / "freeze_manifest.json"
    write_json_atomic(path, {"freeze_state": "INCOMPLETE"})
    assert json.loads(path.read_text(encoding="utf-8"))["freeze_state"] == "INCOMPLETE"
    assert not list(tmp_path.glob("*.tmp"))
