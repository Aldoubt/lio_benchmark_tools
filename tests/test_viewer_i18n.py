import pytest

from viewer_i18n import normalize_language, tr, translate_anomaly_types


def test_chinese_display_strings():
    assert normalize_language("zh-CN") == "zh-CN"
    assert tr("zh-CN", "view.map_trajectories") == "地图与轨迹"
    assert tr("zh-CN", "view.raw_lidar") == "当前原始激光点云"
    assert translate_anomaly_types("zh-CN", ["position_jump", "yaw_jump"]) == [
        "位置突变",
        "航向突变",
    ]


def test_english_display_strings():
    assert tr("en", "view.map_trajectories") == "Map + trajectories"
    assert translate_anomaly_types("en", ["position_jump"]) == ["Position jump"]


def test_missing_translation_key_fails_loudly():
    with pytest.raises(KeyError, match="missing.key"):
        tr("zh-CN", "missing.key")
