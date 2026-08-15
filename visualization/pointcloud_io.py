#!/usr/bin/env python3
"""Small readers for standardized benchmark point-cloud artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class PointCloudData:
    xyz: np.ndarray
    intensity: np.ndarray | None

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        if self.xyz.size == 0:
            raise ValueError("point cloud is empty")
        return np.min(self.xyz, axis=0), np.max(self.xyz, axis=0)

    def cropped(self, min_xyz: tuple[float, float, float], max_xyz: tuple[float, float, float]) -> "PointCloudData":
        low = np.asarray(min_xyz, dtype=np.float64)
        high = np.asarray(max_xyz, dtype=np.float64)
        mask = np.all((self.xyz >= low) & (self.xyz <= high), axis=1)
        intensity = self.intensity[mask] if self.intensity is not None else None
        return PointCloudData(self.xyz[mask], intensity)


def read_standard_ply(path: str | Path) -> PointCloudData:
    """Read the binary little-endian x/y/z/intensity PLY written by standardize_map.py."""
    path = Path(path)
    with path.open("rb") as stream:
        header_lines: list[str] = []
        while True:
            raw = stream.readline()
            if not raw:
                raise ValueError(f"unterminated PLY header: {path}")
            line = raw.decode("ascii").rstrip("\r\n")
            header_lines.append(line)
            if line == "end_header":
                break
        if header_lines[:2] != ["ply", "format binary_little_endian 1.0"]:
            raise ValueError(f"only benchmark binary little-endian PLY is supported: {path}")
        vertex_line = next((line for line in header_lines if line.startswith("element vertex ")), None)
        if vertex_line is None:
            raise ValueError(f"PLY missing vertex count: {path}")
        count = int(vertex_line.split()[-1])
        expected = [
            "property float x",
            "property float y",
            "property float z",
            "property float intensity",
        ]
        properties = [line for line in header_lines if line.startswith("property ")]
        if properties != expected:
            raise ValueError(f"unexpected benchmark PLY properties: {properties}")
        records = np.fromfile(
            stream,
            dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4")],
            count=count,
        )
    if len(records) != count:
        raise ValueError(f"PLY truncated: expected {count} vertices, read {len(records)}")
    xyz = np.column_stack((records["x"], records["y"], records["z"])).astype(np.float64)
    return PointCloudData(xyz=xyz, intensity=np.asarray(records["intensity"], dtype=np.float64))
