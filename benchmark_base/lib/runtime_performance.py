"""Descriptive runtime resource evidence for one benchmark runner process session."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from typing import Mapping, Sequence


SCHEMA = "lio_benchmark_runtime_performance/v1"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def _linux_session_rss_kib(session_id: int) -> int | None:
    """Return current aggregate RSS for processes in one Linux session.

    Process exits can race `/proc` reads. Those races are ignored and the next
    sample is authoritative. `None` means the platform cannot provide this
    measurement, not zero RSS.
    """
    if sys.platform != "linux" or not Path("/proc").is_dir():
        return None
    try:
        page_kib = os.sysconf("SC_PAGE_SIZE") / 1024.0
    except (OSError, ValueError):
        return None

    total_pages = 0
    observed = False
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            text = (entry / "stat").read_text(encoding="utf-8")
            right_paren = text.rfind(")")
            if right_paren < 0:
                continue
            fields = text[right_paren + 2 :].split()
            # fields start at Linux /proc/<pid>/stat field 3 (state).
            if int(fields[3]) != session_id:  # field 6: session
                continue
            rss_pages = int(fields[21])  # field 24: rss
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, ValueError, IndexError):
            continue
        observed = True
        total_pages += max(rss_pages, 0)
    if not observed:
        return None
    return int(round(total_pages * page_kib))


def run_process_with_metrics(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    log_path: Path,
    algorithm_id: str,
    output_path: Path,
    sample_period_s: float = 0.2,
) -> int:
    """Run one benchmark command and atomically record descriptive resources.

    CPU time uses the standard-library child rusage delta. Peak RSS is the
    maximum sampled aggregate resident set across the new Linux process
    session, so the shell adapter and estimator descendants stay in the same
    accounting scope. The metrics file is immutable: an existing path is an
    error and the command is not launched.
    """
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite runtime metrics: {output_path}")
    if sample_period_s <= 0:
        raise ValueError("sample_period_s must be positive")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = _now_iso()
    wall_started = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    max_rss_kib: int | None = None
    limitations: list[str] = []

    with log_path.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        while True:
            rss = _linux_session_rss_kib(process.pid)
            if rss is not None:
                max_rss_kib = rss if max_rss_kib is None else max(max_rss_kib, rss)
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(sample_period_s)

    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall_time_s = max(time.monotonic() - wall_started, 0.0)
    cpu_user_s = max(after.ru_utime - before.ru_utime, 0.0)
    cpu_system_s = max(after.ru_stime - before.ru_stime, 0.0)
    if max_rss_kib is None:
        limitations.append(
            "aggregate process-session RSS unavailable or no readable /proc sample was observed"
        )

    payload = {
        "schema": SCHEMA,
        "algorithm_id": algorithm_id,
        "measurement_method": (
            "LINUX_PROC_PROCESS_SESSION_V1"
            if sys.platform == "linux" and Path("/proc").is_dir()
            else "PORTABLE_CHILD_RUSAGE_WALL_ONLY_V1"
        ),
        "started_at": started_at,
        "finished_at": _now_iso(),
        "wall_time_s": wall_time_s,
        "cpu_user_s": cpu_user_s,
        "cpu_system_s": cpu_system_s,
        "cpu_total_s": cpu_user_s + cpu_system_s,
        "max_rss_kib": max_rss_kib,
        "returncode": returncode,
        "status": "PASS" if returncode == 0 else "FAIL",
        "single_run_descriptive": True,
        "limitations": limitations,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return int(returncode)
