#!/usr/bin/env python3
"""ROS-message-agnostic point cloud extraction and scan timestamp helpers.

The functions operate on duck-typed message objects so their binary/time
contracts can be unit-tested without importing a ROS runtime. ROS bag reading
and message deserialization remain in evaluator executables.
"""
from __future__ import annotations

from typing import Any

import numpy as np


POINTFIELD_DTYPES = {
    1: "i1",
    2: "u1",
    3: "<i2",
    4: "<u2",
    5: "<i4",
    6: "<u4",
    7: "<f4",
    8: "<f8",
}


def pointcloud_dtype(msg: Any) -> np.dtype:
    if msg.is_bigendian:
        raise ValueError("big-endian PointCloud2 is not supported")
    names: list[str] = []
    formats: list[Any] = []
    offsets: list[int] = []
    for field in msg.fields:
        if field.datatype not in POINTFIELD_DTYPES:
            raise ValueError(f"unsupported PointField datatype {field.datatype} for {field.name}")
        names.append(field.name)
        base = np.dtype(POINTFIELD_DTYPES[field.datatype])
        formats.append(base if field.count == 1 else (base, (field.count,)))
        offsets.append(field.offset)
    return np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": msg.point_step})


def cloud_rows(msg: Any, point_step: int, near_range_m: float) -> np.ndarray:
    if point_step < 1:
        raise ValueError("point_step must be >= 1")
    if hasattr(msg, "points") and hasattr(msg, "point_num"):
        points = msg.points[::point_step]
        if not points:
            return np.empty((0, 4), dtype=np.float32)
        xyz = np.asarray([(point.x, point.y, point.z) for point in points], dtype=np.float64)
        intensity = np.asarray([point.reflectivity for point in points], dtype=np.float64)
        valid = np.isfinite(xyz).all(axis=1) & np.isfinite(intensity)
        if near_range_m > 0:
            valid &= np.linalg.norm(xyz, axis=1) >= near_range_m
        return np.column_stack((xyz[valid], intensity[valid])).astype(np.float32)
    if msg.row_step != msg.point_step * msg.width:
        raise ValueError("PointCloud2 row padding is not supported by the unified map standardizer")
    dtype = pointcloud_dtype(msg)
    points = np.frombuffer(msg.data, dtype=dtype, count=msg.width * msg.height)[::point_step]
    for field in ("x", "y", "z"):
        if field not in points.dtype.names:
            raise ValueError(f"PointCloud2 missing required field: {field}")
    xyz = np.column_stack((points["x"], points["y"], points["z"])).astype(np.float64)
    intensity = (
        np.asarray(points["intensity"], dtype=np.float64)
        if "intensity" in (points.dtype.names or ()) and points["intensity"].ndim == 1
        else np.zeros(len(points), dtype=np.float64)
    )
    valid = np.isfinite(xyz).all(axis=1) & np.isfinite(intensity)
    if near_range_m > 0:
        valid &= np.linalg.norm(xyz, axis=1) >= near_range_m
    return np.column_stack((xyz[valid], intensity[valid])).astype(np.float32)


def point_time_to_seconds(value: float, unit: str) -> float:
    scales = {
        "s": 1.0,
        "sec": 1.0,
        "ms": 1e-3,
        "us": 1e-6,
        "ns": 1e-9,
        "ns_absolute": 1e-9,
        "us_absolute": 1e-6,
    }
    if unit not in scales:
        raise ValueError(f"unsupported point time unit: {unit}")
    return float(value) * scales[unit]


def scan_timestamp(
    msg: Any,
    bag_stamp_ns: int,
    point_time_field: str,
    point_time_unit: str,
) -> tuple[float, str]:
    stamp = getattr(getattr(msg, "header", None), "stamp", None)
    if stamp is not None and (stamp.sec != 0 or stamp.nanosec != 0):
        return stamp.sec + stamp.nanosec * 1e-9, "HEADER_STAMP"
    if point_time_field:
        if hasattr(msg, "points") and hasattr(msg, "timebase") and msg.points:
            first = getattr(msg.points[0], point_time_field, None)
            if first is not None:
                timebase = point_time_to_seconds(float(msg.timebase), "ns_absolute")
                offset_unit = "ns" if point_time_unit == "ns_relative_to_timebase" else point_time_unit
                offset = point_time_to_seconds(float(first), offset_unit)
                return timebase + offset, f"CUSTOM_POINT:{point_time_field}:{point_time_unit}"
        dtype = pointcloud_dtype(msg)
        if point_time_field in (dtype.names or ()) and msg.width * msg.height:
            values = np.frombuffer(msg.data, dtype=dtype, count=msg.width * msg.height)[point_time_field]
            values = np.asarray(values).reshape(-1)
            finite = values[np.isfinite(values)]
            if finite.size:
                return point_time_to_seconds(float(finite[0]), point_time_unit), f"POINT_FIELD:{point_time_field}:{point_time_unit}"
    return bag_stamp_ns * 1e-9, "ROSBAG_RECORD_TIME"
