import json
from pathlib import Path
from lio_benchmark.manifest import load_manifest, validate_manifest

def test_current_manifest_v2_is_valid():
    path=Path(__file__).parents[1]/"benchmark_base/config/navigation_20260719_164431.json"
    errors=validate_manifest(load_manifest(path),check_paths=True)
    assert errors == []

def test_v1_requires_migration():
    assert any("migrate-manifest" in x for x in validate_manifest({"schema_version":1},check_paths=False))
