#!/usr/bin/env python3
"""Repository-owned display translations for the diagnostic viewer/report layer.

Machine-readable benchmark keys remain English and are never translated here.
"""
from __future__ import annotations

SUPPORTED_LANGUAGES = ("zh-CN", "en")

_TRANSLATIONS = {
    "zh-CN": {
        "view.map_trajectories": "地图与轨迹",
        "view.raw_lidar": "当前原始激光点云",
        "view.world_lidar": "世界坐标点云",
        "view.cpu": "CPU 占用",
        "view.rss": "内存占用",
        "view.motion": "运动异常",
        "view.anomaly_windows": "异常时间窗口",
        "anomaly.position_jump": "位置突变",
        "anomaly.yaw_jump": "航向突变",
        "lod.dense": "稠密",
        "lod.medium": "中等",
        "lod.sparse": "稀疏",
        "status.pose_unavailable": "姿态不可用",
    },
    "en": {
        "view.map_trajectories": "Map + trajectories",
        "view.raw_lidar": "Current raw LiDAR",
        "view.world_lidar": "World LiDAR",
        "view.cpu": "CPU",
        "view.rss": "RSS",
        "view.motion": "Motion anomalies",
        "view.anomaly_windows": "Anomaly windows",
        "anomaly.position_jump": "Position jump",
        "anomaly.yaw_jump": "Yaw jump",
        "lod.dense": "Dense",
        "lod.medium": "Medium",
        "lod.sparse": "Sparse",
        "status.pose_unavailable": "Pose unavailable",
    },
}


def normalize_language(value: str) -> str:
    language = str(value).strip()
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"unsupported viewer language {value!r}; expected one of {SUPPORTED_LANGUAGES}"
        )
    return language


def native_viewer_language(value: str) -> str:
    """Return a display language that is safe in the pinned Native Viewer.

    Rerun 0.36.3's desktop viewer font atlas does not reliably cover CJK on all
    hosts, which renders Chinese TextLog/blueprint labels as square glyphs.
    Frozen HTML/PDF reports keep their requested language; the Native Viewer
    uses English labels for deterministic cross-host readability.
    """
    normalize_language(value)
    return "en"


def tr(lang: str, key: str, **values: object) -> str:
    language = normalize_language(lang)
    try:
        text = _TRANSLATIONS[language][key]
    except KeyError as exc:
        raise KeyError(f"missing translation key: {key}") from exc
    return text.format(**values) if values else text


def translate_anomaly_types(lang: str, values: list[str]) -> list[str]:
    return [tr(lang, f"anomaly.{value}") for value in values]
