#!/usr/bin/env python3
"""Pure helpers for the project MID360 PointCloud2 binary layout."""
from __future__ import annotations

import math
import struct

# x/y/z/intensity=float32, tag/line=uint8, timestamp=float64(ns absolute)
MID360_POINT_STRUCT = struct.Struct("<ffffBBd")
MID360_POINT_STEP = MID360_POINT_STRUCT.size


def absolute_ns_float_to_uint64(value: float) -> int:
    """Convert a FLOAT64 nanosecond timestamp to the integer contract used by Livox CustomMsg."""
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"invalid absolute nanosecond timestamp: {value}")
    rounded = int(round(value))
    if rounded > 0xFFFFFFFFFFFFFFFF:
        raise ValueError(f"absolute nanosecond timestamp exceeds uint64: {rounded}")
    return rounded


def offset_ns_uint32(timestamp_ns: int, base_ns: int) -> int:
    offset = timestamp_ns - base_ns
    if offset < 0 or offset > 0xFFFFFFFF:
        raise ValueError(f"point timestamp offset outside uint32: {offset}")
    return offset
