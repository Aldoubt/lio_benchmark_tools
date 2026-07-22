from pathlib import Path
import pytest
from lio_benchmark.run_directory import create_run

def test_existing_run_is_never_overwritten(tmp_path):
    manifest={"name":"x","output_root":str(tmp_path),"algorithms":{}}
    source=tmp_path/"manifest.json";source.write_text("{}")
    create_run(manifest,source,"same")
    assert (tmp_path/"same"/"metadata"/"run_status.json").is_file()
    assert "状态：initialized" in (tmp_path/"same"/"RUN_STATUS.md").read_text()
    with pytest.raises(FileExistsError):create_run(manifest,source,"same")
