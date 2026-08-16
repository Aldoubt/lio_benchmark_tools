#!/usr/bin/env python3
"""Deterministic run-level LiDAR scan selection manifest helpers."""
from __future__ import annotations

from dataclasses import dataclass
import csv
import math
from pathlib import Path
from typing import Iterable


CSV_FIELDS = (
    "scan_index",
    "timestamp_s",
    "timestamp_source",
    "bag_record_time_s",
    "lidar_topic",
    "selected",
)


@dataclass(frozen=True)
class ScanWindow:
    start_offset_s: float = 0.0
    duration_s: float | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.start_offset_s)) or self.start_offset_s < 0:
            raise ValueError("start_offset_s must be finite and >= 0")
        if self.duration_s is not None:
            if not math.isfinite(float(self.duration_s)) or self.duration_s <= 0:
                raise ValueError("duration_s must be finite and > 0 when provided")


def in_scan_window(
    bag_record_time_s: float,
    first_lidar_record_time_s: float,
    window: ScanWindow,
) -> bool:
    relative = float(bag_record_time_s) - float(first_lidar_record_time_s)
    if relative + 1e-12 < window.start_offset_s:
        return False
    if window.duration_s is None:
        return True
    return relative <= window.start_offset_s + window.duration_s + 1e-12


@dataclass(frozen=True)
class SelectedScan:
    scan_index: int
    timestamp_s: float
    timestamp_source: str
    bag_record_time_s: float
    lidar_topic: str
    selected: bool = True

    def __post_init__(self) -> None:
        if self.scan_index < 0:
            raise ValueError("scan_index must be >= 0")
        if not math.isfinite(float(self.timestamp_s)):
            raise ValueError("timestamp_s must be finite")
        if not math.isfinite(float(self.bag_record_time_s)):
            raise ValueError("bag_record_time_s must be finite")
        if not self.timestamp_source:
            raise ValueError("timestamp_source is required")
        if not self.lidar_topic:
            raise ValueError("lidar_topic is required")
        if self.selected is not True:
            raise ValueError("selected scan manifest contains selected rows only")


def select_scan_indices(total_scans: int, scan_step: int) -> tuple[int, ...]:
    if total_scans < 0:
        raise ValueError("total_scans must be >= 0")
    if scan_step < 1:
        raise ValueError("scan_step must be >= 1")
    return tuple(range(0, total_scans, scan_step))


def _validate_rows(rows: Iterable[SelectedScan]) -> tuple[SelectedScan, ...]:
    frozen = tuple(rows)
    indices = [row.scan_index for row in frozen]
    if len(indices) != len(set(indices)):
        raise ValueError("selected scan manifest contains duplicate scan_index values")
    if indices != sorted(indices):
        raise ValueError("selected scan manifest must be sorted by scan_index")
    return frozen


def write_scan_manifest(path: Path, rows: Iterable[SelectedScan]) -> None:
    frozen = _validate_rows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in frozen:
            writer.writerow(
                {
                    "scan_index": row.scan_index,
                    "timestamp_s": f"{row.timestamp_s:.17g}",
                    "timestamp_source": row.timestamp_source,
                    "bag_record_time_s": f"{row.bag_record_time_s:.17g}",
                    "lidar_topic": row.lidar_topic,
                    "selected": "true",
                }
            )


def read_scan_manifest(path: Path) -> tuple[SelectedScan, ...]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CSV_FIELDS:
            raise ValueError(f"unexpected selected scan manifest columns: {reader.fieldnames}")
        rows = tuple(
            SelectedScan(
                scan_index=int(row["scan_index"]),
                timestamp_s=float(row["timestamp_s"]),
                timestamp_source=row["timestamp_source"],
                bag_record_time_s=float(row["bag_record_time_s"]),
                lidar_topic=row["lidar_topic"],
                selected=row["selected"].strip().lower() == "true",
            )
            for row in reader
        )
    return _validate_rows(rows)
