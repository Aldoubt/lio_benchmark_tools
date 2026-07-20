"""Datatype-aware PointCloud2 scalar access (ROS PointField constants)."""
from __future__ import annotations
import struct

FORMATS = {1: "b", 2: "B", 3: "h", 4: "H", 5: "i", 6: "I", 7: "f", 8: "d"}


def read_scalar(data: bytes, offset: int, datatype: int, bigendian: bool = False) -> int | float:
    if datatype not in FORMATS: raise ValueError(f"unsupported PointField datatype: {datatype}")
    return struct.unpack_from((">" if bigendian else "<") + FORMATS[datatype], data, offset)[0]


def relative_seconds(values: list[int | float], unit: str, semantics: str) -> list[float]:
    scales = {"s":1.0,"ms":1e-3,"us":1e-6,"ns":1e-9}
    if unit not in scales: raise ValueError(f"unresolved time unit: {unit}")
    scaled=[float(x)*scales[unit] for x in values]
    if semantics == "absolute":
        start=min(scaled); return [x-start for x in scaled]
    if semantics in ("relative_to_header","relative_to_scan_start"): return scaled
    raise ValueError(f"unresolved time semantics: {semantics}")
