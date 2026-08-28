#!/usr/bin/env python3
"""Record wall-clock to ROS /clock anchors for strict benchmark time alignment."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _iso_from_ns(value: int) -> str:
    return dt.datetime.fromtimestamp(value * 1e-9, tz=dt.timezone.utc).isoformat()


def make_anchor(wall_time_ns: int, sec: int, nanosec: int, sequence: int) -> dict[str, Any]:
    ros_time_ns = int(sec) * 1_000_000_000 + int(nanosec)
    return {
        "wall_time_ns": int(wall_time_ns),
        "at": _iso_from_ns(int(wall_time_ns)),
        "ros_time_ns": ros_time_ns,
        "ros_time_s": ros_time_ns * 1e-9,
        "sequence": int(sequence),
    }


@dataclass
class AnchorBuffer:
    anchors: list[dict[str, Any]] = field(default_factory=list)
    wall_time_backtracks: int = 0
    ros_time_backtracks: int = 0
    started_at: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())

    def append(self, anchor: dict[str, Any]) -> None:
        if self.anchors:
            previous = self.anchors[-1]
            self.wall_time_backtracks += int(int(anchor["wall_time_ns"]) < int(previous["wall_time_ns"]))
            self.ros_time_backtracks += int(int(anchor["ros_time_ns"]) < int(previous["ros_time_ns"]))
        self.anchors.append(anchor)

    def snapshot(self, status: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": status,
            "started_at": self.started_at,
            "finished_at": dt.datetime.now(dt.timezone.utc).isoformat() if status != "live" else None,
            "samples": len(self.anchors),
            "wall_time_backtracks": self.wall_time_backtracks,
            "ros_time_backtracks": self.ros_time_backtracks,
            "anchors": list(self.anchors),
        }


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-wall-interval", type=float, default=0.1)
    parser.add_argument("--write-interval", type=float, default=0.5)
    args = parser.parse_args()
    if args.min_wall_interval < 0 or args.write_interval <= 0:
        parser.error("--min-wall-interval must be >= 0 and --write-interval must be > 0")

    import rclpy
    from rosgraph_msgs.msg import Clock
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

    rclpy.init()
    node = rclpy.create_node("lio_benchmark_clock_anchor_recorder")
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=20,
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
    )
    buffer = AnchorBuffer()
    lock = threading.Lock()
    stop_requested = threading.Event()
    last_kept_wall_ns: int | None = None
    last_written_monotonic = 0.0

    def write(status: str) -> None:
        nonlocal last_written_monotonic
        with lock:
            snapshot = buffer.snapshot(status)
        _atomic_write(args.output, snapshot)
        last_written_monotonic = time.monotonic()

    def on_clock(message: Clock) -> None:
        nonlocal last_kept_wall_ns
        wall_ns = time.time_ns()
        if last_kept_wall_ns is not None and wall_ns - last_kept_wall_ns < int(args.min_wall_interval * 1e9):
            return
        with lock:
            sequence = len(buffer.anchors)
            buffer.append(make_anchor(wall_ns, message.clock.sec, message.clock.nanosec, sequence))
        last_kept_wall_ns = wall_ns
        if time.monotonic() - last_written_monotonic >= args.write_interval:
            write("live")

    node.create_subscription(Clock, "/clock", on_clock, qos)

    def stop(_signum, _frame) -> None:
        stop_requested.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    write("live")
    try:
        while rclpy.ok() and not stop_requested.is_set():
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        write("finished")
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
