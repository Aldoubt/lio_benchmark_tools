#!/usr/bin/env python3
"""Sample a process tree and publish live and final resource JSON snapshots."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import tempfile
import time
from pathlib import Path

import psutil


def _atomic_write(path: Path, value: dict) -> None:
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


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def _summary(samples: list[dict], started: float, status: str, error: str | None = None, started_at: str | None = None) -> dict:
    result = {
        "status": status,
        "started_at": started_at or _now(),
        "finished_at": _now() if status != "live" else None,
        "wall_time_s": time.monotonic() - started,
        "updated_at": _now(),
        "samples": len(samples),
        "latest": samples[-1] if samples else None,
        # Keep the complete time series so post-run plots cover the whole bag,
        # not only the last 600 samples. The benchmark runs are short enough
        # that this remains small compared with the recorded trajectory bag.
        "sample_history": samples,
        "mean_cpu_percent": sum(x["cpu_percent"] for x in samples) / len(samples) if samples else None,
        "peak_cpu_percent": max((x["cpu_percent"] for x in samples), default=None),
        "mean_rss_bytes": sum(x["rss_bytes"] for x in samples) / len(samples) if samples else None,
        "peak_rss_bytes": max((x["rss_bytes"] for x in samples), default=None),
        "peak_threads": max((x["threads"] for x in samples), default=None),
        "disk_write_bytes": max((x["write_bytes"] for x in samples), default=None),
    }
    if error:
        result["error"] = error
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pid", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    try:
        root = psutil.Process(args.pid)
    except psutil.Error as exc:
        _atomic_write(args.output, _summary([], time.monotonic(), "failed", str(exc)))
        return 1

    samples: list[dict] = []
    started = time.monotonic()
    started_at = _now()
    process_cache: dict[int, psutil.Process] = {}
    primed: set[int] = set()
    stop_requested = False

    def stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stop_requested:
        try:
            if not root.is_running() or root.status() == psutil.STATUS_ZOMBIE:
                break
            pids = {root.pid, *(child.pid for child in root.children(recursive=True))}
            processes = []
            for pid in pids:
                process_cache.setdefault(pid, psutil.Process(pid))
                processes.append(process_cache[pid])
            rss = sum(process.memory_info().rss for process in processes)
            cpu = 0.0
            for process in processes:
                if process.pid not in primed:
                    process.cpu_percent(None)
                    primed.add(process.pid)
                else:
                    cpu += process.cpu_percent(None)
            threads = sum(process.num_threads() for process in processes)
            written = sum(getattr(process.io_counters(), "write_bytes", 0) for process in processes)
            samples.append(
                {
                    "elapsed_s": time.monotonic() - started,
                    "at": _now(),
                    "cpu_percent": cpu,
                    "rss_bytes": rss,
                    "threads": threads,
                    "write_bytes": written,
                }
            )
            live = _summary(samples, started, "live", started_at=started_at)
            live["finished_at"] = None
            _atomic_write(args.output, live)
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied) as exc:
            _atomic_write(args.output, _summary(samples, started, "finished", str(exc), started_at))
            break
        time.sleep(args.interval)

    _atomic_write(args.output, _summary(samples, started, "finished", started_at=started_at))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
