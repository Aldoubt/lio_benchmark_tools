from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def ros_params(relative: str) -> dict:
    data = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    return data["/**"]["ros__parameters"]


def test_point_lio_extrinsic_and_time_contract():
    params = ros_params("configs/algorithms/point_lio/mid360.yaml")
    assert params["mapping"]["extrinsic_R"] == [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    assert params["preprocess"]["timestamp_unit"] == 0
    assert params["preprocess"]["scan_line"] == 4


def test_lio_sam_variants_differ_only_by_loop_parameters():
    no_loop = ros_params("configs/algorithms/lio_sam_no_loop/params.yaml")
    loop = ros_params("configs/algorithms/lio_sam_loop/params.yaml")
    assert no_loop["loopClosureEnableFlag"] is False
    assert loop["loopClosureEnableFlag"] is True
    for key, value in no_loop.items():
        if key != "loopClosureEnableFlag":
            assert loop.get(key, value) == value


def test_all_declared_rotation_matrices_have_nine_values():
    files = [
        "configs/algorithms/fast_livo2/mid360.yaml",
        "configs/algorithms/point_lio/mid360.yaml",
        "configs/algorithms/dlio/dlio.yaml",
        "configs/algorithms/lio_sam_no_loop/params.yaml",
        "configs/algorithms/lio_sam_loop/params.yaml",
    ]
    keys = {"extrinsic_R", "extrinsicRot", "extrinsicRPY", "extrinsics/baselink2imu/R", "extrinsics/baselink2lidar/R"}
    for filename in files:
        params = ros_params(filename)
        stack = [params]
        while stack:
            value = stack.pop()
            if not isinstance(value, dict):
                continue
            for key, child in value.items():
                if key in keys:
                    assert len(child) == 9, f"{filename}:{key}"
                stack.append(child)
