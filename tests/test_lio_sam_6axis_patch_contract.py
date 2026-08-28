from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _params(relative: str) -> dict:
    data = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    return data["/**"]["ros__parameters"]


def test_lio_sam_patch_declares_explicit_6axis_fallback():
    patch = (ROOT / "patches/lio_sam/allow_6axis_imu.patch").read_text(encoding="utf-8")
    assert 'declare_parameter("allow6AxisImu", false)' in patch
    assert "get_parameter(\"allow6AxisImu\", allow6AxisImu)" in patch
    assert "6-axis IMU fallback active" in patch
    assert "atan2(acc.y(), acc.z())" in patch
    assert "atan2(-acc.x()" in patch
    assert "if (!allow6AxisImu)" in patch


def test_lio_sam_benchmark_variants_enable_6axis_fallback():
    no_loop = _params("configs/algorithms/lio_sam_no_loop/params.yaml")
    loop = _params("configs/algorithms/lio_sam_loop/params.yaml")
    assert no_loop["allow6AxisImu"] is True
    assert loop["allow6AxisImu"] is True
