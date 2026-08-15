#!/usr/bin/env python3
"""Serializable ROI and camera presets shared by inspector/report/demo tools."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


def _vec3(values: Iterable[float], name: str) -> tuple[float, float, float]:
    result = tuple(float(value) for value in values)
    if len(result) != 3 or not all(math.isfinite(value) for value in result):
        raise ValueError(f"{name} must contain three finite values")
    return result  # type: ignore[return-value]


@dataclass(frozen=True)
class RoiPreset:
    name: str
    min_xyz: tuple[float, float, float]
    max_xyz: tuple[float, float, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_xyz", _vec3(self.min_xyz, "min_xyz"))
        object.__setattr__(self, "max_xyz", _vec3(self.max_xyz, "max_xyz"))
        if not self.name:
            raise ValueError("ROI preset name must not be empty")
        if any(high <= low for low, high in zip(self.min_xyz, self.max_xyz)):
            raise ValueError("ROI max_xyz must be greater than min_xyz on all axes")


@dataclass(frozen=True)
class CameraPreset:
    name: str
    field_of_view_deg: float = 60.0
    lookat: tuple[float, float, float] | None = None
    eye: tuple[float, float, float] | None = None
    up: tuple[float, float, float] | None = None
    view_matrix: tuple[tuple[float, float, float, float], ...] | None = None
    viewport_width_px: int | None = None
    viewport_height_px: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("camera preset name must not be empty")
        if not 1.0 <= float(self.field_of_view_deg) <= 179.0:
            raise ValueError("field_of_view_deg must be in [1,179]")
        vector_form = self.lookat is not None or self.eye is not None or self.up is not None
        matrix_form = self.view_matrix is not None
        if vector_form and matrix_form:
            raise ValueError("camera preset must use vector form or matrix form, not both")
        if not vector_form and not matrix_form:
            raise ValueError("camera preset requires lookat/eye/up or view_matrix")
        if vector_form:
            if self.lookat is None or self.eye is None or self.up is None:
                raise ValueError("lookat, eye and up must be supplied together")
            object.__setattr__(self, "lookat", _vec3(self.lookat, "lookat"))
            object.__setattr__(self, "eye", _vec3(self.eye, "eye"))
            object.__setattr__(self, "up", _vec3(self.up, "up"))
        if matrix_form:
            rows = tuple(tuple(float(value) for value in row) for row in self.view_matrix or ())
            if len(rows) != 4 or any(len(row) != 4 for row in rows):
                raise ValueError("view_matrix must be 4x4")
            if not all(math.isfinite(value) for row in rows for value in row):
                raise ValueError("view_matrix contains non-finite values")
            if not self.viewport_width_px or not self.viewport_height_px:
                raise ValueError("matrix camera preset requires positive viewport dimensions")
            object.__setattr__(self, "view_matrix", rows)


def save_roi(path: str | Path, preset: RoiPreset) -> None:
    _write(path, {"schema": "lio_benchmark_roi/v2", **asdict(preset)})


def load_roi(path: str | Path) -> RoiPreset:
    payload = _read(path)
    if payload.get("schema") != "lio_benchmark_roi/v2":
        raise ValueError("unsupported ROI preset schema")
    return RoiPreset(payload["name"], tuple(payload["min_xyz"]), tuple(payload["max_xyz"]))


def save_camera(path: str | Path, preset: CameraPreset) -> None:
    _write(path, {"schema": "lio_benchmark_camera/v2", **asdict(preset)})


def load_camera(path: str | Path) -> CameraPreset:
    payload = _read(path)
    if payload.get("schema") != "lio_benchmark_camera/v2":
        raise ValueError("unsupported camera preset schema")
    view_matrix = payload.get("view_matrix")
    return CameraPreset(
        name=payload["name"],
        field_of_view_deg=float(payload.get("field_of_view_deg", 60.0)),
        lookat=tuple(payload["lookat"]) if payload.get("lookat") is not None else None,
        eye=tuple(payload["eye"]) if payload.get("eye") is not None else None,
        up=tuple(payload["up"]) if payload.get("up") is not None else None,
        view_matrix=tuple(tuple(row) for row in view_matrix) if view_matrix is not None else None,
        viewport_width_px=payload.get("viewport_width_px"),
        viewport_height_px=payload.get("viewport_height_px"),
    )


def orthographic_like_camera(
    name: str,
    min_xyz: Iterable[float],
    max_xyz: Iterable[float],
    view: str,
    field_of_view_deg: float = 45.0,
) -> CameraPreset:
    low = _vec3(min_xyz, "min_xyz")
    high = _vec3(max_xyz, "max_xyz")
    center = tuple((a + b) * 0.5 for a, b in zip(low, high))
    span = max(high[i] - low[i] for i in range(3))
    distance = max(span * 1.8, 1.0)
    if view == "xy":
        eye, up = (center[0], center[1], center[2] + distance), (0.0, 1.0, 0.0)
    elif view == "xz":
        eye, up = (center[0], center[1] - distance, center[2]), (0.0, 0.0, 1.0)
    elif view == "yz":
        eye, up = (center[0] + distance, center[1], center[2]), (0.0, 0.0, 1.0)
    elif view == "perspective":
        eye, up = (center[0] + distance, center[1] - distance, center[2] + distance * 0.7), (0.0, 0.0, 1.0)
    else:
        raise ValueError(f"unsupported camera view: {view}")
    return CameraPreset(name=name, field_of_view_deg=field_of_view_deg, lookat=center, eye=eye, up=up)


def _read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("preset JSON root must be an object")
    return value


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
